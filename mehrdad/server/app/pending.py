"""تأیید قبل از ثبت خرج و درآمد.

هر خرج/درآمدی که مغز از چت یا عکس بسازد، و هر پیامک/اعلانی که شبیه تراکنش بانکی پارس شود، اول «منتظر تأیید» می‌ماند و فقط بعد از
تأیید صاحب (دکمهٔ تلگرام/اپ، یا گفتن «آره» در چت) در حافظه ثبت می‌شود. اگر صاحب ننوشته باشد «ثبت کن»، هیچ‌چیز خودکار ثبت نمی‌شود.
تنظیم: kv confirm_money (پیش‌فرض روشن؛ "0" = مثل قبل، بدون تأیید).
"""
import json
import logging
import re
import time

from . import life
from .memory import normalize_fa

log = logging.getLogger("pending")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_money(
    id INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT NOT NULL, batch TEXT, type TEXT NOT NULL, summary TEXT NOT NULL, detail TEXT,
    amount REAL, category TEXT, when_ts REAL, fields TEXT, status TEXT NOT NULL DEFAULT 'pending', source TEXT, inbox_id INTEGER,
    created_ts REAL NOT NULL, decided_ts REAL, offered INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_pending_money ON pending_money(status, created_ts);
"""
COLS = "id, origin, batch, type, summary, detail, amount, category, when_ts, fields, status, source, inbox_id, created_ts, decided_ts, offered"
CHAT_ORIGINS = ("chat", "image")
EXPIRE_HOURS = 48
CHAT_WINDOW = 30 * 60                        # «آره/نه» فقط به پرسشِ همین چند دقیقه جواب می‌دهد
MARK = "منتظر تأییدته"                        # نشانهٔ جملهٔ سرور در پاسخ؛ جواب «آره» فقط وقتی معنی دارد که آخرین پیام مهرداد این را داشته باشد

_YES = re.compile(r"^(?:آره|اره|آری|بله|بلی|ثبت\s*کن|ثبتش\s*کن|ثبت\s*بکن|تایید|تأیید|تایید\s*می‌?کنم|درسته|درست\s*ه|ok|okay|اوکی|باشه|آره\s*ثبت\s*کن|بزن\s*ثبت|آره\s*درسته|بله\s*ثبت\s*کن|ثبتش\s*کن\s*دیگه)[\s.!،؟]*$", re.I)
_NO = re.compile(r"^(?:نه|نخیر|نه\s*نکن|نکن|لغو|ثبت\s*نکن|ثبتش\s*نکن|بی\s*خیال|بیخیال|نه\s*ثبت\s*نکن|نه\s*بابا|رد\s*کن|پاک\s*کن)[\s.!،؟]*$", re.I)
_EXPLICIT = re.compile(r"(ثبت\s*کن|ثبتش\s*کن|ثبت\s*بکن|ثبت\s*بزن|اضافه\s*کن\s*به\s*(?:خرج|درآمد|هزینه))")


def money(n):
    return life.fa(f"{int(round(n or 0)):,}")


def explicit_record(user_text):
    """کاربر خودش صریحاً گفته «ثبت کن» → همان دستور تأیید است."""
    return bool(_EXPLICIT.search(normalize_fa(user_text or "")))


def parse_yes_no(text):
    t = normalize_fa(text or "").strip()
    if not t or len(t) > 40:
        return None
    if _YES.match(t):
        return "yes"
    if _NO.match(t):
        return "no"
    return None


class Pending:
    def __init__(self, bot):
        self.bot = bot
        self.mem = bot.mem
        self.db = bot.mem.db
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ------------------------------------------------------------------ تنظیم
    async def enabled(self):
        return (await self.mem.kv_get("confirm_money")) != "0"

    async def set_enabled(self, on):
        await self.mem.kv_set("confirm_money", "1" if on else "0")

    # ------------------------------------------------------------------ ردیف‌ها
    @staticmethod
    def _p(r):
        try:
            fields = json.loads(r[9]) if r[9] else None
        except ValueError:
            fields = None
        return {"id": r[0], "origin": r[1], "batch": r[2], "type": r[3], "summary": r[4], "detail": r[5], "amount": r[6] or 0.0, "category": r[7],
                "when_ts": r[8], "fields": fields, "status": r[10], "source": r[11] or "", "inbox_id": r[12], "created_ts": r[13], "decided_ts": r[14], "offered": bool(r[15])}

    async def get(self, pid):
        async with self.mem.lock:
            r = self.db.execute(f"SELECT {COLS} FROM pending_money WHERE id=?", (pid,)).fetchone()
        return self._p(r) if r else None

    async def list(self, status="pending", limit=50):
        await self.expire()
        async with self.mem.lock:
            rows = self.db.execute(f"SELECT {COLS} FROM pending_money WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
        return [self._p(r) for r in rows]

    async def max_id(self):
        async with self.mem.lock:
            return self.db.execute("SELECT COALESCE(MAX(id),0) FROM pending_money").fetchone()[0]

    async def since(self, last_id, origins=CHAT_ORIGINS):
        async with self.mem.lock:
            rows = self.db.execute(f"SELECT {COLS} FROM pending_money WHERE id>? AND status='pending' AND origin IN ({','.join('?' * len(origins))}) ORDER BY id",
                                   (last_id, *origins)).fetchall()
        return [self._p(r) for r in rows]

    async def expire(self):
        async with self.mem.lock:
            self.db.execute("UPDATE pending_money SET status='expired', decided_ts=? WHERE status='pending' AND created_ts<?", (time.time(), time.time() - EXPIRE_HOURS * 3600))
            self.db.commit()

    # ------------------------------------------------------------------ ساخت
    async def add_many(self, entries, origin, source="", inbox_id=None):
        """entries: ورودی‌های add_memory (type/summary/detail/amount/category/when_ts/fields) → لیست pending های ساخته‌شده (تکراری‌های ۱۰ دقیقهٔ اخیر نادیده)."""
        batch = f"{int(time.time())}"
        out = []
        for e in entries:
            amount = float(e.get("amount") or 0)
            async with self.mem.lock:
                dup = self.db.execute("SELECT id FROM pending_money WHERE status='pending' AND type=? AND COALESCE(amount,0)=? AND summary=? AND created_ts>?",
                                      (e["type"], amount, e.get("summary") or "", time.time() - 600)).fetchone()
                if dup:
                    continue
                cur = self.db.execute(
                    "INSERT INTO pending_money(origin, batch, type, summary, detail, amount, category, when_ts, fields, source, inbox_id, created_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (origin, batch, e["type"], (e.get("summary") or "")[:300], e.get("detail"), amount, e.get("category"), e.get("when_ts"),
                     json.dumps(e["fields"], ensure_ascii=False) if e.get("fields") else None, source, inbox_id, time.time()))
                self.db.commit()
                pid = cur.lastrowid
            out.append(await self.get(pid))
        return out

    # ------------------------------------------------------------------ نمایش
    def describe(self, p):
        label = "خرج" if p["type"] == "expense" else "درآمد"
        s = f"{'💸' if p['type'] == 'expense' else '💰'} {label} {money(p['amount'])} تومان"
        title = (p["summary"] or "").split(" (")[0]
        if title and not title.startswith(label):
            s += f" — {title}"
        if p.get("category"):
            s += f" [{p['category']}]"
        return s

    def note_for_chat(self, items):
        """خط حقیقتِ سرور زیر پاسخ مغز: چه چیزی ثبت نشده و منتظر تأیید است."""
        lines = [f"❓ {MARK} (هنوز ثبت نشده):"] + [f"• {self.describe(p)}" for p in items[:6]]
        lines.append("بگو «آره» تا ثبت کنم یا «نه»؛ دکمه‌هاش هم هست. اگه مبلغ یا چیزی اشتباهه، درستش رو بگو.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ تصمیم
    async def confirm(self, pid, patch=None):
        """→ (خط نتیجه, pending) یا (None, None) اگر نبود/قبلاً تصمیم‌گرفته شده."""
        p = await self.get(pid)
        if not p or p["status"] != "pending":
            return None, p
        if patch:
            for k in ("amount", "summary", "category"):
                if patch.get(k) not in (None, ""):
                    p[k] = patch[k]
            if patch.get("type") in ("expense", "income"):
                p["type"] = patch["type"]
        async with self.mem.lock:
            cur = self.db.execute("UPDATE pending_money SET status='confirmed', decided_ts=? WHERE id=? AND status='pending'", (time.time(), pid))
            self.db.commit()
            if cur.rowcount == 0:
                return None, p
        entry = {"type": p["type"], "summary": p["summary"], "detail": p["detail"], "amount": float(p["amount"] or 0), "category": p["category"], "when_ts": p["when_ts"], "fields": p["fields"]}
        await self.mem.add_memory([entry])
        if p.get("inbox_id"):
            await self.mem.mark_inbox_parsed(p["inbox_id"])
        p["status"] = "confirmed"
        return f"✅ ثبت شد: {self.describe(p)}", p

    async def reject(self, pid):
        p = await self.get(pid)
        if not p or p["status"] != "pending":
            return None, p
        async with self.mem.lock:
            self.db.execute("UPDATE pending_money SET status='rejected', decided_ts=? WHERE id=? AND status='pending'", (time.time(), pid))
            self.db.commit()
        p["status"] = "rejected"
        return f"❌ ثبت نشد: {self.describe(p)}", p

    async def edit(self, pid, patch):
        p = await self.get(pid)
        if not p or p["status"] != "pending":
            return None
        sets, args = [], []
        if patch.get("amount") is not None and 0 <= float(patch["amount"]) <= 1e12:
            sets.append("amount=?")
            args.append(float(patch["amount"]))
        if patch.get("category") is not None:
            sets.append("category=?")
            args.append(str(patch["category"])[:60] or None)
        if patch.get("summary"):
            sets.append("summary=?")
            args.append(str(patch["summary"])[:300])
        if patch.get("type") in ("expense", "income"):
            sets.append("type=?")
            args.append(patch["type"])
        if sets:
            async with self.mem.lock:
                self.db.execute(f"UPDATE pending_money SET {', '.join(sets)} WHERE id=? AND status='pending'", (*args, pid))
                self.db.commit()
        return await self.get(pid)

    # ------------------------------------------------------------------ چت: «آره / نه»
    async def chat_decision(self, text):
        """اگر مهرداد همین الان پرسیده «ثبت کنم؟» و کاربر فقط «آره/نه» گفت → بدون مغز تصمیم را اجرا می‌کند. وگرنه None."""
        d = parse_yes_no(text)
        if not d:
            return None
        recent = await self.mem.recent_messages(2)
        last_bot = next((m for r, m in reversed(recent) if r == "assistant"), "") if recent else ""
        if MARK not in (last_bot or ""):
            return None
        items = [p for p in await self.list() if p["origin"] in CHAT_ORIGINS and time.time() - p["created_ts"] <= CHAT_WINDOW]
        if not items:
            return None
        batch = items[0]["batch"]
        group = [p for p in items if p["batch"] == batch]
        lines = []
        for p in reversed(group):
            line, _ = await (self.confirm(p["id"]) if d == "yes" else self.reject(p["id"]))
            if line:
                lines.append(line)
        return "\n".join(lines) or None

    # ------------------------------------------------------------------ تلگرام
    async def offer(self, chat_id, items):
        """برای هر مورد یک پیام با دکمهٔ ✅ ثبت / ❌ نه."""
        from .telegram import btn
        sent = 0
        for p in items[:8]:
            text = "🧾 ثبت کنم؟\n" + self.describe(p)
            if p["origin"] not in CHAT_ORIGINS:
                text += f"\n(از {p['source'] or 'پیامک'}) «{(p['detail'] or '')[:110]}»"
            try:
                await self.bot.tg.send(chat_id, text, kb=[[btn("✅ ثبت کن", f"mc:{p['id']}:1"), btn("❌ نه", f"mc:{p['id']}:0")]])
                sent += 1
                async with self.mem.lock:
                    self.db.execute("UPDATE pending_money SET offered=1 WHERE id=?", (p["id"],))
                    self.db.commit()
            except Exception:
                log.exception("ارسال دکمه‌های تأیید ناموفق")
        if len(items) > 8:
            await self.bot.tg.send(chat_id, f"و {life.fa(len(items) - 8)} مورد دیگه هم منتظر تأییده؛ اپ ← امروز.")
        return sent

    async def callback(self, data):
        try:
            _, pid_s, ok_s = data.split(":")
            pid = int(pid_s)
        except ValueError:
            return "نامعتبر", None
        line, p = await (self.confirm(pid) if ok_s == "1" else self.reject(pid))
        if line is None:
            return ("قبلاً تصمیم گرفته شده" if p else "این مورد دیگه نیست"), p
        return line, p

    async def text(self):
        items = await self.list()
        if not items:
            return "چیزی منتظر تأیید نیست ✅"
        return "⏳ منتظر تأیید تو:\n" + "\n".join(f"• {self.describe(p)}" for p in items[:15])
