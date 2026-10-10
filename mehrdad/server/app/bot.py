"""حلقه‌ی ربات تلگرام مهرداد — فقط به صاحبش جواب می‌دهد.

فاز ۱: متن + سیستم عادت (ساخت/جایگزینی عادت، چک‌این روزانه با استریک).
ویس (فاز ۲) بعداً اضافه می‌شود — پیام ویس فعلاً با یک توضیح کوتاه رد می‌شود.
"""
import asyncio
import logging

import json
import re

from . import agents, finance, life, novatunnel, profile
from .coach import Coach
from .payroll import Payroll
from . import payroll as payroll_mod
from .media import MAX_IMAGE_BYTES, sniff_image
from .memory import normalize_fa, today_str
from .telegram import TGError, btn

log = logging.getLogger("bot")

HELP = """سلام، منم مهرداد، مغز دومت 🧠

هر چی بگی یادم می‌مونه و خودم تو جای درستش ثبت می‌کنم: خرج، درآمد، غذا، قلیان، کار، حقوق، حس‌وحال، ایده، هر چی.
راحت باهام حرف بزن، فرم و دکمه لازم نیست. ویس و عکس فیش هم بفرستی می‌فهمم.

ساخت عادت:
/habit <عادت خوب> — مثلاً: /habit هر روز صبح ۲۰ دقیقه مطالعه
/habit به‌جای <عادت بد>، <عادت خوب> — مثلاً: /habit به‌جای چک گوشی صبح، ۱۰ دقیقه کشش بدن
/habits — عادت‌های فعال، استریک‌ها و چک‌این امروز

خلاصه‌ها:
/today /week /month — خرج و درآمد، غذا، قلیان، کارها و عادت‌های امروز، هفته یا ماه
/finance — موجودی حساب‌ها، بدهی و اقساط و هشدارها
/salary — حقوق این ماه (از روی فیش نمونه) و ماه بعد
/goals — هدف‌هایی که از روی شناختم از تو پیشنهاد می‌دم
/nova — فروش و درآمد NovaTunnel (فقط می‌خونم)
/inbox — آخرین پیام‌های ایمیل و تلگرام که ایجنت‌ها دیدن (/mailtest برای تست ایمیل)

بیشتر بشناسمت:
/onboard — مصاحبهٔ ۱۵ سؤالی
/wife — لینک چند تا سؤال برای همسرت
/invites — لینک‌هایی که ساختی و باطل‌کردنشون

اپ:
/pair — کد وصل‌کردن اپ (۱۰ دقیقه اعتبار داره، یه بار مصرفه)
/devices — گوشی‌های وصل‌شده
/unpair <شماره> — قطع یکی از اونا

/start <کد> — معرفی خودت به‌عنوان صاحب این مغز (فقط یه بار)
/help — همین راهنما"""

NO_HABITS = "هنوز عادتی ثبت نکردی. با /habit شروع کن — یه چیز کوچیک و مشخص، نه یه آرزوی بزرگ."


def parse_habit_text(text):
    """«به‌جای X، Y» یا «X -> Y» یا فقط «Y» → (good, bad|None)"""
    t = text.strip()
    for sep in ("->", "→"):
        if sep in t:
            bad, good = t.split(sep, 1)
            return good.strip(), bad.strip() or None
    for kw in ("به‌جای", "بجای", "به جای"):
        if t.startswith(kw):
            rest = t[len(kw):].strip()
            for comma in ("،", ","):
                if comma in rest:
                    bad, good = rest.split(comma, 1)
                    return good.strip(), bad.strip() or None
    return t, None


def habit_line(h):
    streak = f"🔥{h['streak']}" if h["streak"] else "—"
    base = h["good"] if not h.get("bad") else f"{h['good']} (به‌جای {h['bad']})"
    return f"#{h['id']} {base} · استریک {streak}"


def checkin_kb(habit_id):
    return [[btn("✅ انجام دادم", f"hb:{habit_id}:1"), btn("❌ نه، امروز نه", f"hb:{habit_id}:0")]]


