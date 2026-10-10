import asyncio
import contextlib
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import life, novatunnel

NOW = datetime.datetime(2026, 10, 10, 14, 0, tzinfo=life.TEHRAN)


class FakeConn:
    """جایگزین اتصال asyncpg؛ بر اساس متن SQL جواب می‌دهد و ثبت می‌کند که فقط SELECT زده شده."""
    def __init__(self):
        self.sql = []
        self.closed = False
        self.readonly = None

    @contextlib.asynccontextmanager
    async def transaction(self, readonly=False):
        self.readonly = readonly
        yield

    async def fetchrow(self, sql, *args):
        self.sql.append(sql)
        if "mehrad.sales" in sql and "confirmed" in sql:
            return {"total": 450000.0, "n": 3} if args[0].day == 10 or True else None
        if "mehrad.expenses" in sql:
            return {"total": 50000.0, "n": 1}
        if "mehrad.sales" in sql and "pending" in sql:
            return {"n": 2, "total": 120000.0}
        if "mehrad.topups" in sql:
            return {"n": 1, "total": 200000.0}
        if "mehrad.user_counts" in sql:
            return {"total_users": 321, "new_24h": 4, "new_30d": 57}
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        return [{"d": datetime.date(2026, 10, 9), "total": 300000.0, "n": 2}]

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_snapshot_reads_only_the_mehrad_schema_in_a_readonly_transaction():
    conn = FakeConn()

    async def connect(dsn):
        return conn

    d = await novatunnel.snapshot("postgresql://x", NOW, connect=connect, use_cache=False)
    assert d["revenue"]["today"] == 450000 and d["revenue"]["month_count"] == 3
    assert d["net_month"] == 400000 and d["pending_sales"]["count"] == 2 and d["users"]["new_30d"] == 57
    assert d["last7"][0]["total"] == 300000
    assert conn.readonly is True and conn.closed is True
    assert all(s.lstrip().lower().startswith("select") for s in conn.sql)          # هیچ نوشتنی
    assert all("public." not in s for s in conn.sql)                                # فقط view‌های schema مهراد
    txt = novatunnel.format_text(d)
    assert "۴۵۰,۰۰۰" in txt and "NovaTunnel" in txt and "۳۲۱" in txt


@pytest.mark.asyncio
async def test_not_configured_and_failures_are_graceful():
    assert await novatunnel.snapshot("") == {"configured": False}
    assert "تنظیم نشده" in novatunnel.format_text({"configured": False})

    async def boom(dsn):
        raise ConnectionRefusedError("db down")

    d = await novatunnel.snapshot("postgresql://x", NOW, connect=boom, use_cache=False)
    assert d["configured"] is True and "ConnectionRefusedError" in d["error"]
    assert "در دسترس نیست" in novatunnel.format_text(d)
    assert "password" not in d["error"].lower()


@pytest.mark.asyncio
async def test_results_are_cached_briefly():
    conn = FakeConn()
    calls = []

    async def connect(dsn):
        calls.append(1)
        return conn

    novatunnel._CACHE.update(ts=0.0, dsn=None, data=None)
    await novatunnel.snapshot("postgresql://cache-test", NOW, connect=connect)
    await novatunnel.snapshot("postgresql://cache-test", NOW, connect=connect)
    assert len(calls) == 1
    novatunnel._CACHE.update(ts=0.0, dsn=None, data=None)


def test_sql_file_exposes_no_personal_columns_and_uses_closed_schema():
    sql = open(os.path.join(os.path.dirname(__file__), "..", "novatunnel-readonly.sql"), encoding="utf-8").read().lower()
    code = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "create schema if not exists mehrad" in code and "revoke all on schema mehrad from public, anon, authenticated" in code
    for personal in ("phone_number", "telegram_id", "telegram_username", "full_name"):
        assert personal not in code
    assert "grant select" in code and "insert" not in code and "update" not in code and "delete" not in code
