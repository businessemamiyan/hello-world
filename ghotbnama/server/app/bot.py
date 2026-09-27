"""ربات تلگرام قطب‌نما — دستیار پیگیر.

- ثبت هزینه/درآمد با پیام کوتاه («۲۵۰ ناهار»)
- ثبت خودکار تراکنش از پیامک بانک (از طریق /sms)
- برنامه‌ریزی ۳ اقدام روزانه، ثبت نتیجه، بستن روز و امتیاز
- یادآوری‌های زمان‌بندی‌شده و بازبینی هفتگی (scheduler.py)
فقط به صاحب اپ جواب می‌دهد.
"""
import hashlib
import json
import logging
import re
import time

from . import jalali as J
from . import model as M
from .parse_sms import looks_banky, parse_sms
from .parse_text import parse_expense
from .telegram import TGError, btn, rows

log = logging.getLogger("bot")

MAIN_KB = {"keyboard": [[{"text": "📋 امروز"}, {"text": "📝 برنامه‌ریزی"}], [{"text": "💰 پول این ماه"}, {"text": "📊 این هفته"}],
                        [{"text": "📱 اپ"}, {"text": "❓ راهنما"}]], "resize_keyboard": True, "is_persistent": True}
BUTTON_CMDS = {"📋 امروز": "/today", "📝 برنامه‌ریزی": "/plan", "💰 پول این ماه": "/money", "📊 این هفته": "/week", "📱 اپ": "/app", "❓ راهنما": "/help"}
REVIEW_Q = [("best", "۱/۵ — مهم‌ترین نتیجه این هفته چه بود؟ (با عدد)"), ("fail", "۲/۵ — بزرگ‌ترین شکست؟"), ("lesson", "۳/۵ — چه یاد گرفتی؟"),
            ("stop", "۴/۵ — چه چیزی باید متوقف شود؟"), ("focus", "۵/۵ — تمرکز هفته آینده در یک جمله؟")]
CAT_EMOJI = {"income": "💵", "future": "🏗", "growth": "📚"}
ST_EMOJI = {"todo": "⏳", "done": "✅", "partial": "◐", "skipped": "❌"}

HELP = """راهنمای قطب‌نما

💸 ثبت هزینه: فقط بنویس
«۲۵۰ ناهار» ← ۲۵۰ هزار تومان
«۲ تومن مکانیک» ← ۲ میلیون
«دیروز ۱.۵ میلیون قسط»
«۱۸۰۰۰۰ تومان بنزین» ← خود تومان
💵 واریز/درآمد: «+۳۲ میلیون حقوق» یا «۵ میلیون واریز پروژه»
عدد بدون واحد: زیر ۱۰ = میلیون، ۱۰ تا ۹۹۹ = هزار تومان. برداشت ربات همیشه نمایش داده می‌شود و با دکمه اصلاح می‌شود.

📝 برنامه روزانه: /plan — ۳ اقدام (درآمدساز، ساخت آینده، یادگیری). آخر خط «۹۰د» یعنی زمان تخمینی ۹۰ دقیقه.
📋 /today — وضعیت امروز و ثبت نتیجه
💰 /money — پول این ماه · 📊 /week — این هفته
↩️ /undo — حذف آخرین تراکنش · /cancel — خروج از حالت فعلی
📦 /export — فایل پشتیبان (برای اپ داخل Claude)
⏸ /snooze — یادآوری‌ها ۱ ساعت عقب بیفتد (فقط همین)

پیامک‌های بانک خودکار ثبت می‌شوند و فقط دسته‌شان را می‌پرسم."""


def tail_minutes(text):
    """«نتیجه ... ۸۰» یا «... ۸۰ د» → (متن, ۸۰)"""
    t = J.to_latin(text).strip()
    m = re.search(r"\s(\d{1,3})\s*(د|دقیقه|min)?$", t)
    if m and 0 < int(m.group(1)) <= 600:
        return t[: m.start()].strip(), int(m.group(1))
    return t, 0


