"""یادآوری فعال شبانه برای چک‌این عادت‌ها — مهرداد منتظر نمی‌ماند تا خودت بپرسی.

هر دقیقه زمان تهران را چک می‌کند؛ در ساعت تنظیم‌شده (HABIT_CHECKIN_TIME)، برای هر عادت
فعالی که امروز هنوز چک‌این نشده، یک پیام با دکمه ✅/❌ به صاحب مغز می‌فرستد.
"""
import asyncio
import datetime
import logging

try:
    from zoneinfo import ZoneInfo
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:  # pragma: no cover - fallback اگر tzdata نصب نباشد
    TEHRAN = None

log = logging.getLogger("scheduler")


def now_tehran():
    if TEHRAN is not None:
        return datetime.datetime.now(TEHRAN)
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3, minutes=30)


class Scheduler:
    def __init__(self, bot, mem, cfg):
        self.bot = bot
        self.mem = mem
        self.cfg = cfg
        self.fired_date = None
        self.fired_digest = set()
        self.backup_date = None
        self.coach_date = None
        self.evening_date = None

    async def maybe_backup(self, hhmm, today):
        if hhmm == getattr(self.cfg, "backup_time", "03:30") and self.backup_date != today:
            self.backup_date = today
            try:
                await self.bot.do_backup()
            except Exception:
                log.exception("پشتیبان‌گیری ناموفق")

    async def maybe_coach(self, hhmm, today):
        """هر روز صبح برنامهٔ مربی ساخته و خلاصه‌اش در تلگرام فرستاده می‌شود."""
        if hhmm != getattr(self.cfg, "coach_time", "07:00") or self.coach_date == today:
            return
        self.coach_date = today
        coach = getattr(self.bot, "coach", None)
        if not coach or not await self.mem.get_owner():
            return
        try:
            rec = await coach.generate()
            await self.bot.notify_owner(coach.morning_message(rec["plan"]))
        except Exception:
            log.exception("برنامهٔ صبحگاهی مربی ناموفق")

    async def maybe_evening(self, hhmm, today):
        """شب (۲۱:۳۰) یادآوری مرور شبانهٔ مربی؛ فقط اگر امروز برنامه ساخته شده باشد."""
        if hhmm != getattr(self.cfg, "coach_evening_time", "21:30") or self.evening_date == today:
            return
        self.evening_date = today
        coach = getattr(self.bot, "coach", None)
        if not coach or not await self.mem.get_owner():
            return
        try:
            st = await coach.state()
            if st["plan"] and not any(k.startswith("e") for k, v in st["done"].items() if v):
                await self.bot.notify_owner(coach.evening_message(st["stats"]["today"]["done"], st["stats"]["today"]["total"]))
        except Exception:
            log.exception("یادآوری شبانهٔ مربی ناموفق")

    async def maybe_digest(self, hhmm, today):
        times = [t.strip() for t in (getattr(self.cfg, "digest_times", "") or "").split(",") if t.strip()]
        key = (today, hhmm)
        if hhmm in times and key not in self.fired_digest:
            self.fired_digest = {k for k in self.fired_digest if k[0] == today} | {key}
            await self.bot.send_digest()

    async def maybe_fire(self):
        now = now_tehran()
        hhmm = now.strftime("%H:%M")
        today = now.date().isoformat()
        await self.maybe_digest(hhmm, today)
        await self.maybe_backup(hhmm, today)
        await self.maybe_coach(hhmm, today)
        await self.maybe_evening(hhmm, today)
        if hhmm != self.cfg.habit_checkin_time or self.fired_date == today:
            return
        self.fired_date = today
        owner = await self.mem.get_owner()
        if not owner:
            return
        pending = await self.mem.habits_pending_today()
        if not pending:
            return
        log.info("ارسال یادآوری چک‌این برای %d عادت", len(pending))
        for h in pending:
            await self.bot.prompt_habit_checkin(owner, h)

    async def run_forever(self):
        log.info("شروع زمان‌بند (ساعت چک‌این: %s تهران)", self.cfg.habit_checkin_time)
        while True:
            try:
                await self.maybe_fire()
            except Exception:
                log.exception("خطا در زمان‌بند")
            await asyncio.sleep(60)
