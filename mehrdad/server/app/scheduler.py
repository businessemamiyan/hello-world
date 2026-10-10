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

    async def maybe_fire(self):
        now = now_tehran()
        hhmm = now.strftime("%H:%M")
        today = now.date().isoformat()
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
