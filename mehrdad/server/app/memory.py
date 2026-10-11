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
_MSG_WORDS = {"پیام", "پیامک", "پیامها", "پیامهای", "اعلان", "اعلانها", "تلگرام", "واتس", "واتساپ", "اینستا", "اینستاگرام", "ایمیل", "دایرکت", "مسیج", "تماس", "تماسها"}


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
        self.extra_searchers = []         # async fn(query) → نتیجه‌های هم‌شکل search_memory (مثلاً CRM)
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
            CREATE TABLE IF NOT EXISTS invites(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                label TEXT,
                expires_ts REAL NOT NULL,
                max_uses INTEGER NOT NULL DEFAULT 3,
                uses INTEGER NOT NULL DEFAULT 0,
                created_ts REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS contacts(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ckey TEXT UNIQUE, name TEXT NOT NULL, norm TEXT NOT NULL, numbers TEXT NOT NULL, updated_ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS phone_actions(
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, to_name TEXT, to_number TEXT, text TEXT, status TEXT NOT NULL,
                detail TEXT, origin TEXT, created_ts REAL NOT NULL, updated_ts REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_pactions ON phone_actions(status, created_ts);
            CREATE TABLE IF NOT EXISTS convs(
                key TEXT PRIMARY KEY, app TEXT, title TEXT NOT NULL, norm TEXT NOT NULL, last_ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS projects(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, subtitle TEXT, status TEXT NOT NULL DEFAULT 'فعال', color TEXT, icon TEXT,
                summary TEXT, meta TEXT, pos INTEGER NOT NULL DEFAULT 0, created_ts REAL NOT NULL, updated_ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS project_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0, source TEXT, ts REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_pitems ON project_items(project_id, kind, done);
            CREATE TABLE IF NOT EXISTS project_docs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, section TEXT NOT NULL, body TEXT NOT NULL, pos INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS ix_pdocs ON project_docs(project_id, pos);
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
        icols = {r[1] for r in self.db.execute("PRAGMA table_info(inbox)").fetchall()}
        if "notified" not in icols:
            self.db.execute("ALTER TABLE inbox ADD COLUMN notified INTEGER NOT NULL DEFAULT 0")
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
            self.db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS project_docs_fts USING fts5("
                "section, body, doc_id UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
            )
            return True
        except sqlite3.OperationalError:
            return False

    # ---------- پشتیبان ----------
    async def backup_to(self, dest):
        """پشتیبان سازگار از دیتابیس زنده با API رسمی SQLite (کپی ساده‌ی فایل در حالت WAL پشتیبان معتبر نیست)."""
        async with self.lock:
            dst = sqlite3.connect(dest)
            try:
                self.db.backup(dst)
            finally:
                dst.close()
        return dest

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

    # ---------- لینک دعوت (مثلاً پرسش‌نامهٔ همسر) ----------
    async def create_invite(self, kind, label=None, days=14, max_uses=3):
        token = secrets.token_urlsafe(24)
        async with self.lock:
            cur = self.db.execute(
                "INSERT INTO invites(token_hash, kind, label, expires_ts, max_uses, created_ts) VALUES(?,?,?,?,?,?)",
                (_sha(token), kind, (label or "")[:60], time.time() + days * 86400, max_uses, time.time()))
            self.db.commit()
            return cur.lastrowid, token

    async def get_invite(self, token):
        """معتبر = وجود، باطل‌نشده، منقضی‌نشده، و ظرفیت استفاده."""
        if not token or len(token) > 80:
            return None
        async with self.lock:
            r = self.db.execute("SELECT id, kind, label, expires_ts, max_uses, uses, revoked FROM invites WHERE token_hash=?",
                                (_sha(token),)).fetchone()
        if not r or r[6] or r[3] < time.time() or r[5] >= r[4]:
            return None
        return {"id": r[0], "kind": r[1], "label": r[2], "expires_ts": r[3], "max_uses": r[4], "uses": r[5]}

    async def use_invite(self, invite_id):
        async with self.lock:
            self.db.execute("UPDATE invites SET uses = uses + 1 WHERE id=?", (invite_id,))
            self.db.commit()

    async def list_invites(self):
        async with self.lock:
            rows = self.db.execute("SELECT id, kind, label, expires_ts, max_uses, uses, revoked FROM invites ORDER BY id DESC LIMIT 20").fetchall()
        return [{"id": r[0], "kind": r[1], "label": r[2], "expires_ts": r[3], "max_uses": r[4], "uses": r[5], "revoked": bool(r[6])} for r in rows]

    async def revoke_invite(self, invite_id):
        async with self.lock:
            cur = self.db.execute("UPDATE invites SET revoked=1 WHERE id=?", (invite_id,))
            self.db.commit()
            return cur.rowcount > 0

    async def kv_get(self, key, default=None):
        async with self.lock:
            r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    async def kv_set(self, key, value):
        async with self.lock:
            if value is None:
                self.db.execute("DELETE FROM kv WHERE key=?", (key,))
            else:
                self.db.execute("INSERT INTO kv(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
            self.db.commit()

    async def kv_prefix(self, prefix):
        """همهٔ کلیدهایی که با prefix شروع می‌شوند → {key: value}."""
        esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        async with self.lock:
            rows = self.db.execute("SELECT key, value FROM kv WHERE key LIKE ? ESCAPE '\\'", (esc + "%",)).fetchall()
        return {k: v for k, v in rows}

    # ---------- مخاطبین گوشی ----------
    async def replace_contacts(self, items, replace=True):
        """items: [{"key", "name", "norm", "numbers": [..]}]. replace=True → اول همهٔ مخاطبین قبلی پاک می‌شود (برای تکهٔ اول همگام‌سازی)."""
        now = time.time()
        async with self.lock:
            if replace:
                self.db.execute("DELETE FROM contacts")
            for it in items:
                self.db.execute(
                    "INSERT INTO contacts(ckey, name, norm, numbers, updated_ts) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(ckey) DO UPDATE SET name=excluded.name, norm=excluded.norm, numbers=excluded.numbers, updated_ts=excluded.updated_ts",
                    (it["key"], it["name"], it["norm"], json.dumps(it["numbers"], ensure_ascii=False), now))
            self.db.commit()

    async def all_contacts(self):
        async with self.lock:
            rows = self.db.execute("SELECT id, ckey, name, norm, numbers FROM contacts ORDER BY name").fetchall()
        return [{"id": r[0], "key": r[1], "name": r[2], "norm": r[3], "numbers": json.loads(r[4])} for r in rows]

    async def contacts_count(self):
        async with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

    # ---------- اقدام‌های گوشی (پیامک/تماس/پیام) ----------
    _PA_COLS = "id, kind, to_name, to_number, text, status, detail, origin, created_ts, updated_ts"

    @staticmethod
    def _pa(r):
        return {"id": r[0], "kind": r[1], "to_name": r[2], "to_number": r[3], "text": r[4], "status": r[5], "detail": r[6], "origin": r[7],
                "created_ts": r[8], "updated_ts": r[9]}

    async def add_phone_action(self, a):
        now = time.time()
        async with self.lock:
            cur = self.db.execute(
                "INSERT INTO phone_actions(kind, to_name, to_number, text, status, detail, origin, created_ts, updated_ts) VALUES(?,?,?,?,?,?,?,?,?)",
                (a["kind"], a.get("to_name"), a.get("to_number"), a.get("text"), a["status"], a.get("detail"), a.get("origin"), now, now))
            self.db.commit()
            return cur.lastrowid

    async def get_phone_action(self, aid):
        async with self.lock:
            r = self.db.execute(f"SELECT {self._PA_COLS} FROM phone_actions WHERE id=?", (aid,)).fetchone()
        return self._pa(r) if r else None

    async def list_phone_actions(self, statuses=None, limit=30, kinds=None):
        q, args = f"SELECT {self._PA_COLS} FROM phone_actions", []
        cond = []
        if statuses:
            cond.append("status IN (%s)" % ",".join("?" * len(statuses)))
            args += list(statuses)
        if kinds:
            cond.append("kind IN (%s)" % ",".join("?" * len(kinds)))
            args += list(kinds)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY id DESC LIMIT ?"
        async with self.lock:
            rows = self.db.execute(q, (*args, limit)).fetchall()
        return [self._pa(r) for r in rows]

    async def set_phone_action(self, aid, status, detail=None, only_from=None):
        """تغییر وضعیت؛ only_from: فقط اگر وضعیت فعلی یکی از این‌ها باشد (برای جلوگیری از رقابت). True اگر عوض شد."""
        async with self.lock:
            q, args = "UPDATE phone_actions SET status=?, updated_ts=?" + (", detail=?" if detail is not None else "") + " WHERE id=?", [status, time.time()]
            if detail is not None:
                args.append(detail)
            args.append(aid)
            if only_from:
                q += " AND status IN (%s)" % ",".join("?" * len(only_from))
                args += list(only_from)
            cur = self.db.execute(q, args)
            self.db.commit()
            return cur.rowcount > 0

    async def phone_actions_since(self, ts, kinds=None):
        async with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM phone_actions WHERE created_ts>=? AND status NOT IN ('cancelled')", (ts,)).fetchone()[0]

    async def expire_phone_actions(self, now=None):
        now = now or time.time()
        async with self.lock:
            self.db.execute("UPDATE phone_actions SET status='expired', updated_ts=? WHERE status='awaiting' AND created_ts<?", (now, now - 15 * 60))
            self.db.execute("UPDATE phone_actions SET status='expired', detail='گوشی جواب نداد', updated_ts=? WHERE status='approved' AND updated_ts<?", (now, now - 10 * 60))
            self.db.execute("UPDATE phone_actions SET status='failed', detail='گوشی تأیید نکرد', updated_ts=? WHERE status='sending' AND updated_ts<?", (now, now - 3 * 60))
            self.db.commit()

    async def touch_conv(self, key, app, title, ts):
        """گفتگوهای پیام‌رسان که اخیراً اعلان داشته‌اند (برای «به علی توی واتس‌اپ جواب بده»)."""
        async with self.lock:
            self.db.execute(
                "INSERT INTO convs(key, app, title, norm, last_ts) VALUES(?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET app=excluded.app, title=excluded.title, norm=excluded.norm, last_ts=MAX(convs.last_ts, excluded.last_ts)",
                (key[:200], (app or "")[:40], title[:120], normalize_fa(title), ts))
            self.db.commit()

    async def find_convs(self, query, app_labels=None, within_hours=3, limit=6):
        """گفتگوهای اخیر هم‌نام با query (کلمهٔ کامل، سپس بخشی از نام)؛ app_labels: فقط این اپ‌ها."""
        nq = normalize_fa(query or "").strip()
        toks = nq.split()
        if not toks:
            return []
        since = time.time() - within_hours * 3600
        async with self.lock:
            rows = self.db.execute("SELECT key, app, title, norm, last_ts FROM convs WHERE last_ts>=? ORDER BY last_ts DESC", (since,)).fetchall()
        rows = [r for r in rows if not app_labels or r[1] in app_labels]
        exact = [r for r in rows if r[3] == nq]
        strong = exact or [r for r in rows if all(t in r[3].split() for t in toks)]
        cands = strong or [r for r in rows if all(t in r[3] for t in toks)]
        return [{"key": r[0], "app": r[1], "title": r[2], "last_ts": r[4]} for r in cands[:limit]]

    async def prune_inbox(self, days=90, kinds=("sms", "notification", "call")):
        """پیامک/اعلان/تماس‌های قدیمی‌تر از days روز پاک می‌شوند (دیتابیس باد نکند)."""
        async with self.lock:
            marks = ",".join("?" for _ in kinds)
            cur = self.db.execute(f"DELETE FROM inbox WHERE kind IN ({marks}) AND ts<?", (*kinds, time.time() - days * 86400))
            self.db.execute("DELETE FROM convs WHERE last_ts<?", (time.time() - 7 * 86400,))
            self.db.commit()
            return cur.rowcount

    async def search_inbox(self, query, limit=3):
        """پیامک/ایمیل/اعلان‌های ذخیره‌شده (داده‌ی خام؛ نه دستور) برای پاسخ به «آخرین پیام فلانی چی بود؟»."""
        tokens = [t for t in _TOKEN.findall(normalize_fa(query)) if len(t) > 1][:6]
        if not tokens:
            return []
        like = " OR ".join("(LOWER(text) LIKE ? OR LOWER(source) LIKE ?)" for _ in tokens)
        params = [p for t in tokens for p in (f"%{t}%", f"%{t}%")]
        async with self.lock:
            rows = self.db.execute(f"SELECT kind, source, text, ts FROM inbox WHERE {like} ORDER BY ts DESC LIMIT ?", (*params, limit)).fetchall()
            if set(tokens) & _MSG_WORDS:          # «کی پیام داده؟» «پیام‌های تازه» → آخرین‌ها، حتی بدون کلمهٔ مشترک
                rows += self.db.execute("SELECT kind, source, text, ts FROM inbox WHERE kind IN ('sms','notification','telegram','email','call') ORDER BY ts DESC LIMIT 8").fetchall()
        seen, out = set(), []
        for r in rows:
            if (r[1], r[2]) in seen:
                continue
            seen.add((r[1], r[2]))
            out.append({"type": r[0], "summary": f"[{r[0]} از {r[1]}] {r[2][:140]}", "detail": r[2][:500], "amount": None, "ts": r[3]})
        return out[:limit + 8]

    # ---------- پروژه‌ها ----------
    @staticmethod
    def _project(r):
        try:
            meta = json.loads(r[7]) if r[7] else {}
        except ValueError:
            meta = {}
        return {"id": r[0], "name": r[1], "subtitle": r[2] or "", "status": r[3], "color": r[4] or "#E3B35C", "icon": r[5] or "🗂",
                "summary": r[6] or "", "meta": meta, "kpis": meta.get("kpis") or [], "pos": r[8], "updated_ts": r[10]}

    _PROJ_COLS = "id, name, subtitle, status, color, icon, summary, meta, pos, created_ts, updated_ts"

    async def upsert_project(self, p):
        now = time.time()
        async with self.lock:
            cur = self.db.execute("SELECT created_ts FROM projects WHERE id=?", (p["id"],)).fetchone()
            self.db.execute(
                "INSERT INTO projects(id, name, subtitle, status, color, icon, summary, meta, pos, created_ts, updated_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, subtitle=excluded.subtitle, color=excluded.color, icon=excluded.icon, "
                "summary=excluded.summary, meta=excluded.meta, pos=excluded.pos, updated_ts=excluded.updated_ts"
                + ("" if cur else ""),
                (p["id"], p["name"], p.get("subtitle"), p.get("status") or "فعال", p.get("color"), p.get("icon"), p.get("summary"),
                 json.dumps(p.get("meta") or {}, ensure_ascii=False), int(p.get("pos") or 0), cur[0] if cur else now, now))
            self.db.commit()

    async def get_project(self, pid):
        async with self.lock:
            r = self.db.execute(f"SELECT {self._PROJ_COLS} FROM projects WHERE id=?", (pid,)).fetchone()
        return self._project(r) if r else None

    async def update_project(self, pid, patch):
        cols = {"name": "name", "subtitle": "subtitle", "status": "status", "summary": "summary", "color": "color", "icon": "icon"}
        sets = [(cols[k], v) for k, v in patch.items() if k in cols and v is not None]
        if not sets:
            return await self.get_project(pid)
        async with self.lock:
            self.db.execute("UPDATE projects SET " + ", ".join(f"{c}=?" for c, _ in sets) + ", updated_ts=? WHERE id=?",
                            (*[v for _, v in sets], time.time(), pid))
            self.db.commit()
        return await self.get_project(pid)

    async def list_projects(self):
        async with self.lock:
            rows = self.db.execute(f"SELECT {self._PROJ_COLS} FROM projects ORDER BY pos, created_ts").fetchall()
            out = []
            for r in rows:
                p = self._project(r)
                tasks = self.db.execute("SELECT id, text FROM project_items WHERE project_id=? AND kind='task' AND done=0 ORDER BY id", (p["id"],)).fetchall()
                last = self.db.execute("SELECT text, ts FROM project_items WHERE project_id=? AND kind='note' ORDER BY id DESC LIMIT 1", (p["id"],)).fetchone()
                p["open_count"] = len(tasks)
                p["open_tasks"] = [{"id": t[0], "text": t[1]} for t in tasks[:5]]
                p["last_note"] = {"text": last[0], "ts": last[1]} if last else None
                p["docs_count"] = self.db.execute("SELECT COUNT(*) FROM project_docs WHERE project_id=?", (p["id"],)).fetchone()[0]
                out.append(p)
        return out

    async def add_project_item(self, pid, kind, text, source=None):
        async with self.lock:
            cur = self.db.execute("INSERT INTO project_items(project_id, kind, text, done, source, ts) VALUES(?,?,?,0,?,?)",
                                  (pid, kind, text, source, time.time()))
            self.db.execute("UPDATE projects SET updated_ts=? WHERE id=?", (time.time(), pid))
            self.db.commit()
            return cur.lastrowid

    async def project_items(self, pid, kind=None, limit=300):
        q = "SELECT id, project_id, kind, text, done, source, ts FROM project_items WHERE project_id=?" + (" AND kind=?" if kind else "") + " ORDER BY id DESC LIMIT ?"
        args = (pid, kind, limit) if kind else (pid, limit)
        async with self.lock:
            rows = self.db.execute(q, args).fetchall()
        return [{"id": r[0], "project_id": r[1], "kind": r[2], "text": r[3], "done": bool(r[4]), "source": r[5], "ts": r[6]} for r in rows]

    async def set_project_item_done(self, item_id, done):
        async with self.lock:
            cur = self.db.execute("UPDATE project_items SET done=? WHERE id=?", (1 if done else 0, item_id))
            self.db.commit()
            return cur.rowcount > 0

    async def delete_project_item(self, item_id):
        async with self.lock:
            cur = self.db.execute("DELETE FROM project_items WHERE id=?", (item_id,))
            self.db.commit()
            return cur.rowcount > 0

    async def replace_project_docs(self, pid, docs):
        """docs: [(بخش, متن)] — همهٔ مستندات قبلیِ پروژه جایگزین می‌شود (ورود دوباره تکرار نمی‌سازد)."""
        async with self.lock:
            old = [r[0] for r in self.db.execute("SELECT id FROM project_docs WHERE project_id=?", (pid,)).fetchall()]
            if self.fts and old:
                self.db.executemany("DELETE FROM project_docs_fts WHERE doc_id=?", [(i,) for i in old])
            self.db.execute("DELETE FROM project_docs WHERE project_id=?", (pid,))
            for pos, (section, body) in enumerate(docs):
                cur = self.db.execute("INSERT INTO project_docs(project_id, section, body, pos) VALUES(?,?,?,?)", (pid, section, body, pos))
                if self.fts:
                    self.db.execute("INSERT INTO project_docs_fts(section, body, doc_id) VALUES(?,?,?)", (normalize_fa(section), normalize_fa(body), cur.lastrowid))
            self.db.commit()

    async def list_project_docs(self, pid):
        async with self.lock:
            rows = self.db.execute("SELECT id, section, LENGTH(body) FROM project_docs WHERE project_id=? ORDER BY pos", (pid,)).fetchall()
        return [{"id": r[0], "section": r[1], "size": r[2]} for r in rows]

    async def get_project_doc(self, doc_id):
        async with self.lock:
            r = self.db.execute("SELECT d.id, d.project_id, d.section, d.body, p.name FROM project_docs d JOIN projects p ON p.id=d.project_id WHERE d.id=?", (doc_id,)).fetchone()
        return {"id": r[0], "project_id": r[1], "section": r[2], "body": r[3], "project": r[4]} if r else None

    async def search_project_docs(self, query, limit=3, snippet=900):
        """جست‌وجوی مستندات پروژه‌ها؛ خروجی هم‌شکل نتیجه‌های search_memory تا مغز یکسان استفاده کند."""
        tokens = [t for t in _TOKEN.findall(normalize_fa(query)) if len(t) > 1][:8]
        if not tokens:
            return []
        async with self.lock:
            rows = []
            if self.fts:
                match = " OR ".join('"%s"*' % t.replace('"', "") for t in tokens)
                try:
                    rows = self.db.execute(
                        "SELECT p.name, d.section, d.body FROM project_docs_fts f JOIN project_docs d ON d.id=f.doc_id "
                        "JOIN projects p ON p.id=d.project_id WHERE project_docs_fts MATCH ? ORDER BY bm25(project_docs_fts) LIMIT ?",
                        (match, limit)).fetchall()
                except sqlite3.OperationalError:
                    rows = []
        return [{"type": "project", "summary": f"[پروژه {r[0]}] {r[1]}", "detail": r[2][:snippet], "amount": None, "ts": None} for r in rows]

    # ---------- inbox (پیامک/نوتیفیکیشن ورودی از گوشی) ----------
    async def add_inbox(self, kind, source, text, ts, dedup_key=None, notified=0):
        """None اگر قبلاً همین مورد ثبت شده باشد (تلاش دوباره‌ی اپ/ایجنت نباید دوبار ثبت کند)."""
        dedup = _sha(f"{kind}|key|{dedup_key}") if dedup_key else _sha(f"{kind}|{source}|{int(ts)}|{text}")
        async with self.lock:
            try:
                cur = self.db.execute(
                    "INSERT INTO inbox(kind, source, text, ts, dedup, notified) VALUES(?,?,?,?,?,?)",
                    (kind, source, text, ts, dedup, notified),
                )
            except sqlite3.IntegrityError:
                return None
            self.db.commit()
            return cur.lastrowid

    async def inbox_unnotified(self, kinds, limit=50):
        marks = ",".join("?" for _ in kinds)
        async with self.lock:
            rows = self.db.execute(
                f"SELECT id, kind, source, text, ts FROM inbox WHERE notified=0 AND kind IN ({marks}) ORDER BY ts LIMIT ?",
                (*kinds, limit)).fetchall()
        return [{"id": r[0], "kind": r[1], "source": r[2], "text": r[3], "ts": r[4]} for r in rows]

    async def recent_inbox(self, kinds, limit=15):
        marks = ",".join("?" for _ in kinds)
        async with self.lock:
            rows = self.db.execute(
                f"SELECT id, kind, source, text, ts FROM inbox WHERE kind IN ({marks}) ORDER BY id DESC LIMIT ?",
                (*kinds, limit)).fetchall()
        return [{"id": r[0], "kind": r[1], "source": r[2], "text": r[3], "ts": r[4]} for r in rows]

    async def mark_notified(self, ids):
        if not ids:
            return
        async with self.lock:
            self.db.executemany("UPDATE inbox SET notified=1 WHERE id=?", [(i,) for i in ids])
            self.db.commit()

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
            found = [{"type": r[0], "summary": r[1], "detail": r[2], "amount": r[3], "ts": r[4]} for r in rows]
        extra = []
        for fn in self.extra_searchers:
            try:
                extra += await fn(query)
            except Exception:
                pass
        return found + extra + await self.search_project_docs(query, limit=3) + await self.search_inbox(query, limit=3)

    async def recent_memory(self, limit=40):
        async with self.lock:
            rows = self.db.execute(
                "SELECT type, summary, detail, amount, ts, id, category, fields FROM memory WHERE type != 'profile' ORDER BY id DESC LIMIT ?", (limit,)
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
