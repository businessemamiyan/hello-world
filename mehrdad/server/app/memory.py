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
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_NORMALIZE = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "ؤ": "و", "‌": " ", "ـ": ""})
_DIACRITICS = re.compile("[ً-ٰٟ]")
_TOKEN = re.compile(r"\w+", re.UNICODE)


def normalize_fa(text):
    """یکسان‌سازی متن فارسی برای جست‌وجو: ي/ك عربی، نیم‌فاصله، اعراب، ارقام فارسی/عربی."""
    if not text:
        return ""
    t = _DIACRITICS.sub("", str(text).translate(_FA_DIGITS).translate(_NORMALIZE))
    return t.lower()


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


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
            CREATE TABLE IF NOT EXISTS devices(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_ts REAL NOT NULL,
                last_seen_ts REAL
            );
            CREATE TABLE IF NOT EXISTS pair_codes(
                code_hash TEXT PRIMARY KEY,
                expires_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inbox(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                source TEXT,
                text TEXT NOT NULL,
                ts REAL NOT NULL,
                dedup TEXT NOT NULL UNIQUE,
                parsed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS accounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'bank',
                balance REAL NOT NULL DEFAULT 0,
                note TEXT,
                created_ts REAL NOT NULL,
                updated_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                balance REAL NOT NULL,
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS debts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'installment',
                creditor TEXT,
                total REAL NOT NULL DEFAULT 0,
                remaining REAL NOT NULL DEFAULT 0,
                installment_amount REAL NOT NULL DEFAULT 0,
                installments_total INTEGER,
                installments_paid INTEGER NOT NULL DEFAULT 0,
                due_day INTEGER,
                next_due TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                note TEXT,
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
        self._migrate_memory_columns()
        self.fts = self._init_fts()
        self.db.commit()
        self.lock = asyncio.Lock()

    def _migrate_memory_columns(self):
        """ستون‌های رویداد زندگی: زمان واقعی رویداد، دسته، و فیلدهای ساختاری (JSON)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(memory)").fetchall()}
        for name, ddl in (("event_ts", "REAL"), ("category", "TEXT"), ("fields", "TEXT")):
            if name not in cols:
                self.db.execute(f"ALTER TABLE memory ADD COLUMN {name} {ddl}")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_memory_event_ts ON memory(event_ts)")

    def _init_fts(self):
        """جدول جست‌وجوی متنی (FTS5) روی حافظهٔ بلندمدت؛ اگر SQLite بدون FTS5 باشد، به LIKE برمی‌گردیم.
        متن نرمال‌شده ذخیره می‌شود؛ ردیف‌های قدیمی که هنوز ایندکس نشده‌اند یک‌بار پر می‌شوند."""
        try:
            self.db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
                "summary, detail, memory_id UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
            )
            missing = self.db.execute(
                "SELECT id, summary, detail FROM memory WHERE id NOT IN (SELECT memory_id FROM memory_fts)"
            ).fetchall()
            self.db.executemany(
                "INSERT INTO memory_fts(summary, detail, memory_id) VALUES(?,?,?)",
                [(normalize_fa(s), normalize_fa(d), i) for i, s, d in missing],
            )
            return True
        except sqlite3.OperationalError:
            return False

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

    async def recent_messages_ts(self, limit=50):
        """برای همگام‌سازی چت اپ: [{role, text, ts}] از قدیم به جدید."""
        async with self.lock:
            rows = self.db.execute(
                "SELECT role, text, ts FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [{"role": r[0], "text": r[1], "ts": r[2]} for r in reversed(rows)]

    # ---------- دستگاه‌ها و جفت‌سازی (اپ اندروید) ----------
    async def create_pair_code(self, ttl=600):
        """کد یک‌بارمصرف ۸ حرفی؛ فقط هش ذخیره می‌شود."""
        code = secrets.token_hex(4).upper()
        async with self.lock:
            self.db.execute("DELETE FROM pair_codes WHERE expires_ts < ?", (time.time(),))
            self.db.execute("INSERT INTO pair_codes(code_hash, expires_ts) VALUES(?,?)", (_sha(code), time.time() + ttl))
            self.db.commit()
        return code

    async def consume_pair_code(self, code):
        h = _sha((code or "").strip().upper())
        async with self.lock:
            row = self.db.execute("SELECT expires_ts FROM pair_codes WHERE code_hash=?", (h,)).fetchone()
            if not row:
                return False
            self.db.execute("DELETE FROM pair_codes WHERE code_hash=?", (h,))
            self.db.commit()
            return row[0] >= time.time()

    async def add_device(self, name):
        token = secrets.token_urlsafe(32)
        async with self.lock:
            cur = self.db.execute(
                "INSERT INTO devices(name, token_hash, created_ts) VALUES(?,?,?)",
                ((name or "گوشی")[:60], _sha(token), time.time()),
            )
            self.db.commit()
            return cur.lastrowid, token

    async def device_for_token(self, token):
        if not token:
            return None
        async with self.lock:
            row = self.db.execute(
                "SELECT id, name FROM devices WHERE token_hash=?", (_sha(token),)
            ).fetchone()
            if not row:
                return None
            self.db.execute("UPDATE devices SET last_seen_ts=? WHERE id=?", (time.time(), row[0]))
            self.db.commit()
            return {"id": row[0], "name": row[1]}

    async def list_devices(self):
        async with self.lock:
            rows = self.db.execute("SELECT id, name, created_ts, last_seen_ts FROM devices ORDER BY id").fetchall()
            return [{"id": r[0], "name": r[1], "created_ts": r[2], "last_seen_ts": r[3]} for r in rows]

    async def remove_device(self, device_id):
        async with self.lock:
            cur = self.db.execute("DELETE FROM devices WHERE id=?", (device_id,))
            self.db.commit()
            return cur.rowcount > 0

    # ---------- حساب‌های بانکی/نقدی ----------
    _ACC_COLS = "id, name, kind, balance, note, updated_ts"

    @staticmethod
    def _acc(r):
        return {"id": r[0], "name": r[1], "kind": r[2], "balance": r[3], "note": r[4], "updated_ts": r[5]}

    async def list_accounts(self):
        async with self.lock:
            return [self._acc(r) for r in self.db.execute(f"SELECT {self._ACC_COLS} FROM accounts ORDER BY id").fetchall()]

    async def add_account(self, name, kind="bank", balance=0.0, note=None):
        now = time.time()
        async with self.lock:
            cur = self.db.execute("INSERT INTO accounts(name, kind, balance, note, created_ts, updated_ts) VALUES(?,?,?,?,?,?)",
                                  (name, kind, balance, note, now, now))
            self.db.execute("INSERT INTO account_log(account_id, balance, ts) VALUES(?,?,?)", (cur.lastrowid, balance, now))
            self.db.commit()
            return cur.lastrowid

    async def update_account(self, account_id, patch):
        async with self.lock:
            r = self.db.execute(f"SELECT {self._ACC_COLS} FROM accounts WHERE id=?", (account_id,)).fetchone()
            if not r:
                return None
            cur = self._acc(r)
            new = {k: (patch[k] if k in patch and patch[k] is not None else cur[k]) for k in ("name", "kind", "balance", "note")}
            if "note" in patch:
                new["note"] = patch["note"]
            now = time.time()
            self.db.execute("UPDATE accounts SET name=?, kind=?, balance=?, note=?, updated_ts=? WHERE id=?",
                            (new["name"], new["kind"], new["balance"], new["note"], now, account_id))
            if new["balance"] != cur["balance"]:
                self.db.execute("INSERT INTO account_log(account_id, balance, ts) VALUES(?,?,?)", (account_id, new["balance"], now))
            self.db.commit()
            r = self.db.execute(f"SELECT {self._ACC_COLS} FROM accounts WHERE id=?", (account_id,)).fetchone()
            return self._acc(r)

    async def delete_account(self, account_id):
        async with self.lock:
            cur = self.db.execute("DELETE FROM accounts WHERE id=?", (account_id,))
            self.db.execute("DELETE FROM account_log WHERE account_id=?", (account_id,))
            self.db.commit()
            return cur.rowcount > 0

    async def account_history(self, account_id, limit=60):
        async with self.lock:
            rows = self.db.execute("SELECT balance, ts FROM account_log WHERE account_id=? ORDER BY id DESC LIMIT ?",
                                   (account_id, limit)).fetchall()
        return [{"balance": r[0], "ts": r[1]} for r in reversed(rows)]

    # ---------- بدهی و اقساط ----------
    _DEBT_COLS = ("id, title, kind, creditor, total, remaining, installment_amount, installments_total, "
                  "installments_paid, due_day, next_due, status, note")

    @staticmethod
    def _debt(r):
        keys = ("id", "title", "kind", "creditor", "total", "remaining", "installment_amount", "installments_total",
                "installments_paid", "due_day", "next_due", "status", "note")
        return dict(zip(keys, r))

    async def list_debts(self, include_paid=True):
        q = f"SELECT {self._DEBT_COLS} FROM debts" + ("" if include_paid else " WHERE status='active'") + " ORDER BY status, next_due IS NULL, next_due, id"
        async with self.lock:
            return [self._debt(r) for r in self.db.execute(q).fetchall()]

    async def get_debt(self, debt_id):
        async with self.lock:
            r = self.db.execute(f"SELECT {self._DEBT_COLS} FROM debts WHERE id=?", (debt_id,)).fetchone()
        return self._debt(r) if r else None

    async def add_debt(self, d):
        async with self.lock:
            cur = self.db.execute(
                "INSERT INTO debts(title, kind, creditor, total, remaining, installment_amount, installments_total, "
                "installments_paid, due_day, next_due, status, note, created_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (d["title"], d.get("kind", "installment"), d.get("creditor"), d.get("total", 0), d.get("remaining", d.get("total", 0)),
                 d.get("installment_amount", 0), d.get("installments_total"), d.get("installments_paid", 0),
                 d.get("due_day"), d.get("next_due"), d.get("status", "active"), d.get("note"), time.time()))
            self.db.commit()
            return cur.lastrowid

    async def update_debt(self, debt_id, patch):
        cur = await self.get_debt(debt_id)
        if not cur:
            return None
        cols = ("title", "kind", "creditor", "total", "remaining", "installment_amount", "installments_total",
                "installments_paid", "due_day", "next_due", "status", "note")
        new = {k: (patch[k] if k in patch else cur[k]) for k in cols}
        async with self.lock:
            self.db.execute(
                "UPDATE debts SET title=?, kind=?, creditor=?, total=?, remaining=?, installment_amount=?, installments_total=?, "
                "installments_paid=?, due_day=?, next_due=?, status=?, note=? WHERE id=?",
                (*[new[k] for k in cols], debt_id))
            self.db.commit()
        return await self.get_debt(debt_id)

    async def delete_debt(self, debt_id):
        async with self.lock:
            cur = self.db.execute("DELETE FROM debts WHERE id=?", (debt_id,))
            self.db.commit()
            return cur.rowcount > 0

    # ---------- inbox (پیامک/نوتیفیکیشن ورودی از گوشی) ----------
    async def add_inbox(self, kind, source, text, ts):
        """None اگر قبلاً همین مورد ثبت شده باشد (تلاش دوباره‌ی اپ نباید خرج را دوبار ثبت کند)."""
        dedup = _sha(f"{kind}|{source}|{int(ts)}|{text}")
        async with self.lock:
            try:
                cur = self.db.execute(
                    "INSERT INTO inbox(kind, source, text, ts, dedup) VALUES(?,?,?,?,?)",
                    (kind, source, text, ts, dedup),
                )
            except sqlite3.IntegrityError:
                return None
            self.db.commit()
            return cur.lastrowid

    async def mark_inbox_parsed(self, inbox_id):
        async with self.lock:
            self.db.execute("UPDATE inbox SET parsed=1 WHERE id=?", (inbox_id,))
            self.db.commit()

    # ---------- memory (بلندمدت) ----------
    async def add_memory(self, entries):
        """entries: لیستی از dict با کلیدهای type/summary/detail/amount."""
        if not entries:
            return []
        ids = []
        async with self.lock:
            now = time.time()
            for e in entries:
                fields = e.get("fields")
                cur = self.db.execute(
                    "INSERT INTO memory(type, summary, detail, amount, ts, event_ts, category, fields) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (e.get("type", "note"), e.get("summary", ""), e.get("detail"), e.get("amount"), now,
                     e.get("when_ts"), e.get("category"),
                     json.dumps(fields, ensure_ascii=False) if fields else None),
                )
                ids.append(cur.lastrowid)
                if self.fts:
                    self.db.execute(
                        "INSERT INTO memory_fts(summary, detail, memory_id) VALUES(?,?,?)",
                        (normalize_fa(e.get("summary")), normalize_fa(e.get("detail")), cur.lastrowid),
                    )
            self.db.commit()
        return ids

    async def events_between(self, ts_from, ts_to, kinds=None):
        """رکوردهای حافظه که زمان واقعی‌شان (event_ts، وگرنه زمان ثبت) در بازه است، با when_ts."""
        async with self.lock:
            rows = self.db.execute(
                "SELECT id, type, summary, detail, amount, category, fields, COALESCE(event_ts, ts) AS w "
                "FROM memory WHERE COALESCE(event_ts, ts) >= ? AND COALESCE(event_ts, ts) < ? ORDER BY w",
                (ts_from, ts_to),
            ).fetchall()
        out = []
        for r in rows:
            if kinds and r[1] not in kinds:
                continue
            try:
                fields = json.loads(r[6]) if r[6] else {}
            except ValueError:
                fields = {}
            out.append({"id": r[0], "type": r[1], "summary": r[2], "detail": r[3], "amount": r[4],
                        "category": r[5], "fields": fields, "when_ts": r[7]})
        return out

    @staticmethod
    def _event_row(r):
        try:
            fields = json.loads(r[6]) if r[6] else {}
        except ValueError:
            fields = {}
        return {"id": r[0], "type": r[1], "summary": r[2], "detail": r[3], "amount": r[4],
                "category": r[5], "fields": fields, "when_ts": r[7]}

    _EVENT_COLS = "id, type, summary, detail, amount, category, fields, COALESCE(event_ts, ts)"

    async def get_event(self, event_id):
        async with self.lock:
            r = self.db.execute(f"SELECT {self._EVENT_COLS} FROM memory WHERE id=?", (event_id,)).fetchone()
        return self._event_row(r) if r else None

    async def update_event(self, event_id, patch):
        """patch: summary/detail/amount/category/when_ts و fields (ادغام با فیلدهای قبلی). None = بدون تغییر."""
        cur = await self.get_event(event_id)
        if not cur:
            return None
        merged_fields = dict(cur["fields"])
        if isinstance(patch.get("fields"), dict):
            merged_fields.update(patch["fields"])
        if merged_fields.get("uncertain") is False:
            merged_fields.pop("uncertain")                 # رفع ابهام: نشانهٔ «؟» حذف شود
        new = {
            "summary": patch.get("summary") if patch.get("summary") else cur["summary"],
            "detail": patch["detail"] if "detail" in patch else cur["detail"],
            "amount": patch["amount"] if "amount" in patch else cur["amount"],
            "category": patch["category"] if "category" in patch else cur["category"],
            "event_ts": patch["when_ts"] if patch.get("when_ts") else cur["when_ts"],
        }
        async with self.lock:
            self.db.execute(
                "UPDATE memory SET summary=?, detail=?, amount=?, category=?, event_ts=?, fields=? WHERE id=?",
                (new["summary"], new["detail"], new["amount"], new["category"], new["event_ts"],
                 json.dumps(merged_fields, ensure_ascii=False) if merged_fields else None, event_id))
            if self.fts:
                self.db.execute("DELETE FROM memory_fts WHERE memory_id=?", (event_id,))
                self.db.execute("INSERT INTO memory_fts(summary, detail, memory_id) VALUES(?,?,?)",
                                (normalize_fa(new["summary"]), normalize_fa(new["detail"]), event_id))
            self.db.commit()
        return await self.get_event(event_id)

    async def delete_event(self, event_id):
        async with self.lock:
            cur = self.db.execute("DELETE FROM memory WHERE id=?", (event_id,))
            if self.fts:
                self.db.execute("DELETE FROM memory_fts WHERE memory_id=?", (event_id,))
            self.db.commit()
            return cur.rowcount > 0

    async def latest_of_kinds(self, kinds, limit=15):
        """آخرین کارها/اهداف (بدون محدودیت بازه)."""
        marks = ",".join("?" for _ in kinds)
        async with self.lock:
            rows = self.db.execute(
                f"SELECT id, type, summary, detail, amount, category, fields, COALESCE(event_ts, ts) FROM memory "
                f"WHERE type IN ({marks}) ORDER BY id DESC LIMIT ?", (*kinds, limit)).fetchall()
        out = []
        for r in rows:
            try:
                fields = json.loads(r[6]) if r[6] else {}
            except ValueError:
                fields = {}
            out.append({"id": r[0], "type": r[1], "summary": r[2], "detail": r[3], "amount": r[4],
                        "category": r[5], "fields": fields, "when_ts": r[7]})
        return out

    async def search_memory(self, query, limit=10):
        """جست‌وجو در کل حافظهٔ بلندمدت (نه فقط ۴۰ مورد آخر). کلمات با OR ترکیب می‌شوند و پیشوندی‌اند
        (مثلاً «خرج» → «خرجی»). نتیجه به ترتیب ربط (bm25)؛ بدون نتیجه → []."""
        tokens = [t for t in _TOKEN.findall(normalize_fa(query)) if len(t) > 1][:8]
        if not tokens:
            return []
        async with self.lock:
            rows = []
            if self.fts:
                match = " OR ".join('"%s"*' % t.replace('"', "") for t in tokens)
                try:
                    rows = self.db.execute(
                        "SELECT m.type, m.summary, m.detail, m.amount, m.ts FROM memory_fts f "
                        "JOIN memory m ON m.id = f.memory_id WHERE memory_fts MATCH ? "
                        "ORDER BY bm25(memory_fts) LIMIT ?",
                        (match, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            else:
                like = " OR ".join("(summary LIKE ? OR detail LIKE ?)" for _ in tokens)
                params = [p for t in tokens for p in (f"%{t}%", f"%{t}%")]
                rows = self.db.execute(
                    f"SELECT type, summary, detail, amount, ts FROM memory WHERE {like} ORDER BY id DESC LIMIT ?",
                    (*params, limit),
                ).fetchall()
            return [{"type": r[0], "summary": r[1], "detail": r[2], "amount": r[3], "ts": r[4]} for r in rows]

    async def recent_memory(self, limit=40):
        async with self.lock:
            rows = self.db.execute(
                "SELECT type, summary, detail, amount, ts, id, category, fields FROM memory ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in reversed(rows):
            try:
                fields = json.loads(r[7]) if r[7] else {}
            except ValueError:
                fields = {}
            out.append({"type": r[0], "summary": r[1], "detail": r[2], "amount": r[3], "ts": r[4],
                        "id": r[5], "category": r[6], "fields": fields})
        return out

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
