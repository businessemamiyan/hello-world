import asyncio
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import agents, scheduler
from app.agent_mail import MailAgent
from app.agent_tg import TelegramAgent, parse_allow, should_process
from app.bot import Bot
from app.config import Config
from app.memory import Memory


def raw_mail(subject, sender="Boss <boss@company.com>", body="سلام", mid="<1@x>", extra="", html=False):
    import email.header
    subj = email.header.Header(subject, "utf-8").encode()
    ctype = "text/html" if html else "text/plain"
    return (f"From: {sender}\r\nSubject: {subj}\r\nMessage-ID: {mid}\r\nDate: Sat, 10 Oct 2026 10:00:00 +0330\r\n{extra}"
            f"MIME-Version: 1.0\r\nContent-Type: {ctype}; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n{body}").encode("utf-8")


# ---------------------------------------------------------------- تجزیه و امتیاز
def test_parse_email_decodes_persian_subject_and_strips_html():
    m = agents.parse_email(raw_mail("فاکتور اکتبر", body="<html><style>x{}</style><p>مبلغ <b>۵۰۰</b> هزار تومان</p></html>", html=True))
    assert m["subject"] == "فاکتور اکتبر" and m["sender_addr"] == "boss@company.com" and m["sender"] == "Boss"
    assert m["snippet"] == "مبلغ ۵۰۰ هزار تومان" and "style" not in m["snippet"] and m["message_id"] == "<1@x>"
    long = agents.parse_email(raw_mail("x", body="الف " * 1000))
    assert len(long["snippet"]) <= agents.SNIPPET


def test_parse_email_survives_garbage():
    m = agents.parse_email(b"not an email at all \xff\xfe")
    assert m["subject"] == "(بدون موضوع)" and isinstance(m["ts"], float)


@pytest.mark.parametrize("text,sender,addr,allow,unsub,expected", [
    ("فاکتور پرداخت شد", "فروشگاه", "shop@x.com", (), False, "high"),
    ("سلام، حالت چطور است", "دوست", "d@x.com", (), False, "normal"),
    ("رمز یکبار مصرف شما 123456", "بانک", "b@x.ir", (), False, "skip"),           # OTP هرگز
    ("Your verification code is 482913. OTP", "svc", "n@x.com", (), False, "skip"),
    ("خبرنامه هفتگی ما", "نشریه", "news@x.com", (), True, "skip"),                  # تبلیغ/خبرنامه
    ("خبرنامه: سررسید فاکتور شما", "نشریه", "news@x.com", (), True, "normal"),      # خبرنامه ولی حاوی سررسید → فقط در خلاصه
    ("hello", "Boss", "boss@company.com", ("boss@company.com",), False, "high"),     # allowlist
    ("hello", "x", "someone@corp.ir", ("corp.ir",), False, "high"),                  # دامنه
])
def test_score_rules(text, sender, addr, allow, unsub, expected):
    assert agents.score(text, sender, addr, allow, unsub) == expected


# ---------------------------------------------------------------- ایجنت ایمیل با IMAP ساختگی
class FakeIMAP:
    """سرور IMAP ساختگی؛ ثبت می‌کند که فقط‌خواندنی باز شد و از PEEK استفاده شد."""
    mailbox = {}
    log = []

    def login(self, u, p):
        FakeIMAP.log.append(("login", u))
        if p == "bad":
            import imaplib
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", []

    def select(self, box, readonly=False):
        FakeIMAP.log.append(("select", box, readonly))
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        FakeIMAP.log.append((cmd,) + args)
        if cmd == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u in sorted(FakeIMAP.mailbox))]
        if cmd == "FETCH":
            uid = int(args[0])
            return "OK", [(b"%d (UID %d BODY[]<0> {n}" % (uid, uid), FakeIMAP.mailbox[uid]), b")"]
        raise AssertionError(cmd)

    def logout(self):
        FakeIMAP.log.append(("logout",))


class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, *a, **k):
        pass


class NoBrain:
    context_provider = None

    async def think(self, *a, **k):
        return "ok", []


