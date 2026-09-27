"""ذخیره‌سازی SQLite — یک سند state (همان قالب نسخه ۲ اپ) با نسخه‌بندی خوش‌بینانه.

اپ و ربات هر دو state را تغییر می‌دهند. هر نوشتن نسخه را یکی بالا می‌برد؛
اگر اپ با نسخه قدیمی بنویسد، Conflict برمی‌گردد تا چیزی بی‌صدا رونویسی نشود.
"""
import asyncio
import json
import os
import sqlite3
import time


class Conflict(Exception):
    def __init__(self, version, state):
        super().__init__("version conflict")
        self.version = version
        self.state = state


def empty_root():
    return {"v": 2, "mode": "real", "setupDone": False, "real": {}}


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, json TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS smslog(hash TEXT PRIMARY KEY, received REAL NOT NULL, sender TEXT, text TEXT, parsed INTEGER NOT NULL);
            """
        )
        self.db.commit()
        self.lock = asyncio.Lock()

    # ---------- state ----------
    def get(self):
        row = self.db.execute("SELECT version, json FROM state WHERE id=1").fetchone()
        if not row:
            return 0, empty_root()
        return row[0], json.loads(row[1])

    def _write(self, version, state):
        self.db.execute(
            "INSERT INTO state(id,version,json,updated) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET version=excluded.version, json=excluded.json, updated=excluded.updated",
            (version, json.dumps(state, ensure_ascii=False, separators=(",", ":")), time.time()),
        )
        self.db.commit()

    async def put(self, state, expect_version):
        """نوشتن از طرف اپ؛ فقط اگر نسخه‌ای که اپ دیده هنوز آخرین نسخه باشد."""
        async with self.lock:
            v, cur = self.get()
            if expect_version != v:
                raise Conflict(v, cur)
            self._write(v + 1, state)
            return v + 1

    async def mutate(self, fn):
        """تغییر از طرف ربات: fn(state) را روی آخرین نسخه اجرا می‌کند و ذخیره می‌کند."""
        async with self.lock:
            v, st = self.get()
            result = fn(st)
            self._write(v + 1, st)
            return result

    # ---------- kv ----------
    def kget(self, k, default=None):
        row = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def kset(self, k, v):
        self.db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v, ensure_ascii=False)))
        self.db.commit()

    def kdel(self, k):
        self.db.execute("DELETE FROM kv WHERE k=?", (k,))
        self.db.commit()

    # ---------- sms ----------
    def sms_seen(self, h):
        return self.db.execute("SELECT 1 FROM smslog WHERE hash=?", (h,)).fetchone() is not None

    def sms_log(self, h, sender, text, parsed):
        self.db.execute("INSERT OR IGNORE INTO smslog(hash,received,sender,text,parsed) VALUES(?,?,?,?,?)", (h, time.time(), sender, text, 1 if parsed else 0))
        self.db.commit()
