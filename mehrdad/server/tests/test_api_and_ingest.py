import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.ingest import is_sensitive, parse_bank_text
from app.memory import Memory
from app.web import create_app


# ---------- پارسر پیامک بانک (نمونه‌های ساختگی؛ با پیامک‌های واقعی کاربر دقیق‌تر می‌شود) ----------
@pytest.mark.parametrize("text,kind,amount,balance", [
    ("بانک ملی\nبرداشت: 500,000\nمانده: 2,300,000\n1405/07/18-10:30", "expense", 50000, 230000),
    ("برداشت:۵۰۰,۰۰۰\nمانده:۲,۳۰۰,۰۰۰\n۱۴۰۵/۰۷/۱۸ - ۱۰:۳۰", "expense", 50000, 230000),
    ("مبلغ 1,000,000 ریال به حساب شما واریز شد. مانده: 5,000,000", "income", 100000, 500000),
    ("مبلغ 250,000 ریال از حساب شما برداشت شد.", "expense", 25000, None),
    ("کارت 6037****1234\nخرید\n250,000-\nموجودی: 3,000,000", "expense", 25000, 300000),
    ("+1,500,000\nواریز حقوق\nمانده 9,000,000", "income", 150000, 900000),
    ("خرید 80,000 تومان از کافه", "expense", 80000, None),
])
def test_parse_bank_text(text, kind, amount, balance):
    p = parse_bank_text(text)
    assert p and p["type"] == kind and p["amount"] == amount and p["balance"] == balance


@pytest.mark.parametrize("text", [
    "سلام، فردا جلسه داریم ساعت 10:30",
    "مانده: 2,300,000",                      # فقط مانده، تراکنش نیست
    "کارت 6037****1234 فعال شد",
    "",
])
def test_parse_bank_text_rejects_non_transactions(text):
    assert parse_bank_text(text) is None


@pytest.mark.parametrize("text", [
    "رمز یکبار مصرف شما: 123456",
    "کد تایید ورود: 482913. به کسی نگویید",
    "رمز پویا 998877 برای خرید 500,000 ریال",
    "Your OTP is 123456",
    "CVV2: 123",
])
def test_otp_is_sensitive_and_never_parsed(text):
    assert is_sensitive(text)
    assert parse_bank_text(text) is None


# ---------- API ----------
class FakeSvc:
    def __init__(self):
        self.notified = []
        self.chats = []

    async def chat(self, text):
        self.chats.append(text)
        return "جواب: " + text

    async def notify_owner(self, text):
        self.notified.append(text)


@pytest.fixture
def api(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    svc = FakeSvc()
    client = TestClient(create_app(mem, time.time(), svc))
    return mem, svc, client


def _pair(client, mem):
    import asyncio
    code = asyncio.new_event_loop().run_until_complete(mem.create_pair_code())
    r = client.post("/api/pair", json={"code": code, "name": "تست"})
    assert r.status_code == 200
    return r.json()["token"], code


def test_docs_are_disabled(api):
    _, _, client = api
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/health").status_code == 200


def test_endpoints_require_token(api):
    _, _, client = api
    for method, path in (("get", "/api/me"), ("get", "/api/history"), ("post", "/api/chat"), ("post", "/api/ingest")):
        assert getattr(client, method)(path).status_code in (401, 422)
    assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_pair_is_single_use_and_notifies_owner(api):
    mem, svc, client = api
    token, code = _pair(client, mem)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()["ok"] is True
    again = client.post("/api/pair", json={"code": code, "name": "x"})
    assert again.status_code == 403                      # کد دوباره قابل‌استفاده نیست
    assert any("وصل شد" in n for n in svc.notified)


def test_pair_rate_limit(api):
    _, _, client = api
    codes = [client.post("/api/pair", json={"code": f"BAD{i}", "name": "x"}).status_code for i in range(7)]
    assert codes[:5] == [403] * 5 and codes[5:] == [429, 429]


def test_chat_and_history(api):
    mem, svc, client = api
    token, _ = _pair(client, mem)
    h = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/chat", json={"text": "سلام"}, headers=h).json()["reply"] == "جواب: سلام"
    assert client.post("/api/chat", json={"text": ""}, headers=h).status_code == 422
    assert svc.chats == ["سلام"]


def test_ingest_parses_dedups_and_skips_otp(api):
    mem, svc, client = api
    token, _ = _pair(client, mem)
    h = {"Authorization": f"Bearer {token}"}
    now = time.time()
    items = [
        {"kind": "sms", "source": "BankMelli", "text": "برداشت: 500,000\nمانده: 2,300,000", "ts": now},
        {"kind": "sms", "source": "BankMelli", "text": "رمز یکبار مصرف شما: 123456", "ts": now},
        {"kind": "notification", "source": "bank.app", "text": "سلام دنیا", "ts": now},
    ]
    r = client.post("/api/ingest", json={"items": items}, headers=h).json()
    assert r == {"stored": 2, "duplicate": 0, "skipped": 1, "parsed": 1}
    r2 = client.post("/api/ingest", json={"items": items}, headers=h).json()   # تلاش دوبارهٔ اپ
    assert r2 == {"stored": 0, "duplicate": 2, "skipped": 1, "parsed": 0}
    import asyncio
    mems = asyncio.new_event_loop().run_until_complete(mem.recent_memory(10))
    assert len(mems) == 1 and mems[0]["type"] == "expense" and mems[0]["amount"] == 50000
    assert any("ثبت شد" in n for n in svc.notified)


def test_ingest_validates_input(api):
    mem, _, client = api
    token, _ = _pair(client, mem)
    h = {"Authorization": f"Bearer {token}"}
    bad_kind = {"items": [{"kind": "email", "source": "", "text": "x", "ts": 1}]}
    assert client.post("/api/ingest", json=bad_kind, headers=h).status_code == 422
    too_many = {"items": [{"kind": "sms", "source": "", "text": "x", "ts": i} for i in range(51)]}
    assert client.post("/api/ingest", json=too_many, headers=h).status_code == 422


def test_token_is_stored_hashed(api, tmp_path):
    import sqlite3
    mem, _, client = api
    token, _ = _pair(client, mem)
    raw = sqlite3.connect(str(tmp_path / "t.db")).execute("SELECT token_hash FROM devices").fetchone()[0]
    assert token not in raw and len(raw) == 64