class Bot:
    def __init__(self, store, tg, cfg):
        self.store, self.tg, self.cfg = store, tg, cfg

    # ---------- پایه ----------
    def owner(self):
        return self.cfg.owner_id or self.store.kget("owner")

    def real(self):
        return M.ensure(self.store.get()[1].setdefault("real", {}))

    async def mut(self, fn):
        return await self.store.mutate(lambda root: fn(M.ensure(root.setdefault("real", {}))))

    def today(self):
        return J.today_n()

    def conv(self):
        return self.store.kget("conv") or {}

    def set_conv(self, c):
        if c:
            self.store.kset("conv", c)
        else:
            self.store.kdel("conv")

    async def say(self, text, kb=None, reply_kb=None):
        o = self.owner()
        if not o:
            return None
        return await self.tg.send(o, text, kb=kb, reply_kb=reply_kb)

    def app_button(self):
        if not self.cfg.public_url:
            return None
        return [[{"text": "📱 باز کردن اپ", "web_app": {"url": self.cfg.public_url.rstrip("/") + "/app"}}]]

    # ---------- ورودی‌ها ----------
    async def handle(self, u):
        if "callback_query" in u:
            return await self.on_callback(u["callback_query"])
        msg = u.get("message")
        if not msg:
            return
        chat = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()
        if not self.owner():
            if text.startswith("/start") and self.cfg.setup_code and text.split()[-1] == self.cfg.setup_code:
                self.store.kset("owner", chat)
                await self.tg.send(chat, "✅ این ربات حالا فقط برای توست.\n\n" + HELP, reply_kb=MAIN_KB)
            return
        if chat != self.owner():
            return
        self.store.kset("last_seen", time.time())
        if msg.get("document"):
            return await self.on_document(msg["document"])
        if not text:
            return
        text = BUTTON_CMDS.get(text, text)
        if text.startswith("/"):
            return await self.on_command(text)
        c = self.conv()
        mode = c.get("mode")
        if mode == "plan":
            return await self.plan_add(c, text)
        if mode in ("result", "reason"):
            return await self.save_result(c, text)
        if mode == "review":
            return await self.review_answer(c, text)
        return await self.on_money_text(text)

    async def on_command(self, text):
        cmd = text.split()[0].split("@")[0]
        if cmd in ("/start", "/help"):
            return await self.say(HELP, reply_kb=MAIN_KB)
        if cmd == "/cancel":
            self.set_conv(None)
            return await self.say("از حالت فعلی خارج شدی.")
        if cmd == "/today":
            return await self.send_day(self.today())
        if cmd == "/plan":
            return await self.start_plan(self.today())
        if cmd == "/money":
            return await self.send_money()
        if cmd == "/week":
            return await self.send_week()
        if cmd == "/app":
            kb = self.app_button()
            return await self.say("اپ کامل (داشبورد، اهداف، پروژه‌ها، پول):" if kb else "آدرس اپ (PUBLIC_URL) تنظیم نشده.", kb=kb)
        if cmd == "/export":
            return await self.send_export()
        if cmd == "/undo":
            return await self.undo()
        if cmd == "/snooze":
            self.store.kset("snooze_until", time.time() + 3600)
            return await self.say("⏸ یادآوری‌ها تا ۱ ساعت دیگر عقب افتاد. بیشتر از این نه.")
        if cmd == "/review":
            return await self.start_review(J.week_start(self.today()))
        return await self.say("این دستور را نمی‌شناسم. /help")

    # ---------- پول ----------
    def txn_text(self, t, real, prefix="✅ ثبت شد"):
        kind = "واریز" if t["dir"] == "in" else "هزینه"
        when = "امروز" if t["n"] == self.today() else "دیروز" if t["n"] == self.today() - 1 else J.fa_day(t["n"])
        line = f"{prefix}: {kind} {M.exact(t['amount'])} تومان"
        if t.get("note"):
            line += f" — {t['note']}"
        line += f"\n{when}"
        if t.get("bank"):
            line += f" · بانک {t['bank']}"
        if t.get("balance") is not None:
            line += f" · مانده {M.money(t['balance'])}"
        if t.get("streamId"):
            s = M.by_id(real["streams"], t["streamId"])
            line += f"\nدرآمدِ «{s['name'] if s else '?'}» — در اپ هم ثبت شد."
        elif t.get("cat"):
            line += f"\nدسته: {t['cat']}"
        else:
            line += "\n⚠️ دسته ندارد؛ انتخاب کن:"
        return line

    def cat_kb(self, t, real):
        if t["dir"] == "out":
            b = [btn(c, f"c:{t['id']}:{i}") for i, c in enumerate(M.EXP_CATS)] + [btn(M.SELF, f"c:{t['id']}:s")]
        else:
            b = [btn("💵 " + s["name"], f"s:{t['id']}:{i}") for i, s in enumerate(real["streams"]) if s.get("status") != "stopped"]
            b += [btn(c, f"o:{t['id']}:{i}") for i, c in enumerate(M.IN_OTHER + [M.SELF])]
        kb = rows(b, 3)
        kb.append([btn("🗑 حذف", f"x:{t['id']}")])
        return kb

    def txn_kb(self, t, real, implicit=False):
        if not t.get("cat"):
            return self.cat_kb(t, real)
        kb = [[btn("✏️ تغییر دسته", f"cg:{t['id']}"), btn("🗑 حذف", f"x:{t['id']}")]]
        if implicit:
            kb.insert(0, [btn("×۱۰۰۰", f"k:{t['id']}:u"), btn("÷۱۰۰۰", f"k:{t['id']}:d")])
        return kb

    async def on_money_text(self, text):
        p = parse_expense(text, self.today())
        if not p:
            return await self.say("متوجه نشدم. برای هزینه یک عدد بنویس، مثل «۲۵۰ ناهار». راهنما: /help")

        def add(real):
            t = M.new_txn(p["dir"], p["amount"], p["n"], note=p["note"], src="tg", cat=p["cat"])
            real["txns"].append(t)
            return t, real
        t, real = await self.mut(add)
        extra = "\n(برداشت من از عدد بدون واحد؛ اگر اشتباه است اصلاح کن)" if p["implicit"] else ""
        await self.say(self.txn_text(t, real) + extra, kb=self.txn_kb(t, real, p["implicit"]))

    async def on_sms(self, sender, text):
        """ورودی پیامک از گوشی. خروجی: وضعیت برای پاسخ HTTP."""
        h = hashlib.sha256(f"{sender}\n{text}".encode()).hexdigest()[:32]
        if self.store.sms_seen(h):
            return "duplicate"
        p = parse_sms(text)
        self.store.sms_log(h, sender, text, bool(p and "dir" in p))
        if p is None:
            if looks_banky(text):
                masked = re.sub(r"\d{6,}", lambda m: m.group(0)[:3] + "***", J.to_latin(text))[:500]
                await self.safe_say(f"❓ این پیامک بانکی را نتوانستم بخوانم. اگر تراکنش است، دستی بنویس (مثلاً «۲۵۰ خرید»):\n\n{masked}")
                return "unparsed"
            return "ignored"
        if "ignore" in p:
            return "ignored"
        today = self.today()

        def add(real):
            t = M.new_txn(p["dir"], p["amount"], today, note=p["note"], src="sms", bank=p["bank"], balance=p["balance"], cat=p["cat"], h=h)
            real["txns"].append(t)
            return t, real
        t, real = await self.mut(add)
        if p["bank"] and p["balance"] is not None:
            bal = self.store.kget("balances") or {}
            bal[p["bank"]] = {"v": p["balance"], "ts": time.time()}
            self.store.kset("balances", bal)
        await self.safe_say(self.txn_text(t, real, prefix="💳 پیامک بانک"), kb=self.txn_kb(t, real))
        return "ok"

    async def safe_say(self, text, kb=None):
        try:
            return await self.say(text, kb=kb)
        except Exception as e:  # تلگرام در دسترس نیست؛ داده ثبت شده، فقط اعلان نرفته
            log.warning("send failed: %s", e)
            pending = self.store.kget("pending_notes") or []
            pending.append(text[:1000])
            self.store.kset("pending_notes", pending[-20:])

    async def flush_pending(self):
        pending = self.store.kget("pending_notes") or []
        if not pending:
            return
        self.store.kdel("pending_notes")
        await self.say("📬 اعلان‌هایی که وقت قطعی تلگرام نرسید:\n\n" + "\n—\n".join(pending)[:3500])

    async def undo(self):
        def f(real):
            if not real["txns"]:
                return None
            last = max(real["txns"], key=lambda t: t.get("ts", 0))
            return M.delete_txn(real, last["id"])
        t = await self.mut(f)
        await self.say(f"↩️ حذف شد: {M.exact(t['amount'])} تومان {t.get('note') or ''}" if t else "تراکنشی برای حذف نیست.")

    async def send_money(self):
        real, today = self.real(), self.today()
        key = J.mk(today)
        cur = M.month_money(real, key)
        prev_key = J.last_months(today, 2)[0]
        prev = M.month_money(real, prev_key)
        _, _, dom = J.d2j(today)
        lines = [f"💰 {J.month_label(key)} (تا روز {J.fa_digits(dom)})",
                 f"درآمد (واریزهای دسته‌بندی‌شده): {M.money(cur['income'])}",
                 f"هزینه: {M.money(cur['expense'])}",
                 f"خالص: {M.money(cur['income'] + cur['otherIn'] - cur['expense'])}"]
        if prev["expense"]:
            prev_same = sum(t["amount"] for t in real["txns"] if t["dir"] == "out" and t.get("cat") != M.SELF and J.mk(t["n"]) == prev_key and J.d2j(t["n"])[2] <= dom)
            if prev_same:
                d = (cur["expense"] - prev_same) / prev_same
                lines.append(f"هزینه نسبت به همین بازه ماه قبل: {'+' if d >= 0 else '−'}{J.fa_digits(abs(round(d * 100)))}٪")
        if cur["byCat"]:
            lines.append("\nبیشترین هزینه‌ها:")
            for c, v in cur["byCat"][:6]:
                share = v / cur["expense"] * 100 if cur["expense"] else 0
                lines.append(f"• {c}: {M.money(v)} ({J.fa_digits(round(share))}٪)")
        bal = self.store.kget("balances") or {}
        if bal:
            lines.append("\nآخرین مانده از پیامک: " + "، ".join(f"{b} {M.money(x['v'])}" for b, x in bal.items()))
        kb = None
        if cur["uncat"]:
            lines.append(f"\n⚠️ {J.fa_digits(len(cur['uncat']))} تراکنش بدون دسته — تا دسته نخورند، گزارش ناقص است.")
            kb = [[btn("دسته‌بندی کن", "uc")]]
        if not cur["count"]:
            lines.append("\nاین ماه هنوز تراکنشی ثبت نشده.")
        await self.say("\n".join(lines), kb=kb)

    async def send_uncat(self):
        real = self.real()
        items = [t for t in real["txns"] if not t.get("cat")][-5:]
        if not items:
            return await self.say("تراکنش بدون دسته‌ای نمانده.")
        for t in items:
            await self.say(self.txn_text(t, real, prefix="🏷"), kb=self.cat_kb(t, real))

    # ---------- اقدام‌های روزانه ----------
    def day_text(self, real, n):
        A = M.day_actions(real, n)
        label = "امروز" if n == self.today() else "دیروز" if n == self.today() - 1 else "فردا" if n == self.today() + 1 else J.fa_day(n)
        if not A:
            return f"📋 {label}: هیچ اقدامی ثبت نشده."
        lines = [f"📋 {label} — {J.WEEKDAYS[J.wd_idx(n)]} {J.fa_day(n)}"]
        for a in A:
            p = M.by_id(real["projects"], a.get("projectId"))
            s = f"{ST_EMOJI[a['status']]} {CAT_EMOJI.get(a['cat'], '')} {a['title']}"
            if p:
                s += f"  ‹{p['name']}›"
            if a.get("result"):
                s += f"\n    ← {a['result']}"
            if a.get("reason"):
                s += f"\n    چرا نشد: {a['reason']}"
            lines.append(s)
        d = M.day(real, n)
        sc = M.day_score(real, n)
        if d.get("closed") and sc:
            lines.append(f"\n🔒 بسته شد — امتیاز {J.fa_digits(sc['total'])}/۱۰۰")
        return "\n".join(lines)

    def status_kb(self, real, n):
        d = M.day(real, n)
        if not d or d.get("closed"):
            return None
        kb = []
        for a in d["actions"]:
            if a["status"] == "todo":
                kb.append([btn(f"✅ {a['title'][:22]}", f"st:{a['id']}:d"), btn("◐", f"st:{a['id']}:p"), btn("❌", f"st:{a['id']}:s")])
        return kb or None

    async def send_day(self, n):
        real = self.real()
        kb = self.status_kb(real, n)
        if not M.day_actions(real, n) and n >= self.today():
            return await self.start_plan(n)
        await self.say(self.day_text(real, n) + ("\n\nنتیجه را ثبت کن:" if kb else ""), kb=kb)

    async def start_plan(self, n):
        real = self.real()
        A = M.day_actions(real, n)
        d = M.day(real, n)
        if d and d.get("closed"):
            return await self.say("این روز بسته شده.")
        if len(A) >= 3:
            self.set_conv(None)
            return await self.send_day(n)
        self.set_conv({"mode": "plan", "n": n})
        cat = M.next_cat(A)
        sug = M.suggestions(real, n)
        kb = [[btn(f"{p['nextAction'][:30]} ‹{p['name'][:12]}›", f"sg:{n}:{real['projects'].index(p)}")] for p in sug]
        kb.append([btn("پایان برنامه‌ریزی", "pe")])
        label = "امروز" if n == self.today() else "فردا" if n == self.today() + 1 else J.fa_day(n)
        await self.say(f"📝 برنامه {label}: {J.fa_digits(len(A))} از ۳\nاقدام بعدی ({M.CATS[cat]}) را در یک خط بنویس، یا از «اقدام بعدی» پروژه‌های فعال انتخاب کن:"
                       + ("" if sug else "\n(پیشنهادی نیست؛ در اپ برای پروژه‌های فعال «اقدام بعدی» تعریف کن.)"), kb=kb)

    async def plan_add(self, c, text, project_idx=None):
        n = c["n"]
        title, est = tail_minutes(text)

        def f(real):
            d = M.day(real, n, create=True)
            if len(d["actions"]) >= 3 or d.get("closed"):
                return None, real
            pid, gid = "", ""
            if project_idx is not None and 0 <= project_idx < len(real["projects"]):
                pid = real["projects"][project_idx]["id"]
                gid = real["projects"][project_idx].get("goalId") or ""
            a = M.new_action(title, M.next_cat(d["actions"]), pid, gid, est)
            d["actions"].append(a)
            return a, real
        a, real = await self.mut(f)
        if not a:
            self.set_conv(None)
            return await self.say("۳ اقدام کافی است. اول همین‌ها را تمام کن.")
        cnt = len(M.day_actions(real, n))
        msg = f"➕ {CAT_EMOJI[a['cat']]} «{a['title']}» ({M.CATS[a['cat']]})"
        kb = None
        if not a["projectId"]:
            aps = M.active_projects(real)
            msg += "\nبه کدام پروژه وصل است؟ (اقدام وصل‌نشده امتیاز تمرکز را کم می‌کند)"
            kb = rows([btn(p["name"][:20], f"pj:{a['id']}:{real['projects'].index(p)}") for p in aps], 2) + [[btn("بدون پروژه", f"pj:{a['id']}:-1")]]
        await self.say(msg, kb=kb)
        if cnt >= 3:
            self.set_conv(None)
            await self.say(self.day_text(real, n) + "\n\n✔ برنامه کامل شد. شب نتیجه‌اش را می‌پرسم.")
        else:
            await self.start_plan(n)

    async def set_status(self, aid, code, msg=None):
        st = {"d": "done", "p": "partial", "s": "skipped"}[code]

        def f(real):
            for k, d in real["days"].items():
                for a in d["actions"]:
                    if a["id"] == aid:
                        if d.get("closed"):
                            return None, None
                        a["status"] = st
                        return a, k
            return None, None
        a, k = await self.mut(f)
        if not a:
            return await self.say("این اقدام پیدا نشد یا روزش بسته شده.")
        n = J.parse_j(k.replace("-", "/"))
        if st == "done":
            self.set_conv({"mode": "result", "aid": aid, "n": n})
            await self.say(f"✅ «{a['title']}»\nنتیجه چه بود و چند دقیقه طول کشید؟\nمثال: «تاریخ پایلوت گرفتم ۸۰»")
        else:
            self.set_conv({"mode": "reason", "aid": aid, "n": n})
            await self.say(f"{ST_EMOJI[st]} «{a['title']}»\nچرا کامل نشد؟ (اگر رویش کار کردی، دقیقه را آخرش بنویس)")

    async def save_result(self, c, text):
        body, minutes = tail_minutes(text)

        def f(real):
            for d in real["days"].values():
                for a in d["actions"]:
                    if a["id"] == c["aid"]:
                        if c["mode"] == "result":
                            a["result"] = body
                        else:
                            a["reason"] = body
                        if minutes:
                            a["actualMin"] = minutes
                        return a
            return None
        await self.mut(f)
        self.set_conv(None)
        await self.after_status(c["n"])

    async def after_status(self, n):
        real = self.real()
        d = M.day(real, n)
        if not d:
            return
        todo = [a for a in d["actions"] if a["status"] == "todo"]
        if todo:
            return await self.say("ثبت شد. باقی‌مانده:", kb=self.status_kb(real, n))
        await self.close_day(n)

    async def close_day(self, n):
        def f(real):
            d = M.day(real, n)
            if d and not d.get("closed") and all(a["status"] != "todo" for a in d["actions"]):
                d["closed"] = True
                d["closedAt"] = int(time.time() * 1000)
            return real
        real = await self.mut(f)
        sc = M.day_score(real, n)
        prev = M.day_score(real, n - 1)
        lines = [self.day_text(real, n)]
        if sc:
            cmp = f" (روز قبل {J.fa_digits(prev['total'])})" if prev else ""
            lines.append(f"امتیاز: {J.fa_digits(sc['total'])}/۱۰۰{cmp}")
            inc_done = any(a["cat"] == "income" and a["status"] == "done" for a in M.day_actions(real, n))
            if M.day_income(real, n) <= 0 and not inc_done:
                lines.append("⚠️ امروز نه درآمدی ثبت شد، نه اقدام درآمدساز کامل شد. فردا اول همان را انجام بده.")
            elif sc["total"] < 40:
                lines.append("روز ضعیفی بود. دلیل‌هایی که نوشتی را فردا صبح جلوی چشمت می‌گذارم.")
        await self.say("\n".join(lines))

    # ---------- بازبینی هفتگی ----------
    async def start_review(self, ws):
        real, today = self.real(), self.today()
        w = M.week_stats(real, ws, today)
        ex = w["exec"]
        txt = (f"🗓 بازبینی هفته {J.fa_day(ws)} تا {J.fa_day(ws + 6)}\n"
               f"درآمد ثبت‌شده: {M.money(w['income'])} · هزینه: {M.money(w['expense'])}\n"
               f"اجرا: {J.fa_digits(round(ex * 100)) + '٪' if ex is not None else '—'} ({J.fa_digits(w['doneW'])} از {J.fa_digits(w['total'])} اقدام)\n"
               f"ساعت مؤثر: {J.fa_digits(round(w['hours'], 1))} · روز مؤثر: {J.fa_digits(w['effective'])}\n"
               f"امتیاز هفته: {J.fa_digits(w['score']) if w['score'] is not None else '—'}\n"
               f"پروژه‌های جلورفته: {'، '.join(p['name'] for p in w['projProg']) or 'هیچ‌کدام'}\n\n"
               "۵ سؤال کوتاه. «رد» یعنی بگذر.")
        self.set_conv({"mode": "review", "ws": ws, "step": 0, "ans": {}})
        await self.say(txt)
        await self.say(REVIEW_Q[0][1])

    async def review_answer(self, c, text):
        key = REVIEW_Q[c["step"]][0]
        c["ans"][key] = "" if text.strip() in ("رد", "/skip") else text.strip()
        c["step"] += 1
        if c["step"] < len(REVIEW_Q):
            self.set_conv(c)
            return await self.say(REVIEW_Q[c["step"]][1])
        self.set_conv(None)
        ws, today, ans = c["ws"], self.today(), c["ans"]

        def f(real):
            w = M.week_stats(real, ws, today)
            r = next((x for x in real["reviews"] if x.get("week") == ws), None)
            if not r:
                r = {"id": M.uid("r_"), "week": ws, "ai": ""}
                real["reviews"].append(r)
            r.update({"n": today, "ts": int(time.time() * 1000), "best": ans.get("best", ""), "fail": ans.get("fail", ""), "lesson": ans.get("lesson", ""),
                      "stop": ans.get("stop", ""), "focus": ans.get("focus", ""),
                      "auto": {"income": w["income"], "done": w["doneW"], "total": w["total"], "exec": w["exec"], "hours": w["hours"], "effective": w["effective"],
                               "score": w["score"], "projects": [p["name"] for p in w["projProg"]], "goals": [g["title"] for g in w["goalProg"]]}})
            return r
        await self.mut(f)
        await self.say("✔ بازبینی ثبت شد و در اپ هم هست. تمرکز هفته بعد را هر صبح یادآوری می‌کنم.\nگزارش مدیریتی AI را از اپ داخل Claude بساز.")

    async def send_week(self):
        real, today = self.real(), self.today()
        ws = J.week_start(today)
        w = M.week_stats(real, ws, today)
        days = [self._day_line(real, n) for n in range(ws, min(ws + 6, today) + 1)]
        ex = w["exec"]
        await self.say(f"📊 این هفته (از {J.fa_day(ws)})\n" + "\n".join(days) +
                       f"\n\nاجرا {J.fa_digits(round(ex * 100)) + '٪' if ex is not None else '—'} · روز مؤثر {J.fa_digits(w['effective'])} · ساعت مؤثر {J.fa_digits(round(w['hours'], 1))}"
                       f"\nدرآمد {M.money(w['income'])} · هزینه {M.money(w['expense'])} · امتیاز هفته {J.fa_digits(w['score']) if w['score'] is not None else '—'}")

    def _day_line(self, real, n):
        s = M.day_score(real, n)
        d = M.day(real, n)
        mark = "—" if not s else f"{J.fa_digits(s['total'])}" + ("" if d.get("closed") else " (باز)")
        return f"{J.WEEKDAYS[J.wd_idx(n)]}: {mark}"

    # ---------- پشتیبان ----------
    async def send_export(self):
        v, root = self.store.get()
        full = json.dumps(root, ensure_ascii=False).encode()
        lite = json.loads(json.dumps(root))
        r = M.ensure(lite.setdefault("real", {}))
        cut = self.today() - 90
        r["txns"] = [t for t in r["txns"] if t.get("n", 0) >= cut]
        r["coachLog"] = r["coachLog"][-6:]
        await self.tg.send_document(self.owner(), "ghotbnama-claude.json", json.dumps(lite, ensure_ascii=False).encode(),
                                    caption="برای اپ داخل Claude: تنظیمات ← بازگردانی از فایل. (تراکنش‌های ۹۰ روز اخیر)")
        await self.tg.send_document(self.owner(), "ghotbnama-full.json", full, caption=f"پشتیبان کامل (نسخه {v}). جای امن نگه دار.")

    async def on_document(self, doc):
        if not (doc.get("file_name") or "").endswith(".json"):
            return await self.say("فقط فایل پشتیبان JSON قطب‌نما را می‌پذیرم.")
        raw = await self.tg.download(doc["file_id"])
        try:
            o = json.loads(raw)
            ok = isinstance(o, dict) and o.get("v") == 2 and isinstance(o.get("real"), dict)
        except ValueError:
            ok = False
        if not ok:
            return await self.say("این فایل پشتیبان نسخه ۲ قطب‌نما نیست.")
        self.store.kset("import_pending", o)
        await self.say("⚠️ با این فایل، کل داده سرور جایگزین می‌شود (تراکنش‌ها، اهداف، پروژه‌ها). مطمئنی؟",
                       kb=[[btn("بله، جایگزین کن", "imp:y"), btn("نه", "imp:n")]])

    # ---------- دکمه‌ها ----------
    async def on_callback(self, cq):
        if not self.owner() or cq["from"]["id"] != self.owner():
            return await self.tg.answer(cq["id"])
        data = cq.get("data") or ""
        msg = cq.get("message") or {}
        chat, mid = msg.get("chat", {}).get("id"), msg.get("message_id")
        parts = data.split(":")
        await self.tg.answer(cq["id"])
        self.store.kset("last_seen", time.time())
        k = parts[0]

        if k in ("c", "s", "o", "k", "x", "cg"):
            return await self.cb_txn(k, parts, chat, mid)
        if k == "uc":
            return await self.send_uncat()
        if k == "st":
            return await self.set_status(parts[1], parts[2])
        if k == "pj":
            aid, idx = parts[1], int(parts[2])

            def f(real):
                for d in real["days"].values():
                    for a in d["actions"]:
                        if a["id"] == aid:
                            if 0 <= idx < len(real["projects"]):
                                a["projectId"] = real["projects"][idx]["id"]
                                a["goalId"] = a.get("goalId") or real["projects"][idx].get("goalId") or ""
                            return a, real
                return None, real
            a, real = await self.mut(f)
            if a:
                p = M.by_id(real["projects"], a["projectId"])
                await self.tg.edit(chat, mid, f"➕ {CAT_EMOJI[a['cat']]} «{a['title']}» ‹{p['name'] if p else 'بدون پروژه'}›")
            return
        if k == "sg":
            n, idx = int(parts[1]), int(parts[2])
            real = self.real()
            if 0 <= idx < len(real["projects"]):
                c = {"mode": "plan", "n": n}
                return await self.plan_add(c, real["projects"][idx]["nextAction"], project_idx=idx)
            return
        if k == "pe":
            self.set_conv(None)
            real = self.real()
            n = self.today()
            cnt = len(M.day_actions(real, n))
            return await self.say(self.day_text(real, n) + ("" if cnt >= 3 else f"\n\n⚠️ فقط {J.fa_digits(cnt)} اقدام. روز بدون ۳ اقدام مشخص معمولاً روز پراکنده‌ای است."))
        if k == "zz":
            self.store.kset("snooze_until", time.time() + 3600)
            return await self.say("⏸ تا ۱ ساعت دیگر.")
        if k == "plan":
            return await self.start_plan(int(parts[1]))
        if k == "imp":
            o = self.store.kget("import_pending")
            self.store.kdel("import_pending")
            if parts[1] == "y" and o:
                await self.store.mutate(lambda root: (root.clear(), root.update(o)))
                return await self.say("✔ داده سرور جایگزین شد.")
            return await self.say("لغو شد.")

    async def cb_txn(self, k, parts, chat, mid):
        tid = parts[1]
        real = self.real()
        t = M.by_id(real["txns"], tid)
        if not t:
            return await self.tg.edit(chat, mid, "این تراکنش دیگر وجود ندارد.")
        if k == "cg":
            return await self.tg.edit(chat, mid, self.txn_text(t, real, prefix="✏️ تغییر دسته"), kb=self.cat_kb(t, real))

        def f(real):
            t = M.by_id(real["txns"], tid)
            if not t:
                return None, real
            if k == "x":
                M.delete_txn(real, tid)
                return {"deleted": True, **t}, real
            if k == "c":
                M.classify_txn(real, t, cat=M.SELF if parts[2] == "s" else M.EXP_CATS[int(parts[2])])
            elif k == "s":
                i = int(parts[2])
                if 0 <= i < len(real["streams"]):
                    M.classify_txn(real, t, stream_id=real["streams"][i]["id"])
            elif k == "o":
                M.classify_txn(real, t, cat=(M.IN_OTHER + [M.SELF])[int(parts[2])])
            elif k == "k":
                sid = t.get("streamId")
                M.classify_txn(real, t, cat=t.get("cat") if not sid else None)
                t["amount"] = int(t["amount"] * 1000) if parts[2] == "u" else max(1, int(t["amount"] / 1000))
                if sid:
                    M.classify_txn(real, t, stream_id=sid)
            return t, real
        t, real = await self.mut(f)
        if not t:
            return
        if t.get("deleted"):
            return await self.tg.edit(chat, mid, f"🗑 حذف شد: {M.exact(t['amount'])} تومان {t.get('note') or ''}")
        await self.tg.edit(chat, mid, self.txn_text(t, real, prefix="✅ به‌روز شد"), kb=self.txn_kb(t, real, implicit=(k == "k")))

    # ---------- حلقه دریافت ----------
    async def poll_forever(self):
        import asyncio
        offset = self.store.kget("offset") or 0
        backoff = 2
        while True:
            try:
                ups = await self.tg.updates(offset)
                self.store.kset("tg_ok", time.time())
                backoff = 2
                if self.owner():
                    await self.flush_pending()
                for u in ups:
                    offset = u["update_id"] + 1
                    self.store.kset("offset", offset)
                    try:
                        await self.handle(u)
                    except Exception:
                        log.exception("update failed")
            except (TGError, Exception) as e:  # قطعی شبکه/پروکسی
                log.warning("poll error: %s", e)
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)

    async def setup_menu(self):
        try:
            await self.tg.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in
                               [("today", "وضعیت امروز"), ("plan", "برنامه‌ریزی ۳ اقدام"), ("money", "پول این ماه"), ("week", "این هفته"),
                                ("review", "بازبینی هفتگی"), ("undo", "حذف آخرین تراکنش"), ("export", "فایل پشتیبان"), ("snooze", "یادآوری ۱ ساعت بعد"),
                                ("help", "راهنما")]])
            if self.cfg.public_url and self.owner():
                await self.tg.call("setChatMenuButton", chat_id=self.owner(),
                                   menu_button={"type": "web_app", "text": "قطب‌نما", "web_app": {"url": self.cfg.public_url.rstrip("/") + "/app"}})
        except Exception as e:
            log.warning("menu setup failed: %s", e)
