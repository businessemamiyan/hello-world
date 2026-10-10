import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import scheduler
from app.bot import Bot
from app.config import Config
from app.memory import Memory


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
    mem = Memory(str(tmp_path / "live.db"))
    tg = FakeTG()
    cfg = Config(bot_token="x", setup_code="S", anthropic_api_key="k", data_dir=str(tmp_path))
    return mem, tg, Bot(mem, tg, NoBrain(), cfg), cfg


@pytest.mark.asyncio
async def test_backup_is_consistent_even_while_data_lives_in_the_wal(tmp_path):
    mem, tg, bot, cfg = make(tmp_path)
    await mem.add_memory([{"type": "note", "summary": f"یادداشت {i}"} for i in range(30)])
    await mem.add_message("user", "سلام")
    live_main = tmp_path / "live.db"
    # نشان بدهیم که کپی ساده‌ی فایل اصلی همین مشکل را دارد: داده‌ها هنوز در -wal‌اند
    assert os.path.exists(str(live_main) + "-wal") and os.path.getsize(str(live_main) + "-wal") > os.path.getsize(live_main)
    dest = await bot.do_backup()
    chk = sqlite3.connect(dest)
    assert chk.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert chk.execute("select count(*) from memory").fetchone()[0] == 30 and chk.execute("select count(*) from messages").fetchone()[0] == 1
    assert chk.execute("select count(*) from sqlite_master where name='memory_fts'").fetchone()[0] == 1
    chk.close()
    assert (os.stat(dest).st_mode & 0o077) == 0 or os.name == "nt"           # فقط خودِ مالک (در لینوکس)


@pytest.mark.asyncio
async def test_prune_keeps_last_14_automatic_backups_only(tmp_path):
    mem, tg, bot, cfg = make(tmp_path)
    d = tmp_path / "backups"
    d.mkdir()
    for day in range(1, 21):
        (d / f"mehrdad-202609{day:02d}.db").write_bytes(b"x")
    (d / "mehrdad-manual-20261010-144743.db").write_bytes(b"manual")           # دستی: هرگز پاک نشود
    await bot.do_backup()
    autos = sorted(p.name for p in d.iterdir() if p.name.startswith("mehrdad-") and "manual" not in p.name)
    assert len(autos) == 14 and (d / "mehrdad-manual-20261010-144743.db").exists()
    assert "mehrdad-20260901.db" not in autos                                   # قدیمی‌ترین‌ها رفتند


@pytest.mark.asyncio
async def test_scheduler_runs_backup_once_a_day_and_command(tmp_path):
    mem, tg, bot, cfg = make(tmp_path)
    await mem.set_owner(7)
    sched = scheduler.Scheduler(bot, mem, cfg)
    await sched.maybe_backup("03:29", "2026-10-11")
    assert not (tmp_path / "backups").exists()
    await sched.maybe_backup("03:30", "2026-10-11")
    assert len(list((tmp_path / "backups").iterdir())) == 1
    before = os.path.getmtime(next((tmp_path / "backups").iterdir()))
    await sched.maybe_backup("03:30", "2026-10-11")                              # همان روز دوباره: نه
    assert os.path.getmtime(next((tmp_path / "backups").iterdir())) == before
    await bot.handle_message({"chat": {"id": 7}, "text": "/backup"})
    assert "پشتیبان ساخته شد" in tg.sent[-1]
