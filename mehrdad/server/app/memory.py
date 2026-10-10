"""حافظه مهرداد — SQLite.

چهار جدول:
- messages: کل تاریخچه مکالمه (برای زمینه‌ی مکالمه‌ای کوتاه‌مدت)
- memory: واقعیت‌های استخراج‌شده و دسته‌بندی‌شده (برای حافظه‌ی بلندمدت/جست‌وجو)
- habits: عادت‌هایی که کاربر می‌سازد (با/بدون جایگزینی یک عادت بد)، با استریک
- habit_log: تاریخچه چک‌این روزانه‌ی هر عادت
کاملاً مجزا از دیتابیس قطب‌نما — پروژه‌ی دیگری است.
"""
import asyncio
import datetime
import os
import sqlite3
import time


def today_str():
    return datetime.date.today().isoformat()


def day_before(date_str):
    """روز قبل از date_str (ISO) — نه «دیروز نسبت به الان»، بلکه نسبت به خود تاریخ، تا
    چک‌این تاریخ‌دار (نه فقط امروز) هم استریک را درست حساب کند."""
    d = datetime.date.fromisoformat(date_str)
    return (d - datetime.timedelta(days=1)).isoformat()


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
            CREATE TABLE IF NOT EXISTS habits(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                good TEXT NOT NULL,
                bad TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                streak INTEGER NOT NULL DEFAULT 0,
                best_streak INTEGER NOT NULL DEFAULT 0,
                last_checkin TEXT,
                created_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS habit_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                done INTEGER NOT NULL,
                note TEXT,
                ts REAL NOT NULL
            );
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

    # ---------- habits ----------
    async def add_habit(self, good, bad=None):
        async with self.lock:
            cur = self.db.execute(
                "INSERT INTO habits(good, bad, status, streak, best_streak, last_checkin, created_ts) "
                "VALUES(?,?,'active',0,0,NULL,?)",
                (good, bad, time.time()),
            )
            self.db.commit()
            return cur.lastrowid

    async def list_habits(self, status="active"):
        async with self.lock:
            rows = self.db.execute(
                "SELECT id, good, bad, status, streak, best_streak, last_checkin FROM habits "
                "WHERE status=? ORDER BY id", (status,)
            ).fetchall()
            return [
                {"id": r[0], "good": r[1], "bad": r[2], "status": r[3], "streak": r[4],
                 "best_streak": r[5], "last_checkin": r[6]}
                for r in rows
            ]

    async def get_habit(self, habit_id):
        async with self.lock:
            r = self.db.execute(
                "SELECT id, good, bad, status, streak, best_streak, last_checkin FROM habits WHERE id=?",
                (habit_id,),
            ).fetchone()
            if not r:
                return None
            return {"id": r[0], "good": r[1], "bad": r[2], "status": r[3], "streak": r[4],
                    "best_streak": r[5], "last_checkin": r[6]}

    async def set_habit_status(self, habit_id, status):
        async with self.lock:
            self.db.execute("UPDATE habits SET status=? WHERE id=?", (status, habit_id))
            self.db.commit()

    async def checkin_habit(self, habit_id, done, date=None, note=None):
        """ثبت چک‌این امروز (یا تاریخ دلخواه) و به‌روزرسانی استریک.
        اگر همان تاریخ قبلاً ثبت شده باشد، رکورد قبلی override می‌شود (نه تکراری)."""
        date = date or today_str()
        async with self.lock:
            row = self.db.execute("SELECT good, bad, status, streak, best_streak, last_checkin FROM habits WHERE id=?", (habit_id,)).fetchone()
            if not row:
                return None
            _good, _bad, _status, streak, best_streak, last_checkin = row

            already = self.db.execute(
                "SELECT id FROM habit_log WHERE habit_id=? AND date=?", (habit_id, date)
            ).fetchone()
            if already:
                self.db.execute(
                    "UPDATE habit_log SET done=?, note=?, ts=? WHERE id=?",
                    (1 if done else 0, note, time.time(), already[0]),
                )
            else:
                self.db.execute(
                    "INSERT INTO habit_log(habit_id, date, done, note, ts) VALUES(?,?,?,?,?)",
                    (habit_id, date, 1 if done else 0, note, time.time()),
                )

            if done:
                streak = streak + 1 if last_checkin == day_before(date) else 1
            else:
                streak = 0
            best_streak = max(best_streak, streak)
            self.db.execute(
                "UPDATE habits SET streak=?, best_streak=?, last_checkin=? WHERE id=?",
                (streak, best_streak, date, habit_id),
            )
            self.db.commit()
            return {"streak": streak, "best_streak": best_streak}

    async def habits_pending_today(self):
        """عادت‌های فعالی که امروز هنوز چک‌این نشده‌اند (برای یادآوری شبانه)."""
        today = today_str()
        async with self.lock:
            rows = self.db.execute(
                "SELECT id, good, bad, streak FROM habits WHERE status='active' AND (last_checkin IS NULL OR last_checkin != ?)",
                (today,),
            ).fetchall()
            return [{"id": r[0], "good": r[1], "bad": r[2], "streak": r[3]} for r in rows]
