"""حافظه مهرداد — SQLite.

دو جدول:
- messages: کل تاریخچه مکالمه (برای زمینه‌ی مکالمه‌ای کوتاه‌مدت)
- memory: واقعیت‌های استخراج‌شده و دسته‌بندی‌شده (برای حافظه‌ی بلندمدت/جست‌وجو)
کاملاً مجزا از دیتابیس قطب‌نما — پروژه‌ی دیگری است.
"""
import asyncio
import os
import sqlite3
import time


class Memory:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS owner(id INTEGER PRIMARY KEY CHECK(id=1), chat_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                summary TEXT NOT NULL,
                detail TEXT,
                amount REAL,
                ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(type);
            CREATE INDEX IF NOT EXISTS idx_memory_ts ON memory(ts);
            """
        )
        self.db.commit()
        self.lock = asyncio.Lock()

    # ---------- owner ----------
    async def set_owner(self, chat_id):
        async with self.lock:
            self.db.execute(
                "INSERT INTO owner(id, chat_id) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET chat_id=excluded.chat_id",
                (chat_id,),
            )
            self.db.commit()

    async def get_owner(self):
        async with self.lock:
            row = self.db.execute("SELECT chat_id FROM owner WHERE id=1").fetchone()
            return row[0] if row else None

    # ---------- messages (کوتاه‌مدت) ----------
    async def add_message(self, role, text):
        async with self.lock:
            self.db.execute("INSERT INTO messages(role, text, ts) VALUES(?,?,?)", (role, text, time.time()))
            self.db.commit()

    async def recent_messages(self, limit=20):
        async with self.lock:
            rows = self.db.execute(
                "SELECT role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return list(reversed(rows))

    # ---------- memory (بلندمدت) ----------
    async def add_memory(self, entries):
        """entries: لیستی از dict با کلیدهای type/summary/detail/amount."""
        if not entries:
            return
        async with self.lock:
            now = time.time()
            self.db.executemany(
                "INSERT INTO memory(type, summary, detail, amount, ts) VALUES(?,?,?,?,?)",
                [
                    (e.get("type", "note"), e.get("summary", ""), e.get("detail"), e.get("amount"), now)
                    for e in entries
                ],
            )
            self.db.commit()

    async def recent_memory(self, limit=40):
        async with self.lock:
            rows = self.db.execute(
                "SELECT type, summary, detail, amount, ts FROM memory ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                {"type": r[0], "summary": r[1], "detail": r[2], "amount": r[3], "ts": r[4]}
                for r in reversed(rows)
            ]

    async def memory_by_type(self, type_, limit=100):
        async with self.lock:
            rows = self.db.execute(
                "SELECT summary, detail, amount, ts FROM memory WHERE type=? ORDER BY id DESC LIMIT ?",
                (type_, limit),
            ).fetchall()
            return [{"summary": r[0], "detail": r[1], "amount": r[2], "ts": r[3]} for r in rows]
