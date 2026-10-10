"""زمان‌بند یادآوری‌ها — دستیار پیگیر (به وقت تهران).

هر نوبت فقط یک بار در روز ارسال می‌شود (در جدول kv علامت می‌خورد) و اگر سرور
یا تلگرام موقتاً قطع باشد، تا ۹۰ دقیقه بعد از زمانش دوباره تلاش می‌کند.
«snooze» فقط یادآوری‌های تکمیلی را ۱ ساعت عقب می‌اندازد؛ نوبت‌های اصلی صبح و شب را نه.
"""
import asyncio
import logging
import time

from . import jalali as J
from . import model as M
from .telegram import btn

log = logging.getLogger("scheduler")
WINDOW = 90


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


class Scheduler:
    def __init__(self, bot, cfg):
        self.bot, self.cfg, self.store = bot, cfg, bot.store

    def slots(self):
        c = self.cfg
        m, d, e, w = hm(c.morning), hm(c.midday), hm(c.evening), hm(c.weekly_time)
        return [
            ("morning", m, self.morning, False),
            ("plan_rem1", m + 120, self.plan_reminder, True),
            ("plan_rem2", m + 240, self.plan_reminder, True),
            ("midday", d, self.midday, True),
            ("evening", e, self.evening, False),
            ("eve_rem1", e + 60, self.evening_reminder, True),
            ("eve_rem2", e + 120, self.evening_reminder, True),
            ("weekly", w, self.weekly, False),
        ]

    async def tick(self, now=None):
        if not self.bot.owner():
            return []
        now = now or J.now_tehran()
        n = J.today_n(now)
        minute = now.hour * 60 + now.minute
        key = f"sent:{n}"
        sent = self.store.kget(key) or []
        snoozed = (self.store.kget("snooze_until") or 0) > time.time()
        fired = []
        for name, at, fn, reminder in self.slots():
            if name in sent or not (at <= minute < at + WINDOW):
                continue
            if name == "weekly" and now.weekday() != self.cfg.weekly_weekday:
                continue
            if reminder and snoozed:
                continue
            try:
                await fn(n, name)
            except Exception as e:  # تلگرام در دسترس نیست → دفعه بعد دوباره
                log.warning("slot %s failed: %s", name, e)
                continue
            sent.append(name)
            self.store.kset(key, sent)
            fired.append(name)
        return fired

    async def run_forever(self):
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(30)

    # ---------- نوبت‌ها ----------
    def _unclosed_days(self, real, n, days=7):
        return sum(1 for k in range(n - days, n) if (d := M.day(real, k)) and d["actions"] and not d.get("closed"))

    def _zero_days(self, real, n, days=7):
        return sum(1 for k in range(n - days, n + 1) if not M.day_actions(real, k))

    async def morning(self, n, _):
        b, real = self.bot, self.bot.real()
        y = M.day(real, n - 1)
        if y and y["actions"] and not y.get("closed"):
            kb = b.status_kb(real, n - 1)
            await b.say("🌅 صبح بخیر. اول دیروز: بسته نشده.\n" + b.day_text(real, n - 1) + "\n\nنتیجه‌ها را همین الان ثبت کن:", kb=kb)
        lines = [f"🌅 {J.WEEKDAYS[J.wd_idx(n)]} {J.fa_day(n)}"]
        last = b.store.kget("last_seen") or 0
        if last and time.time() - last > 48 * 3600:
            lines.append(f"⚠️ {J.fa_digits(int((time.time() - last) // 86400))} روز است هیچ چیزی ثبت نکرده‌ای. سیستمی که داده ندارد، کمکی نمی‌کند.")
        rv = sorted(real["reviews"], key=lambda r: r.get("week", 0))
        if rv and rv[-1].get("focus") and rv[-1].get("week", 0) >= J.week_start(n) - 7:
            lines.append(f"🎯 تمرکز این هفته: {rv[-1]['focus']}")
        ys = M.day_score(real, n - 1)
        if ys and ys["total"] < 40:
            reasons = [a["reason"] for a in y["actions"] if a.get("reason")]
            lines.append(f"دیروز امتیاز {J.fa_digits(ys['total'])} بود." + (f" دلیلی که خودت نوشتی: «{reasons[0]}»" if reasons else ""))
        uncat = [t for t in real["txns"] if not t.get("cat")]
        kb = [[btn(f"دسته‌بندی {J.fa_digits(len(uncat))} تراکنش", "uc")]] if uncat else None
        await b.say("\n".join(lines), kb=kb)
        if len(M.day_actions(real, n)) < 3:
            await b.start_plan(n)
        else:
            await b.send_day(n)

    async def plan_reminder(self, n, name):
        b, real = self.bot, self.bot.real()
        d = M.day(real, n)
        cnt = len(d["actions"]) if d else 0
        if cnt >= 3 or (d and d.get("closed")):
            return
        hours = "۲" if name == "plan_rem1" else "۴"
        msg = (f"⏰ {hours} ساعت از صبح گذشته و برنامه امروز {J.fa_digits(cnt)} از ۳ است."
               + (" بدون برنامه، امروز هم مثل روزهای پراکنده می‌گذرد." if cnt == 0 else " بقیه‌اش را کامل کن."))
        await b.say(msg, kb=[[btn("📝 برنامه‌ریزی", f"plan:{n}"), btn("⏸ ۱ ساعت بعد", "zz")]])

    async def midday(self, n, _):
        b, real = self.bot, self.bot.real()
        A = M.day_actions(real, n)
        todo = [a for a in A if a["status"] == "todo"]
        if not todo:
            return
        done = len([a for a in A if a["status"] == "done"])
        inc = next((a for a in todo if a["cat"] == "income"), None)
        msg = f"☀️ نیمه روز: ✅ {J.fa_digits(done)} · ⏳ {J.fa_digits(len(todo))}"
        if inc:
            msg += f"\nاقدام درآمدساز «{inc['title']}» هنوز مانده. بقیه کارها بعد از این."
        await b.say(msg, kb=(b.status_kb(real, n) or []) + [[btn("⏸ ۱ ساعت بعد", "zz")]])

    async def evening(self, n, _):
        b, real = self.bot, self.bot.real()
        d = M.day(real, n)
        if not d or not d["actions"]:
            z = self._zero_days(real, n)
            await b.say(f"🌙 امروز هیچ اقدامی ثبت نشد؛ یعنی روز صفر. ({J.fa_digits(z)} روز صفر در ۸ روز اخیر)\nحداقل برنامه فردا را همین الان بچین.",
                        kb=[[btn("📝 برنامه فردا", f"plan:{n + 1}")]])
            return
        if d.get("closed"):
            return
        if all(a["status"] != "todo" for a in d["actions"]):
            return await b.close_day(n)
        await b.say("🌙 وقت بستن روز.\n" + b.day_text(real, n) + "\n\nبرای هر اقدام: انجام شد؟ نتیجه؟ زمان؟ اگر نشد، چرا؟", kb=b.status_kb(real, n))

    async def evening_reminder(self, n, name):
        b, real = self.bot, self.bot.real()
        d = M.day(real, n)
        if not d or not d["actions"] or d.get("closed"):
            return
        todo = [a for a in d["actions"] if a["status"] == "todo"]
        if not todo:
            return await b.close_day(n)
        unc = self._unclosed_days(real, n)
        msg = f"⏰ روز هنوز بسته نشده — {J.fa_digits(len(todo))} اقدام بدون نتیجه."
        if unc:
            msg += f"\nاین هفته {J.fa_digits(unc)} روز دیگر هم بسته نشد. بدون ثبت نتیجه، نمی‌فهمی کجا وقتت هدر می‌رود."
        kb = (b.status_kb(real, n) or []) + [[btn("⏸ ۱ ساعت بعد", "zz")]]
        if name == "eve_rem2" and not M.day_actions(real, n + 1):
            kb.insert(0, [btn("📝 برنامه فردا", f"plan:{n + 1}")])
        await b.say(msg, kb=kb)

    async def weekly(self, n, _):
        real = self.bot.real()
        ws = J.week_start(n)
        if any(r.get("week") == ws for r in real["reviews"]):
            return
        await self.bot.start_review(ws)