def make(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    tg = FakeTG()
    cfg = Config(bot_token="x", setup_code="S", anthropic_api_key="k", email_imap_user="me@gmail.com", email_imap_password="app-pass",
                 email_allow="boss@company.com")
    bot = Bot(mem, tg, NoBrain(), cfg)
    return mem, tg, bot, cfg


@pytest.mark.asyncio
async def test_mail_agent_baseline_then_new_mail_priority_and_dedup(tmp_path):
    mem, tg, bot, cfg = make(tmp_path)
    await mem.set_owner(7)
    FakeIMAP.log = []
    FakeIMAP.mailbox = {1: raw_mail("قدیمی", mid="<old@x>"), 2: raw_mail("قدیمی۲", mid="<old2@x>")}
    agent = MailAgent(bot, mem, cfg, imap_factory=FakeIMAP)
    assert await agent.poll_once() == 0                                             # اولین بار: فقط خط پایه، سیل ایمیل قدیمی نه
    assert await mem.kv_get("mail_last_uid") == "2" and tg.sent == []
    assert ("select", "INBOX", True) in FakeIMAP.log                                # فقط‌خواندنی
    FakeIMAP.mailbox.update({
        3: raw_mail("فاکتور سررسید", sender="Shop <s@shop.com>", body="پرداخت تا فردا", mid="<3@x>"),
        4: raw_mail("سلام ساده", sender="Friend <f@x.com>", body="چطوری؟", mid="<4@x>"),
        5: raw_mail("رمز یکبار مصرف 998877", sender="Bank <b@bank.ir>", mid="<5@x>"),
        6: raw_mail("گزارش", sender="Boss <boss@company.com>", body="x", mid="<6@x>"),
    })
    assert await agent.poll_once() == 3                                             # فاکتور + ساده + رئیس؛ OTP رد
    assert any("فاکتور سررسید" in m for m in tg.sent) and any("Boss" in m for m in tg.sent)   # دو مورد مهم فوری
    assert not any("سلام ساده" in m for m in tg.sent)                                # معمولی منتظر خلاصه
    stored = await mem.recent_inbox(("email",), 20)
    assert len(stored) == 3 and not any("998877" in i["text"] for i in stored)       # رمز اصلاً ذخیره نشد
    fetches = [x for x in FakeIMAP.log if x[0] == "FETCH"]
    assert fetches and all("BODY.PEEK" in x[2] for x in fetches)                     # علامت خوانده‌شدن نمی‌خورد
    n_before = len(stored)
    FakeIMAP.mailbox[7] = raw_mail("تکراری", mid="<3@x>")                            # همان Message-ID
    assert await agent.poll_once() == 0 and len(await mem.recent_inbox(("email",), 20)) == n_before
    # خلاصهٔ دوره‌ای فقط موارد اعلام‌نشده را می‌فرستد و علامت می‌زند
    assert await bot.send_digest() is True and "سلام ساده" in tg.sent[-1] and "فاکتور" not in tg.sent[-1]
    assert await bot.send_digest() is False


@pytest.mark.asyncio
async def test_mail_check_and_auth_failure(tmp_path):
    mem, tg, bot, cfg = make(tmp_path)
    FakeIMAP.log, FakeIMAP.mailbox = [], {}
    ok, msg = await MailAgent(bot, mem, cfg, imap_factory=FakeIMAP).check()
    assert ok and "me@gmail.com" in msg
    cfg.email_imap_password = "bad"
    ok, msg = await MailAgent(bot, mem, cfg, imap_factory=FakeIMAP).check()
    assert not ok and "AUTHENTICATIONFAILED" in msg and "bad" not in msg            # رمز در پیام نمی‌آید
    await mem.set_owner(7)
    bot.mail_agent = MailAgent(bot, mem, cfg, imap_factory=FakeIMAP)
    await bot.handle_message({"chat": {"id": 7}, "text": "/mailtest"})
    assert tg.sent[-1].startswith("❌")


# ---------------------------------------------------------------- ایجنت تلگرام
def test_parse_allow_and_filters():
    assert parse_allow("123, -1001, @someone , team") == [123, -1001, "someone", "team"] and parse_allow("") == []
    assert should_process(5, False, "سلام") is True
    assert should_process(777000, False, "Login code: 12345") is False               # سرویس رسمی تلگرام
    assert should_process(5, True, "چت سکرت") is False
    assert should_process(5, False, "   ") is False
    assert should_process(5, False, "رمز یکبار مصرف شما 123456") is False


@pytest.mark.asyncio
async def test_telegram_agent_handles_messages_readonly(tmp_path):
    mem, tg, bot, cfg = make(tmp_path)
    await mem.set_owner(7)
    cfg.tg_allow = "-1001,@team"
    agent = TelegramAgent(bot, cfg)
    assert agent.allow == [-1001, "team"]
    ts = time.time()
    assert await agent.handle_message(-1001, "گروه کار", 55, "جلسه فردا ساعت ۱۰ مهلت گزارش", ts, 9) is True        # مهم → فوری
    assert "گروه کار" in tg.sent[-1] and "(مهم)" in tg.sent[-1]
    assert await agent.handle_message(-1001, "گروه کار", 55, "جلسه فردا ساعت ۱۰ مهلت گزارش", ts, 9) is False       # همان پیام → تکراری
    assert await agent.handle_message(-1001, "گروه کار", 55, "ظهر چی بخوریم؟", ts, 10) is True
    n = len(tg.sent)
    assert len(tg.sent) == n and (await mem.recent_inbox(("telegram",), 10))[0]["text"] == "ظهر چی بخوریم؟"        # معمولی ساکت
    assert await agent.handle_message(-1001, "x", 777000, "Login code 55555", ts, 11) is False
    assert await bot.send_digest() is True and "ظهر چی بخوریم" in tg.sent[-1]


@pytest.mark.asyncio
async def test_telegram_agent_refuses_to_run_without_allowlist(tmp_path):
    mem, tg, bot, cfg = make(tmp_path)
    cfg.tg_allow = ""
    created = []
    agent = TelegramAgent(bot, cfg, client_factory=lambda: created.append(1))
    await agent.run_forever()                                                          # بدون allowlist هیچ کلاینتی ساخته نمی‌شود
    assert created == []


# ---------------------------------------------------------------- زمان‌بند خلاصه
@pytest.mark.asyncio
async def test_scheduler_sends_digest_once_per_configured_time(tmp_path, monkeypatch):
    mem, tg, bot, cfg = make(tmp_path)
    await mem.set_owner(7)
    cfg.digest_times = "13:00, 20:30"
    await bot.ingest_external("email", "X", "پیام عادی", time.time(), False, dedup_key="a")
    sched = scheduler.Scheduler(bot, mem, cfg)
    await sched.maybe_digest("12:59", "2026-10-10")
    assert tg.sent == []
    await sched.maybe_digest("13:00", "2026-10-10")
    assert len(tg.sent) == 1 and "پیام عادی" in tg.sent[0]
    await bot.ingest_external("email", "Y", "پیام دوم", time.time(), False, dedup_key="b")
    await sched.maybe_digest("13:00", "2026-10-10")                                    # همان دقیقه دوباره: نه
    assert len(tg.sent) == 1
    await sched.maybe_digest("20:30", "2026-10-10")
    assert len(tg.sent) == 2 and "پیام دوم" in tg.sent[1]
