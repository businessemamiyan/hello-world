"""حلقه‌ی ربات تلگرام مهرداد — فقط به صاحبش جواب می‌دهد.

فاز ۱: متن + سیستم عادت (ساخت/جایگزینی عادت، چک‌این روزانه با استریک).
ویس (فاز ۲) بعداً اضافه می‌شود — پیام ویس فعلاً با یک توضیح کوتاه رد می‌شود.
"""
import asyncio
import logging

from . import finance, life
from .memory import today_str
from .telegram import TGError, btn

log = logging.getLogger("bot")

HELP = """من مهرداد‌ام — مغز دومت.

هر چی بگی رو به‌خاطر می‌سپارم: خرج، درآمد، ایده، کار، حس‌وحال، هرچی.
فقط باهام حرف بزن، مثل یه رفیق. فرم و دکمه لازم نیست.

برای ساختن عادت:
/habit <عادت خوب> — مثلاً: /habit هر روز صبح ۲۰ دقیقه مطالعه
/habit به‌جای <عادت بد>، <عادت خوب> — مثلاً: /habit به‌جای چک گوشی صبح، ۱۰ دقیقه کشش بدن
/habits — لیست عادت‌های فعال و استریک‌هاشون + چک‌این امروز

اپ اندروید:
/today /week /month — خلاصهٔ خرج و درآمد، غذا، قلیان، کارها و عادت‌ها

/finance — موجودی حساب‌ها، بدهی و اقساط، و هشدارها

/pair — کد یک‌بارمصرف برای وصل‌کردن اپ (۱۰ دقیقه اعتبار)
/devices — دستگاه‌های وصل‌شده
/unpair <شماره> — قطع یک دستگاه

/start <کد> — معرفی خودت به‌عنوان صاحب این مغز (یک‌بار)
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

    async def chat(self, text):
        """یک نوبت مکالمه (هم تلگرام هم اپ): تاریخچه و حافظه را می‌خواند، می‌پرسد، و ذخیره می‌کند."""
        async with self.brain_lock:
            history = await self.mem.recent_messages(20)
            recent_mem = await self.mem.recent_memory(40)
            active_habits = await self.mem.list_habits("active")
            await self.mem.add_message("user", text)
            reply, entries = await self.brain.think(history, recent_mem, text, active_habits)
            await self.mem.add_message("assistant", reply)
            if entries:
                await self.mem.add_memory(entries)
        return reply

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

    async def handle_summary(self, chat_id, label, private=False):
        await self.tg.send(chat_id, life.format_text(await self.dashboard(label), private=private))

    async def handle_pair(self, chat_id):
        code = await self.mem.create_pair_code()
        await self.tg.send(chat_id, f"کد جفت‌سازی اپ (۱۰ دقیقه، یک‌بار مصرف):\n\n{code}\n\nدر اپ مهرداد وارد کن.")

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
            await self.tg.send(chat_id, "شمارهٔ دستگاه را بنویس: /unpair 1")
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
                await self.tg.send(chat_id, "این مغز قبلاً معرفی شده و فقط برای صاحبش کار می‌کند.")
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
                await self.tg.send(chat_id, "این مغز فقط برای صاحبش کار می‌کند.")
                return

        if text == "/help":
            await self.tg.send(chat_id, HELP)
            return

        head = text.split(maxsplit=1)[0] if text else ""
        if head in ("/today", "/week", "/month"):
            await self.handle_summary(chat_id, head[1:], private="private" in text)
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

        if msg.get("voice") or msg.get("audio"):
            await self.tg.send(chat_id, "فعلاً فقط متن می‌فهمم — فهمیدن ویس تو فاز بعدیه. همون رو تایپ کن.")
            return

        if not text:
            return

        await self.tg.send_chat_action(chat_id, "typing")
        reply = await self.chat(text)
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
            await self.tg.answer(cq["id"], "این عادت دیگر وجود ندارد.")
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