class Bot:
    def __init__(self, mem, tg, brain, cfg):
        self.mem = mem
        self.tg = tg
        self.brain = brain
        self.cfg = cfg
        self.brain_lock = asyncio.Lock()  # تلگرام و اپ هم‌زمان یک پروسهٔ مغز را نگیرند
        self._ctx_ids = set()             # شناسهٔ پروفایل/هدف‌هایی که در آخرین چکیده به مغز نشان داده شد
        self._ctx_debt_ids = set()        # شناسهٔ بدهی‌های فعالی که مغز در همین گفتگو دیده است
        self.coach = Coach(self)
        self.payroll = Payroll(mem)
        self.stt = None                   # app.stt.STT؛ main آن را وصل می‌کند (None = ویس خاموش)

    async def chat(self, text, images=None, voice=False):
        """یک نوبت مکالمه (هم تلگرام هم اپ): تاریخچه و حافظه را می‌خواند، می‌پرسد، و ذخیره می‌کند.
        images: لیست (media_type, bytes)؛ فقط برای همین نوبت به مغز داده می‌شود و ذخیره نمی‌شود."""
        async with self.brain_lock:
            history = await self.mem.recent_messages(20)
            recent_mem = await self.mem.recent_memory(40)
            active_habits = await self.mem.list_habits("active")
            await self.mem.add_message("user", ("📷 [عکس] " + text) if images else ("🎤 " + text) if voice else text)
            pending_q = await self.mem.kv_get("onboard_q")
            brain_text = text
            if pending_q:      # جواب یک سؤال مصاحبه است: به مغز بگو تا درست در پروفایل ثبتش کند
                q = profile.question_by_id(pending_q)
                if q:
                    brain_text = f"[کاربر داره به سؤال مصاحبه «{q[2]}» (بخش {q[1]}) جواب می‌ده؛ جواب رو در پروفایل ثبت کن]\n{text}"
            if voice:
                brain_text = ("[این پیام رو با ویس گفته و متنش خودکار نوشته شده؛ ممکنه عددها یا اسم‌ها اشتباه شنیده شده باشه. "
                              "اگه مبلغ یا نام مهمی مبهمه، قبل از ثبت بپرس.]\n" + brain_text)
            if images:
                reply, entries = await self.brain.think(history, recent_mem, brain_text, active_habits, images=images)
            else:
                reply, entries = await self.brain.think(history, recent_mem, brain_text, active_habits)
            notes = []
            if entries:
                notes = await self._apply_entries(entries, {m["id"] for m in recent_mem if m.get("id")} | self._ctx_ids)
            if notes:       # حقیقتِ سمت سرور: دقیقاً چه چیزی در اپ ثبت شد (مستقل از حرف مدل)
                reply = reply.rstrip() + "\n\n" + "\n".join(notes)
            await self.mem.add_message("assistant", reply)
        return reply

    async def profile_snapshot(self):
        """پروفایل، روتین‌ها، عادت‌های دیده‌شده و هدف‌ها (از ۳۰ روز اخیر) — بدون مدل."""
        import time as _t
        end = _t.time()
        rows = await self.mem.events_between(end - 30 * 86400, end + 86400)
        prof = await self.mem.latest_of_kinds(("profile",), 300)
        goals = await self.mem.latest_of_kinds(("goal",), 20)
        return {"profile": prof, "routines": profile.routines(rows), "habits": profile.habit_stats(rows),
                "goals": goals, "completeness": profile.completeness(prof)}

    async def context_prompt(self):
        """وضعیت مالی + چکیدهٔ شناخت کاربر؛ هر نوبت به پرامپت مغز اضافه می‌شود."""
        parts = []
        fin = await self.finance_prompt()
        if fin:
            parts.append("### وضعیت مالی واقعی کاربر (برای مشاوره و بررسی حساب‌ها؛ عددها را از همین بخش بگیر، حدس نزن):\n" + fin)
        snap = await self.profile_snapshot()
        digest = profile.build_digest(snap["profile"], snap["routines"], snap["habits"], snap["goals"])
        self._ctx_ids = {e["id"] for e in snap["profile"][-60:]} | {g["id"] for g in snap["goals"]}
        if digest:
            parts.append(digest)
        try:
            pay = await self.payroll.prompt()
            if pay:
                parts.append(pay)
        except Exception:
            log.exception("چکیدهٔ فیش حقوقی ساخته نشد")
        return "\n\n".join(parts)

    async def suggest_goals(self):
        """پیشنهاد ۳ تا ۵ هدف مشخص بر اساس آنچه مهرداد از کاربر می‌داند. خروجی: لیست {title, horizon, why, steps}."""
        ctx = await self.context_prompt()
        system = ("تو «مهرداد» مربی و مغز دوم کاربری. فقط بر پایهٔ واقعیت‌هایی که پایین می‌بینی هدف پیشنهاد بده (چیزی از خودت نساز).\n\n" + ctx)
        user = ("بر اساس آنچه از من می‌دونی (پروفایل، روتین‌ها، عادت‌ها، مالی، هدف‌های فعلی) ۳ تا ۵ هدف مشخص و قابل‌اندازه‌گیری پیشنهاد بده؛ "
                "ترکیبی از هدف کوتاه‌مدت (این ماه) و بلندمدت‌تر. هدف‌های تکراری با هدف‌های باز بالا نده. اگه عادت بدی وقتم رو می‌گیره، یکی از هدف‌ها مربوط به اون باشه. "
                "فقط و فقط یک آرایهٔ JSON معتبر بده، بدون متن اضافه: "
                '[{"title": "...", "horizon": "این ماه|۳ ماه|امسال|۳ سال", "why": "چرا برای من مهمه (یک جمله، با استناد به چیزی که از من می‌دونی)", "steps": ["قدم اول", "قدم دوم"]}]')
        async with self.brain_lock:
            raw = await self.brain.complete(system, user)
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        try:
            data = json.loads(m.group(0)) if m else []
        except ValueError:
            data = []
        out = []
        for g in data[:5]:
            if isinstance(g, dict) and str(g.get("title", "")).strip():
                raw_steps = g.get("steps")
                steps = [str(x)[:140] for x in raw_steps if str(x).strip()][:4] if isinstance(raw_steps, list) else []
                out.append({"title": str(g["title"]).strip()[:200], "horizon": str(g.get("horizon", ""))[:30],
                            "why": str(g.get("why", ""))[:300], "steps": steps})
        return out

    @staticmethod
    def _match_name(items, name, key):
        """هم‌نام دقیق → همان؛ وگرنه فقط اگر دقیقاً یک مورد شامل/مشمول نام باشد. (match, [ambiguous])"""
        n = normalize_fa(name).strip()
        exact = [x for x in items if normalize_fa(x[key]).strip() == n]
        if exact:
            return exact[0], []
        cands = [x for x in items if len(n) >= 3 and len(normalize_fa(x[key])) >= 3
                 and (n in normalize_fa(x[key]) or normalize_fa(x[key]) in n)]
        return (cands[0], []) if len(cands) == 1 else (None, cands)

    async def pay_debt(self, debt_id, amount=None, record_expense=True):
        """پرداخت یک قسط: مانده کم می‌شود، سررسید یک ماه جلالی جلو می‌رود، و (اختیاری) خرج «اقساط» هم ثبت می‌شود."""
        import datetime
        d = await self.mem.get_debt(debt_id)
        if not d or d["status"] != "active":
            return None
        amount = amount if amount is not None else (d["installment_amount"] or d["remaining"])
        remaining = max(0.0, d["remaining"] - amount)
        patch = {"remaining": remaining, "installments_paid": d["installments_paid"] + 1}
        if remaining <= 0:
            patch.update(status="paid", next_due=None)
        elif d.get("next_due"):
            patch["next_due"] = finance.add_jalali_months(datetime.date.fromisoformat(d["next_due"]), 1, d.get("due_day")).isoformat()
        updated = await self.mem.update_debt(debt_id, patch)
        if record_expense and amount:
            await self.mem.add_memory([{"type": "expense", "summary": f"قسط {d['title']}", "amount": float(amount),
                                        "category": "اقساط", "fields": {"debt_id": debt_id}}])
        return updated

    async def _apply_account_op(self, op):
        m = lambda n: life.fa(f"{int(round(n)):,}")
        accounts = await self.mem.list_accounts()
        acc, amb = self._match_name(accounts, op["name"], "name")
        if amb:
            return "⚠️ نام حساب «%s» مبهمه (%s)؛ نام دقیق‌تر بگو." % (op["name"], " یا ".join(a["name"] for a in amb[:3]))
        if acc:
            new = op["balance"] if op["mode"] == "set" else acc["balance"] + op["balance"]
            await self.mem.update_account(acc["id"], {"balance": new})
            return f"🏦 {acc['name']}: موجودی {m(new)} تومان"
        base = op["balance"]
        await self.mem.add_account(op["name"], op["kind"], base)
        return f"🏦 حساب تازهٔ «{op['name']}» ساخته شد: موجودی {m(base)} تومان"

    async def _apply_debt_op(self, op):
        import datetime
        m = lambda n: life.fa(f"{int(round(n)):,}")
        debts = [d for d in await self.mem.list_debts() if d["status"] == "active"]
        target = None
        if op.get("id") is not None and op["id"] in self._ctx_debt_ids:      # فقط شناسه‌هایی که مغز دیده است
            target = next((d for d in debts if d["id"] == op["id"]), None)
        if target is None and op.get("title"):
            target, amb = self._match_name(debts, op["title"], "title")
            if amb:
                return "⚠️ نام بدهی «%s» مبهمه (%s)؛ دقیق‌تر بگو." % (op["title"], " یا ".join(d["title"] for d in amb[:3]))
        fields = {k: op[k] for k in ("kind", "creditor", "total", "remaining", "installment_amount", "installments_total",
                                      "installments_paid", "due_day", "next_due") if k in op}
        if op["op"] == "pay":
            if not target:
                return "⚠️ نفهمیدم کدوم قسط رو پرداخت کنم؛ اسم بدهی رو بگو."
            upd = await self.pay_debt(target["id"], op.get("amount"))
            return f"✓ قسط «{target['title']}» پرداخت شد؛ مانده {m(upd['remaining'])} تومان" if upd else None
        if op["op"] == "update" or (op["op"] == "add" and target):          # add روی بدهی هم‌نام = به‌روزرسانی، نه تکرار
            if not target:
                return "⚠️ نفهمیدم کدوم بدهی رو به‌روز کنم؛ اسم بدهی رو بگو."
            if "due_day" in fields and "next_due" not in fields:
                fields["next_due"] = finance.next_due_from_day(fields["due_day"], life.now_tehran().date()).isoformat()
            if op.get("title") and op["op"] == "add":
                fields.setdefault("title", op["title"])
            upd = await self.mem.update_debt(target["id"], fields)
            return f"⛓ {upd['title']}: مانده {m(upd['remaining'])}، قسط {m(upd['installment_amount'])} تومان"
        total = fields.get("total", fields.get("remaining", 0.0))
        d = {"title": op["title"], "kind": fields.get("kind", "installment"), "creditor": fields.get("creditor"), "total": total,
             "remaining": fields.get("remaining", total), "installment_amount": fields.get("installment_amount", 0.0),
             "installments_total": fields.get("installments_total"), "installments_paid": fields.get("installments_paid", 0),
             "due_day": fields.get("due_day"), "next_due": fields.get("next_due")}
        if not d["next_due"] and d["due_day"]:
            d["next_due"] = finance.next_due_from_day(d["due_day"], life.now_tehran().date()).isoformat()
        await self.mem.add_debt(d)
        return f"⛓ بدهی تازه «{d['title']}»: مانده {m(d['remaining'])}، قسط {m(d['installment_amount'])} تومان"

    async def _apply_entries(self, entries, allowed_ids):
        """ورودی‌های مغز: جدید → ثبت؛ update_id/delete_id → فقط روی رکوردهای اخیری که مغز دیده؛ account_op/debt_op/habit_new → به‌روزرسانی اپ.
        خروجی: لیست خط‌های تأیید (حقیقت سمت سرور) برای نمایش زیر پاسخ."""
        adds, notes, pay_ops = [], [], []
        paying = any("debt_op" in e and e["debt_op"]["op"] == "pay" for e in entries)
        for e in entries:
            if "delete_id" in e:
                if e["delete_id"] in allowed_ids:
                    await self.mem.delete_event(e["delete_id"])
                    notes.append("🗑 یک رکورد اشتباه حذف شد")
                else:
                    log.warning("delete_id %s خارج از رکوردهای اخیر؛ نادیده", e["delete_id"])
            elif "update_id" in e:
                if e["update_id"] in allowed_ids:
                    patch = {k: v for k, v in e.items() if k != "update_id"}
                    await self.mem.update_event(e["update_id"], patch)
                else:
                    log.warning("update_id %s خارج از رکوردهای اخیر؛ نادیده", e["update_id"])
            elif "account_op" in e:
                notes.append(await self._apply_account_op(e["account_op"]))
            elif "debt_op" in e:
                note = await self._apply_debt_op(e["debt_op"])
                if note:
                    notes.append(note)
            elif "payroll_op" in e:
                pay_ops.append(e["payroll_op"])
            elif "payslip" in e:
                notes.append(await self._apply_payslip(e["payslip"]))
            elif "habit_new" in e:
                h = e["habit_new"]
                existing = [x for x in await self.mem.list_habits("active") if normalize_fa(x["good"]).strip() == normalize_fa(h["good"]).strip()]
                if not existing:
                    await self.mem.add_habit(h["good"], h.get("bad"))
                    notes.append(f"🔥 عادت «{h['good']}» برای پیگیری ثبت شد")
            else:
                if paying and e.get("type") == "expense" and ("قسط" in (e.get("summary") or "") or e.get("category") in ("اقساط", "قسط")):
                    continue            # pay خودش خرج «اقساط» را ثبت می‌کند؛ تکراری نشود
                adds.append(e)
        if pay_ops:
            notes.extend(await self.payroll.apply_ops(pay_ops))
        if adds:
            await self.mem.add_memory(adds)
        return [n for n in notes if n]

    async def _apply_payslip(self, ps):
        if not ps.get("month"):
            return "⚠️ ماه فیش رو نفهمیدم؛ بگو فیش کدوم ماه‌ست (مثلاً ۱۴۰۵-۰۶)."
        unit = ps.get("unit") or (await self.payroll.settings())["unit"]
        slip, bad = await self.payroll.save_actual(ps["month"], ps["raw"], unit)
        t = payroll_mod.totals(slip)
        f = lambda n: life.fa(f"{int(n):,}")
        line = f"🧾 فیش {payroll_mod.month_label(ps['month'])} ثبت شد: جمع پرداختی {f(t['total_earn'])}، کسورات {f(t['total_ded'])}، خالص {f(t['net'])} تومان"
        if bad:
            line += "\n⚠️ جمع‌های روی فیش با مجموع اقلام نمی‌خونه؛ عددها رو در اپ (حساب‌ها ← فیش حقوقی) چک کن."
        return line

    async def notify_owner(self, text):
        owner = await self.mem.get_owner()
        if owner:
            try:
                await self.tg.send(owner, text)
            except Exception:  # نبودن تلگرام نباید ثبت تراکنش را خراب کند
                log.exception("ارسال اعلان به صاحب ناموفق")

    async def dashboard(self, label):
        start, end = life.range_bounds(label)
        rows = await self.mem.events_between(start, end)
        habits = await self.mem.list_habits("active")
        d = life.build_dashboard(rows, habits, label)
        d["tasks"] = await self.mem.latest_of_kinds(("task",), 10)
        d["goals"] = await self.mem.latest_of_kinds(("goal",), 10)
        return d

    async def finance_snapshot(self):
        """حساب‌ها، بدهی‌ها و تحلیل خودکار؛ میانگین درآمد/خرج از ۹۰ روز اخیر."""
        import datetime, time as _t
        accounts = await self.mem.list_accounts()
        debts = await self.mem.list_debts()
        end = _t.time()
        rows = await self.mem.events_between(end - 90 * 86400, end + 86400, kinds=("income", "expense"))
        first = min((r["when_ts"] for r in rows), default=end)
        span_days = max(30, min(90, (end - first) / 86400 + 1))
        inc = sum(r["amount"] or 0 for r in rows if r["type"] == "income") / span_days * 30
        exp = sum(r["amount"] or 0 for r in rows if r["type"] == "expense") / span_days * 30
        summary = finance.summarize(accounts, debts, inc, exp, life.now_tehran().date(), int(span_days))
        return {"accounts": accounts, "debts": debts, "summary": summary}

    async def finance_prompt(self):
        snap = await self.finance_snapshot()
        self._ctx_debt_ids = {d["id"] for d in snap["debts"] if d["status"] == "active"}
        return finance.as_prompt(snap["accounts"], snap["debts"], snap["summary"], life.now_tehran().date())

    async def handle_finance(self, chat_id):
        snap = await self.finance_snapshot()
        s = snap["summary"]
        m = lambda n: life.fa(f"{int(round(n)):,}")
        lines = ["🏦 وضعیت مالی", f"دارایی {m(s['assets'])} | بدهی {m(s['debts_total'])} | خالص {m(s['net_worth'])} تومان"]
        for a in snap["accounts"]:
            lines.append(f"  · {a['name']}: {m(a['balance'])}")
        for d in snap["debts"]:
            if d["status"] == "active":
                due = finance.jalali_text(__import__("datetime").date.fromisoformat(d["next_due"])) if d.get("next_due") else "—"
                lines.append(f"  ⛓ {d['title']}: مانده {m(d['remaining'])}، قسط {m(d['installment_amount'])}، سررسید {due}")
        for al in s["alerts"][:5]:
            lines.append(("⚠️ " if al["level"] != "good" else "✅ ") + al["text"])
        await self.tg.send(chat_id, "\n".join(lines))

    async def ingest_external(self, kind, source, text, ts, important, dedup_key=None):
        """ورودی ایجنت‌ها (ایمیل/تلگرام): ذخیره در inbox؛ مهم‌ها فوری اعلام می‌شوند، بقیه در خلاصهٔ دوره‌ای."""
        text = text[:2000]
        inbox_id = await self.mem.add_inbox(kind, source, text, ts, dedup_key=dedup_key, notified=1 if important else 0)
        if inbox_id is None:
            return False
        if important:
            icon = {"email": "📧", "telegram": "💬"}.get(kind, "•")
            await self.notify_owner(agents.one_line(icon + " (مهم)", source, text))
        return True

    async def do_backup(self, keep=14):
        """پشتیبان روزانه در data/backups/mehrdad-YYYYMMDD.db؛ فقط ۱۴ تای آخرِ خودکار نگه داشته می‌شود."""
        import glob
        import os
        import re as _re
        d = os.path.join(self.cfg.data_dir, "backups")
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, "mehrdad-%s.db" % life.now_tehran().strftime("%Y%m%d"))
        await self.mem.backup_to(dest)
        os.chmod(dest, 0o600)
        autos = sorted(p for p in glob.glob(os.path.join(d, "mehrdad-*.db")) if _re.search(r"mehrdad-\d{8}\.db$", p))
        for old in autos[:-keep]:
            try:
                os.remove(old)
            except OSError:
                pass
        return dest

    async def handle_backup(self, chat_id):
        import os
        dest = await self.do_backup()
        await self.tg.send(chat_id, f"✅ پشتیبان ساخته شد: {os.path.basename(dest)} ({life.fa(os.path.getsize(dest) // 1024)} کیلوبایت). هر شب ساعت ۰۳:۳۰ هم خودکار ساخته می‌شه (۱۴ روز نگه‌داری).")

    async def send_digest(self):
        items = await self.mem.inbox_unnotified(("email", "telegram"))
        txt = agents.digest_text(items)
        if txt:
            await self.notify_owner(txt)
            await self.mem.mark_notified([i["id"] for i in items])
        return bool(txt)

    async def handle_inbox(self, chat_id):
        items = await self.mem.recent_inbox(("email", "telegram"), 15)
        if not items:
            await self.tg.send(chat_id, "پیام ایمیل/تلگرامی ثبت نشده‌ست. ایجنت‌ها هنوز تنظیم نشدن یا چیزی نیومده.")
            return
        await self.tg.send(chat_id, agents.digest_text(list(reversed(items)), limit=15).replace("خلاصهٔ پیام‌های جدید", "آخرین پیام‌ها"))

    async def handle_mailtest(self, chat_id):
        agent = getattr(self, "mail_agent", None)
        if agent is None:
            await self.tg.send(chat_id, "ایجنت ایمیل تنظیم نشده. EMAIL_IMAP_USER و EMAIL_IMAP_PASSWORD (App Password) رو توی .env بذار.")
            return
        ok, msg = await agent.check()
        await self.tg.send(chat_id, ("✅ " if ok else "❌ ") + msg)

    async def handle_wife(self, chat_id, arg=""):
        _, token = await self.mem.create_invite("wife", arg.strip() or "همسر", days=14, max_uses=3)
        url = f"{self.cfg.public_url}/who/{token}"
        await self.tg.send(chat_id, "لینک چند تا سؤال برای همسرت (۱۴ روز اعتبار داره و حداکثر ۳ بار باز می‌شه):\n" + url +
                           "\n\nفقط برای خودش بفرست. فقط به چند تا سؤال درباره‌ی تو جواب می‌ده و هیچ‌چیز از اطلاعات تو رو نمی‌بینه. باطل‌کردنش: /invites")

    async def handle_invites(self, chat_id):
        inv = await self.mem.list_invites()
        if not inv:
            await self.tg.send(chat_id, "لینکی ساخته نشده. با /wife بساز.")
            return
        import time as _t
        lines = [f"#{i['id']} {i['label'] or i['kind']} — {i['uses']}/{i['max_uses']} استفاده" +
                 (" — باطل" if i["revoked"] else " — منقضی" if i["expires_ts"] < _t.time() else "") for i in inv]
        await self.tg.send(chat_id, "لینک‌ها:\n" + "\n".join(lines) + "\n\nابطال: /revoke <شماره>")

    async def handle_revoke(self, chat_id, arg):
        try:
            ok = await self.mem.revoke_invite(int(arg.strip().lstrip("#")))
        except ValueError:
            ok = False
        await self.tg.send(chat_id, "باطل شد." if ok else "شمارهٔ لینک رو درست بنویس: /revoke 1")

    async def _onboard_next(self, chat_id):
        """سؤال بعدی مصاحبه (از ۱۵ سؤال) یا پایان."""
        i = int(await self.mem.kv_get("onboard_i", "0") or 0)
        if i >= len(profile.SELF_QUESTIONS):
            await self.mem.kv_set("onboard_q", None)
            await self.mem.kv_set("onboard_i", None)
            await self.tg.send(chat_id, "مصاحبه تمام شد 🙏 هر وقت چیزی عوض شد فقط بگو. با /goals برات هدف پیشنهاد می‌دم.")
            return
        qid, section, text = profile.SELF_QUESTIONS[i]
        await self.mem.kv_set("onboard_q", qid)
        await self.mem.kv_set("onboard_i", i + 1)
        await self.tg.send(chat_id, f"سؤال {life.fa(i + 1)} از {life.fa(len(profile.SELF_QUESTIONS))} ({section}):\n{text}\n\n(برای پایان: /onboard stop — برای رد کردن: بنویس «رد»)")

    async def handle_onboard(self, chat_id, arg):
        if arg.strip() == "stop":
            await self.mem.kv_set("onboard_q", None)
            await self.mem.kv_set("onboard_i", None)
            await self.tg.send(chat_id, "مصاحبه متوقف شد. با /onboard از اول شروع می‌شه.")
            return
        await self.mem.kv_set("onboard_i", "0")
        await self.tg.send(chat_id, "می‌خوام تو رو از صفر تا صد بشناسم؛ ۱۵ سؤال کوتاه‌ست و هر جوابی که دادی در پروفایلت ثبت می‌شه.")
        await self._onboard_next(chat_id)

    async def handle_goals(self, chat_id):
        await self.tg.send_chat_action(chat_id, "typing")
        goals = await self.suggest_goals()
        if not goals:
            await self.tg.send(chat_id, "فعلاً چیز کافی از تو نمی‌دونم. با /onboard شروع کن یا چند روز روزت رو برام تعریف کن.")
            return
        lines = ["🎯 هدف‌های پیشنهادی:"]
        for n, g in enumerate(goals, 1):
            lines.append(f"{life.fa(n)}. {g['title']} ({g['horizon']})\n   چرا: {g['why']}")
        await self.tg.send(chat_id, "\n".join(lines) + "\n\nبرای اضافه‌کردن، در اپ ← هدف‌ها ← «پیشنهاد هدف» رو بزن.")

    async def handle_nova(self, chat_id):
        await self.tg.send(chat_id, novatunnel.format_text(await novatunnel.snapshot(self.cfg.novatunnel_db_url)))

    async def handle_summary(self, chat_id, label, private=False):
        await self.tg.send(chat_id, life.format_text(await self.dashboard(label), private=private))

    async def handle_pair(self, chat_id):
        code = await self.mem.create_pair_code()
        await self.tg.send(chat_id, f"کد وصل‌کردن اپ (۱۰ دقیقه اعتبار داره، یه بار مصرفه):\n\n{code}\n\nبزنش تو اپ مهرداد.")

    async def handle_devices(self, chat_id):
        devs = await self.mem.list_devices()
        if not devs:
            await self.tg.send(chat_id, "هیچ دستگاهی وصل نیست. با /pair شروع کن.")
            return
        lines = [f"#{d['id']} {d['name']}" for d in devs]
        await self.tg.send(chat_id, "دستگاه‌های وصل‌شده:\n" + "\n".join(lines) + "\n\nقطع: /unpair <شماره>")

    async def handle_unpair(self, chat_id, arg):
        try:
            did = int(arg.strip().lstrip("#"))
        except ValueError:
            await self.tg.send(chat_id, "شمارهٔ دستگاه رو بنویس: /unpair 1")
            return
        ok = await self.mem.remove_device(did)
        await self.tg.send(chat_id, "قطع شد." if ok else "چنین دستگاهی نیست.")

    async def _is_owner(self, chat_id):
        owner = await self.mem.get_owner()
        return owner is not None and owner == chat_id

    async def handle_start(self, chat_id, arg):
        owner = await self.mem.get_owner()
        if owner is not None:
            if owner == chat_id:
                await self.tg.send(chat_id, "از قبل من رو می‌شناسی. بگو چی شده.")
            else:
                await self.tg.send(chat_id, "این مغز قبلاً معرفی شده و فقط برای صاحبش کار می‌کنه.")
            return
        if self.cfg.setup_code and arg == self.cfg.setup_code:
            await self.mem.set_owner(chat_id)
            await self.tg.send(chat_id, "از حالا من مهردادم، مغز دومت. هر چی بخوای بگو — یادم می‌مونه.")
        else:
            await self.tg.send(chat_id, "کد درست نیست. از SETUP_CODE توی .env استفاده کن: /start <کد>")

    async def handle_habit_add(self, chat_id, arg):
        if not arg.strip():
            await self.tg.send(chat_id, "بعد از /habit بنویس چه عادتی. مثلاً:\n/habit به‌جای سیگار وقتی استرس دارم، ۵ دقیقه نفس عمیق")
            return
        good, bad = parse_habit_text(arg)
        hid = await self.mem.add_habit(good, bad)
        if bad:
            msg = f"ثبت شد: وقتی خواستی «{bad}» رو انجام بدی، به‌جاش «{good}». از امشب چک‌این می‌گیرم ازت. #{hid}"
        else:
            msg = f"ثبت شد: «{good}». از امشب چک‌این می‌گیرم ازت — هر روز، بدون بهونه. #{hid}"
        await self.tg.send(chat_id, msg)

    async def prompt_habit_checkin(self, chat_id, habit):
        await self.tg.send(chat_id, f"امروز «{habit['good']}» رو انجام دادی؟", kb=checkin_kb(habit["id"]))

    async def handle_habits_list(self, chat_id):
        habits = await self.mem.list_habits("active")
        if not habits:
            await self.tg.send(chat_id, NO_HABITS)
            return
        lines = [habit_line(h) for h in habits]
        await self.tg.send(chat_id, "عادت‌های فعال:\n" + "\n".join(lines))
        today = today_str()
        for h in habits:
            if h["last_checkin"] != today:
                await self.prompt_habit_checkin(chat_id, h)

    async def handle_message(self, msg):
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            await self.handle_start(chat_id, arg)
            return

        if not await self._is_owner(chat_id):
            if self.cfg.owner_id and chat_id == self.cfg.owner_id:
                await self.mem.set_owner(chat_id)
            else:
                await self.tg.send(chat_id, "این مغز فقط برای صاحبش کار می‌کنه.")
                return

        if text == "/help":
            await self.tg.send(chat_id, HELP)
            return

        head = text.split(maxsplit=1)[0] if text else ""
        if head in ("/today", "/week", "/month"):
            await self.handle_summary(chat_id, head[1:], private="private" in text)
            return

        if text == "/salary":
            await self.tg.send(chat_id, await self.payroll.text())
            return

        if text == "/backup":
            await self.handle_backup(chat_id)
            return

        if text == "/inbox":
            await self.handle_inbox(chat_id)
            return

        if text == "/mailtest":
            await self.handle_mailtest(chat_id)
            return

        if text.startswith("/wife"):
            await self.handle_wife(chat_id, text[len("/wife"):])
            return

        if text == "/invites":
            await self.handle_invites(chat_id)
            return

        if text.startswith("/revoke"):
            await self.handle_revoke(chat_id, text[len("/revoke"):])
            return

        if text.startswith("/onboard"):
            await self.handle_onboard(chat_id, text[len("/onboard"):])
            return

        if text == "/goals":
            await self.handle_goals(chat_id)
            return

        if text == "/nova":
            await self.handle_nova(chat_id)
            return

        if text == "/finance":
            await self.handle_finance(chat_id)
            return

        if text == "/pair":
            await self.handle_pair(chat_id)
            return

        if text == "/devices":
            await self.handle_devices(chat_id)
            return

        if text.startswith("/unpair"):
            await self.handle_unpair(chat_id, text[len("/unpair"):])
            return

        if text.startswith("/habits"):
            await self.handle_habits_list(chat_id)
            return

        if text.startswith("/habit"):
            await self.handle_habit_add(chat_id, text[len("/habit"):])
            return

        photo = msg.get("photo")
        doc = msg.get("document") or {}
        if photo or str(doc.get("mime_type") or "").startswith("image/"):
            await self.handle_photo(chat_id, msg)
            return

        if msg.get("voice") or msg.get("audio"):
            await self.handle_voice(chat_id, msg)
            return

        if not text:
            return

        await self.tg.send_chat_action(chat_id, "typing")
        onboarding = await self.mem.kv_get("onboard_q")
        if onboarding and text.strip() in ("رد", "رد کن", "skip"):
            await self.mem.kv_set("onboard_q", onboarding)
            await self._onboard_next(chat_id)
            return
        reply = await self.chat(text)
        await self.tg.send(chat_id, reply)
        if onboarding:
            await self._onboard_next(chat_id)

    async def handle_voice(self, chat_id, msg):
        """ویس تلگرام → متن (روی خود سرور) → همان مسیر چت؛ متنِ فهمیده‌شده هم نشان داده می‌شود تا اشتباه‌شنیدن را اصلاح کنی."""
        if not self.stt or not self.stt.enabled:
            await self.tg.send(chat_id, "فعلاً فقط متن می‌فهمم؛ همون رو تایپ کن.")
            return
        v = msg.get("voice") or msg.get("audio") or {}
        if (v.get("duration") or 0) > 600 or (v.get("file_size") or 0) > 20 * 1024 * 1024:
            await self.tg.send(chat_id, "این ویس خیلی بلنده (حداکثر ۱۰ دقیقه / ۲۰ مگابایت)؛ تکه‌تکه بفرست.")
            return
        await self.tg.send_chat_action(chat_id, "typing")
        try:
            data = await self.tg.download(v["file_id"])
            suffix = ".ogg" if msg.get("voice") else ("." + str(v.get("file_name") or "audio.mp3").rsplit(".", 1)[-1][:5])
            text = await self.stt.transcribe(data, suffix=suffix)
        except Exception:
            log.exception("پردازش ویس ناموفق")
            await self.tg.send(chat_id, "نتونستم ویس رو بفهمم؛ دوباره بفرست یا تایپ کن.")
            return
        if not text:
            await self.tg.send(chat_id, "چیزی از ویس نفهمیدم؛ واضح‌تر بگو یا تایپ کن.")
            return
        await self.tg.send(chat_id, f"🎤 فهمیدم: «{text}»")
        await self.tg.send_chat_action(chat_id, "typing")
        reply = await self.chat(text, voice=True)
        await self.tg.send(chat_id, reply)

    async def handle_photo(self, chat_id, msg):
        """عکس تلگرام (فیش پرداخت، رسید، همسر، …) → مغز آن را می‌بیند و هر چه باید ثبت می‌کند."""
        file = (msg.get("photo") or [None])[-1] or msg.get("document") or {}
        if not file.get("file_id") or (file.get("file_size") or 0) > MAX_IMAGE_BYTES:
            await self.tg.send(chat_id, "این عکس برای من زیادی بزرگه؛ کوچک‌ترش رو بفرست.")
            return
        await self.tg.send_chat_action(chat_id, "typing")
        try:
            data = await self.tg.download(file["file_id"])
        except Exception:
            log.exception("دانلود عکس تلگرام ناموفق")
            await self.tg.send(chat_id, "نتونستم عکس رو بگیرم؛ دوباره بفرست.")
            return
        mt = sniff_image(data)
        if not mt or len(data) > MAX_IMAGE_BYTES:
            await self.tg.send(chat_id, "عکس رو فقط به صورت jpg یا png یا webp می‌فهمم.")
            return
        caption = (msg.get("caption") or "").strip()
        reply = await self.chat(caption or "این عکس رو ببین؛ اگه فیش پرداخت، رسید یا چیز قابل‌ثبته ثبتش کن و بگو چی خوندی.", images=[(mt, data)])
        await self.tg.send(chat_id, reply)

    async def handle_callback(self, cq):
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        data = cq.get("data", "")
        if not await self._is_owner(chat_id):
            await self.tg.answer(cq["id"])
            return
        if not data.startswith("hb:"):
            await self.tg.answer(cq["id"])
            return
        try:
            _, hid_s, done_s = data.split(":")
            hid, done = int(hid_s), done_s == "1"
        except ValueError:
            await self.tg.answer(cq["id"])
            return
        habit = await self.mem.get_habit(hid)
        if not habit:
            await self.tg.answer(cq["id"], "این عادت دیگه وجود نداره.")
            return
        result = await self.mem.checkin_habit(hid, done)
        streak = result["streak"]
        if done:
            if streak >= result["best_streak"] and streak > 1:
                fb = f"🔥 آفرین! {streak} روز پشت‌سرهم — رکورد جدیدته."
            else:
                fb = f"🔥 ثبت شد. استریک: {streak} روز."
        else:
            fb = "عیبی نداره، امروز رو بی‌خیال. استریک صفر شد — فردا دوباره از یک شروع کن."
        await self.mem.add_message("assistant", f"[چک‌این عادت #{hid}] {fb}")
        await self.tg.edit(chat_id, message_id, f"«{habit['good']}»\n{fb}")
        await self.tg.answer(cq["id"], fb)

    async def poll_forever(self):
        offset = 0
        log.info("شروع long polling")
        while True:
            try:
                updates = await self.tg.updates(offset, timeout=50)
            except TGError as e:
                log.warning("getUpdates failed: %s", e)
                continue
            except Exception:
                log.exception("خطای غیرمنتظره در polling")
                continue
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    if u.get("message"):
                        await self.handle_message(u["message"])
                    elif u.get("callback_query"):
                        await self.handle_callback(u["callback_query"])
                except Exception:
                    log.exception("خطا در پردازش آپدیت")
