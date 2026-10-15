"""اعلان‌های اپ (مثلاً «درس تازه داری»): سرور در صف می‌گذارد، سرویس پس‌زمینهٔ گوشی با همان long-poll گوشی می‌گیرد و اعلان محلی نشان می‌دهد.

اپ اندروید پوش گوگل ندارد؛ پس اعلان فقط وقتی می‌رسد که سرویس «کنترل گوشی» (یا کارگر ۱۵‌دقیقه‌ای) زنده باشد. تلگرام همیشه مسیر مطمئن است.
"""
import time

MAX_AGE = 12 * 3600          # اعلان کهنه‌تر از ۱۲ ساعت دیگر نشان داده نمی‌شود

SCHEMA = """
CREATE TABLE IF NOT EXISTS notices(
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, text TEXT, target TEXT, ts REAL NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_notices ON notices(delivered, ts);
"""


class Notices:
    def __init__(self, mem):
        self.mem = mem
        self.db = mem.db
        self.db.executescript(SCHEMA)
        self.db.commit()

    async def add(self, title, text="", target=""):
        async with self.mem.lock:
            cur = self.db.execute("INSERT INTO notices(title, text, target, ts) VALUES(?,?,?,?)", ((title or "")[:120], (text or "")[:300], (target or "")[:60], time.time()))
            self.db.commit()
            return cur.lastrowid

    async def claim(self):
        """قدیمی‌ترین اعلان تحویل‌نشده (و تازه) را برمی‌دارد و تحویل‌شده علامت می‌زند؛ None اگر نیست."""
        async with self.mem.lock:
            self.db.execute("UPDATE notices SET delivered=2 WHERE delivered=0 AND ts<?", (time.time() - MAX_AGE,))
            r = self.db.execute("SELECT id, title, text, target FROM notices WHERE delivered=0 ORDER BY id LIMIT 1").fetchone()
            if r:
                self.db.execute("UPDATE notices SET delivered=1 WHERE id=?", (r[0],))
            self.db.commit()
        return {"id": r[0], "title": r[1], "text": r[2] or "", "target": r[3] or ""} if r else None

    async def waiting(self):
        async with self.mem.lock:
            return self.db.execute("SELECT COUNT(*) FROM notices WHERE delivered=0 AND ts>=?", (time.time() - MAX_AGE,)).fetchone()[0]
