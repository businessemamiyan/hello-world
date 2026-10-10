"""ایجنت ایمیل (Gmail/IMAP): فقط‌خواندنی؛ پیام‌های تازه را می‌خواند، اهمیت را با قانون می‌سنجد و به مهرداد می‌دهد.

تنظیم (در .env): EMAIL_IMAP_USER، EMAIL_IMAP_PASSWORD (App Password گوگل، نه رمز حساب)، اختیاری EMAIL_IMAP_HOST،
EMAIL_POLL_MINUTES، EMAIL_ALLOW (فرستنده/دامنه‌هایی که همیشه مهم‌اند، با کاما).
هیچ‌چیزی حذف، ارسال یا «خوانده‌شده» نمی‌شود: پوشه فقط‌خواندنی باز می‌شود و پیام‌ها با BODY.PEEK گرفته می‌شوند.
"""
import asyncio
import imaplib
import logging
import re

from . import agents

log = logging.getLogger("mail")
UID_KEY = "mail_last_uid"
MAX_PER_POLL = 30


class MailAgent:
    def __init__(self, bot, mem, cfg, imap_factory=None):
        self.bot, self.mem, self.cfg = bot, mem, cfg
        self.allow = tuple(a.strip().lower() for a in cfg.email_allow.split(",") if a.strip())
        self._factory = imap_factory or (lambda: imaplib.IMAP4_SSL(cfg.email_imap_host, 993, timeout=30))
        self._auth_warned = False

    # -- بخش بلاک‌کنندهٔ IMAP (در thread اجرا می‌شود) --
    def _fetch_new(self, last_uid):
        """→ (max_uid, [raw bytes]). اگر last_uid None بود فقط خط پایه را برمی‌گرداند (بدون پیام)."""
        M = self._factory()
        try:
            M.login(self.cfg.email_imap_user, self.cfg.email_imap_password)
            typ, _ = M.select("INBOX", readonly=True)              # فقط‌خواندنی
            if typ != "OK":
                raise imaplib.IMAP4.error("select failed")
            typ, data = M.uid("SEARCH", None, "ALL")
            uids = [int(x) for x in (data[0] or b"").split()]
            top = max(uids) if uids else 0
            if last_uid is None:
                return top, []                                       # اولین بار: از «الان» شروع کن، نه کل صندوق
            new = [u for u in uids if u > last_uid][-MAX_PER_POLL:]
            raws = []
            for u in new:
                typ, parts = M.uid("FETCH", str(u), "(BODY.PEEK[]<0.30000>)")   # PEEK: علامت خوانده‌شدن نمی‌خورد
                if typ == "OK" and parts and isinstance(parts[0], tuple):
                    raws.append((u, parts[0][1]))
            return top, raws
        finally:
            try:
                M.logout()
            except Exception:
                pass

    async def check(self):
        """تست اتصال برای /mailtest: ورود و باز کردن INBOX به‌صورت فقط‌خواندنی؛ چیزی ثبت نمی‌شود."""
        try:
            top, _ = await asyncio.to_thread(self._fetch_new, None)
            return True, f"ورود موفق به {self.cfg.email_imap_user}؛ پیام‌های تازه از همین لحظه به بعد بررسی می‌شن."
        except imaplib.IMAP4.error as e:
            return False, "ورود/IMAP ناموفق: " + re.sub(r"\s+", " ", str(e))[:80]
        except Exception as e:
            return False, f"اتصال ناموفق ({type(e).__name__})"

    async def poll_once(self):
        last = await self.mem.kv_get(UID_KEY)
        last_uid = int(last) if last is not None else None
        top, raws = await asyncio.to_thread(self._fetch_new, last_uid)
        n = 0
        for uid, raw in raws:
            if await self._handle(raw):
                n += 1
        if last_uid is None or top > last_uid:
            await self.mem.kv_set(UID_KEY, top)
        return n

    async def _handle(self, raw):
        m = agents.parse_email(raw)
        text = f"{m['subject']} — {m['snippet']}" if m["snippet"] else m["subject"]
        level = agents.score(text, m["sender"], m["sender_addr"], self.allow, m["list_unsub"])
        if level == "skip":
            return False
        return await self.bot.ingest_external("email", m["sender"], text, m["ts"], level == "high",
                                              dedup_key=m["message_id"] or None)

    async def run_forever(self):
        log.info("ایجنت ایمیل فعال شد (هر %d دقیقه، فقط‌خواندنی)", self.cfg.email_poll_minutes)
        while True:
            try:
                await self.poll_once()
                self._auth_warned = False
            except imaplib.IMAP4.error as e:
                if not self._auth_warned:
                    self._auth_warned = True
                    await self.bot.notify_owner("⚠️ ورود به ایمیل ناموفق بود؛ App Password و فعال‌بودن IMAP رو چک کن. (" + re.sub(r"\s+", " ", str(e))[:60] + ")")
                log.warning("mail auth/imap error: %s", type(e).__name__)
            except Exception as e:
                log.warning("mail poll failed: %s", type(e).__name__)
            await asyncio.sleep(max(60, self.cfg.email_poll_minutes * 60))
