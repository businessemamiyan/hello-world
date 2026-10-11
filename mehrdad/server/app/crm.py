"""CRM شخصی: مشتری/سرنخ، معامله‌ها (قیف فروش)، پیگیری‌ها و تاریخچهٔ هر مشتری.

مغز از چکیدهٔ زمینه (prompt) همیشه می‌داند چه پیگیری‌هایی عقب مانده، چه معامله‌هایی باز است و چه کسی منتظر جواب است؛
هر چه کاربر در چت بگوید با «crm_op» ثبت می‌شود (و خط تأیید را سرور می‌نویسد، نه مدل). فروشِ نقدشده خودکار در درآمدها هم می‌نشیند.
داده‌ها فقط در دیتابیس خود سرور است. هیچ پیام/تماسی از اینجا بدون تأیید صاحب فرستاده نمی‌شود (مسیر phone).
"""
import datetime
import logging
import re
import time

from . import life
from .memory import normalize_fa

log = logging.getLogger("crm")

STAGES = ("lead", "contacted", "proposal", "negotiation", "won", "lost")
OPEN_STAGES = STAGES[:4]
STAGE_FA = {"lead": "سرنخ", "contacted": "تماس گرفته‌شد", "proposal": "قیمت/پیشنهاد داده‌شد", "negotiation": "مذاکره", "won": "فروش شد ✅", "lost": "از دست رفت"}
STATUSES = ("lead", "prospect", "customer", "lost", "inactive")
STATUS_FA = {"lead": "سرنخ", "prospect": "در حال مذاکره", "customer": "مشتری", "lost": "از دست رفته", "inactive": "غیرفعال"}
CHANNELS = ("call", "sms", "visit", "telegram", "whatsapp", "email", "other")
CHANNEL_FA = {"call": "تماس", "sms": "پیامک", "visit": "دیدار", "telegram": "تلگرام", "whatsapp": "واتس‌اپ", "email": "ایمیل", "other": "—"}
OPS = ("customer", "note", "deal", "stage", "followup", "done", "sale", "payment")
STALE_DAYS = 7
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

SCHEMA = """
CREATE TABLE IF NOT EXISTS crm_customers(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, norm TEXT NOT NULL, company TEXT, phone TEXT, email TEXT,
    status TEXT NOT NULL DEFAULT 'lead', source TEXT, tags TEXT, notes TEXT,
    created_ts REAL NOT NULL, updated_ts REAL NOT NULL, last_contact_ts REAL);
CREATE TABLE IF NOT EXISTS crm_deals(
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, title TEXT NOT NULL, value REAL NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT 'lead', expected_close TEXT, lost_reason TEXT,
    created_ts REAL NOT NULL, updated_ts REAL NOT NULL, closed_ts REAL);
CREATE INDEX IF NOT EXISTS ix_crm_deals ON crm_deals(customer_id, stage);
CREATE TABLE IF NOT EXISTS crm_followups(
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, deal_id INTEGER, due TEXT NOT NULL, note TEXT, channel TEXT,
    done INTEGER NOT NULL DEFAULT 0, done_ts REAL, created_ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_crm_fu ON crm_followups(done, due);
CREATE TABLE IF NOT EXISTS crm_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, deal_id INTEGER, kind TEXT NOT NULL, text TEXT, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_crm_ev ON crm_events(customer_id, ts);
"""

C_COLS = "id, name, norm, company, phone, email, status, source, tags, notes, created_ts, updated_ts, last_contact_ts"
D_COLS = "id, customer_id, title, value, stage, expected_close, lost_reason, created_ts, updated_ts, closed_ts"
F_COLS = "id, customer_id, deal_id, due, note, channel, done, done_ts, created_ts"


def clean(x, n):
    return str(x).strip()[:n] if isinstance(x, (str, int, float)) and not isinstance(x, bool) and str(x).strip() else ""


def num(x):
    try:
        v = float(str(x).translate(_DIGITS).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if 0 <= v <= 1e12 else None


def tm(n):
    """مبلغ تومان برای نمایش: ۱٬۲۰۰٬۰۰۰ → «۱٫۲ میلیون»."""
    n = float(n or 0)
    if n >= 1e9:
        s = f"{n / 1e9:.2f}".rstrip("0").rstrip(".") + " میلیارد"
    elif n >= 1e6:
        s = f"{n / 1e6:.1f}".rstrip("0").rstrip(".") + " میلیون"
    else:
        s = f"{int(n):,}"
    return life.fa(s) + " تومان"


def parse_due(s, today=None):
    """«2026-10-20» میلادی، «1405/07/28» جلالی یا «+3» (روز دیگر) → ISO یا None."""
    today = today or life.now_tehran().date()
    s = str(s or "").strip().translate(_DIGITS)
    if not s:
        return None
    m = re.fullmatch(r"\+(\d{1,3})", s)
    if m:
        return (today + datetime.timedelta(days=int(m.group(1)))).isoformat()
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    try:
        if 1300 <= y < 1700:
            y, mo, d = life.j2g(y, mo, d)
        return datetime.date(y, mo, d).isoformat()
    except (ValueError, TypeError):
        return None


def jd(iso):
    try:
        return life.jalali_str(datetime.date.fromisoformat(iso))
    except (TypeError, ValueError):
        return iso or ""


def days_between(a_iso, b_date):
    try:
        return (b_date - datetime.date.fromisoformat(a_iso)).days
    except (TypeError, ValueError):
        return 0


class Crm:
    def __init__(self, bot):
        self.bot = bot
        self.mem = bot.mem
        self.db = bot.mem.db
        self.db.executescript(SCHEMA)
        self.db.commit()
        if hasattr(self.mem, "extra_searchers"):
            self.mem.extra_searchers.append(self.search)

    # ------------------------------------------------------------------ ردیف‌ها
    @staticmethod
    def _c(r):
        return {"id": r[0], "name": r[1], "norm": r[2], "company": r[3] or "", "phone": r[4] or "", "email": r[5] or "", "status": r[6],
                "source": r[7] or "", "tags": r[8] or "", "notes": r[9] or "", "created_ts": r[10], "updated_ts": r[11], "last_contact_ts": r[12]}

    @staticmethod
    def _d(r):
        return {"id": r[0], "customer_id": r[1], "title": r[2], "value": r[3] or 0.0, "stage": r[4], "expected_close": r[5] or "",
                "lost_reason": r[6] or "", "created_ts": r[7], "updated_ts": r[8], "closed_ts": r[9]}

    @staticmethod
    def _f(r):
        return {"id": r[0], "customer_id": r[1], "deal_id": r[2], "due": r[3], "note": r[4] or "", "channel": r[5] or "", "done": bool(r[6]),
                "done_ts": r[7], "created_ts": r[8]}

    # ------------------------------------------------------------------ مشتری
    async def list_customers(self, q="", status=None, limit=300):
        async with self.mem.lock:
            rows = self.db.execute(f"SELECT {C_COLS} FROM crm_customers ORDER BY COALESCE(last_contact_ts, updated_ts) DESC LIMIT ?", (limit,)).fetchall()
            deals = self.db.execute("SELECT customer_id, COUNT(*), COALESCE(SUM(value),0) FROM crm_deals WHERE stage IN ('lead','contacted','proposal','negotiation') GROUP BY customer_id").fetchall()
            fus = self.db.execute("SELECT customer_id, COUNT(*), MIN(due) FROM crm_followups WHERE done=0 GROUP BY customer_id").fetchall()
        dmap = {r[0]: (r[1], r[2]) for r in deals}
        fmap = {r[0]: (r[1], r[2]) for r in fus}
        n = normalize_fa(q).strip()
        out = []
        for r in rows:
            c = self._c(r)
            if status and c["status"] != status:
                continue
            if n and n not in c["norm"] and n not in normalize_fa(c["company"]) and n not in c["phone"] and n not in normalize_fa(c["notes"]):
                continue
            c["open_deals"], c["open_value"] = dmap.get(c["id"], (0, 0.0))
            c["open_followups"], c["next_due"] = fmap.get(c["id"], (0, None))
            out.append(c)
        return out

    async def get_customer(self, cid):
        async with self.mem.lock:
            r = self.db.execute(f"SELECT {C_COLS} FROM crm_customers WHERE id=?", (cid,)).fetchone()
        return self._c(r) if r else None

    async def find_customer(self, ref):
        """→ ("one", [c]) | ("many", [c…]) | ("none", [])."""
        ref = str(ref or "").strip().translate(_DIGITS)
        if not ref:
            return "none", []
        async with self.mem.lock:
            cs = [self._c(r) for r in self.db.execute(f"SELECT {C_COLS} FROM crm_customers").fetchall()]
        if ref.isdigit():
            for c in cs:
                if c["id"] == int(ref):
                    return "one", [c]
        n = normalize_fa(ref).strip()
        exact = [c for c in cs if c["norm"] == n]
        if len(exact) == 1:
            return "one", exact
        if len(exact) > 1:
            return "many", exact
        toks = n.split()
        cands = [c for c in cs if toks and all(t in c["norm"].split() or t in normalize_fa(c["company"]).split() for t in toks)]
        if not cands and len(n) >= 3:
            cands = [c for c in cs if n in c["norm"] or c["norm"] in n or (c["company"] and n in normalize_fa(c["company"]))]
        if len(cands) == 1:
            return "one", cands
        return ("many", cands) if cands else ("none", [])

    async def add_customer(self, f):
        name = clean(f.get("name"), 80)
        if not name:
            return None
        now = time.time()
        status = f.get("status") if f.get("status") in STATUSES else "lead"
        async with self.mem.lock:
            cur = self.db.execute(
                "INSERT INTO crm_customers(name, norm, company, phone, email, status, source, tags, notes, created_ts, updated_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (name, normalize_fa(name).strip(), clean(f.get("company"), 80), clean(f.get("phone"), 30), clean(f.get("email"), 80), status,
                 clean(f.get("source"), 60), clean(f.get("tags"), 120), clean(f.get("notes"), 1500), now, now))
            self.db.commit()
            cid = cur.lastrowid
        return await self.get_customer(cid)

    async def update_customer(self, cid, patch):
        sets, args = [], []
        for k, n in (("name", 80), ("company", 80), ("phone", 30), ("email", 80), ("source", 60), ("tags", 120), ("notes", 1500)):
            if k in patch and patch[k] is not None:
                sets.append(f"{k}=?")
                args.append(clean(patch[k], n))
                if k == "name":
                    sets.append("norm=?")
                    args.append(normalize_fa(clean(patch[k], n)).strip())
        if patch.get("status") in STATUSES:
            sets.append("status=?")
            args.append(patch["status"])
        if not sets:
            return await self.get_customer(cid)
        sets.append("updated_ts=?")
        args += [time.time(), cid]
        async with self.mem.lock:
            self.db.execute(f"UPDATE crm_customers SET {', '.join(sets)} WHERE id=?", args)
            self.db.commit()
        return await self.get_customer(cid)

    async def delete_customer(self, cid):
        async with self.mem.lock:
            for t in ("crm_events", "crm_followups", "crm_deals"):
                self.db.execute(f"DELETE FROM {t} WHERE customer_id=?", (cid,))
            cur = self.db.execute("DELETE FROM crm_customers WHERE id=?", (cid,))
            self.db.commit()
            return cur.rowcount > 0

    async def touch_contact(self, cid):
        async with self.mem.lock:
            self.db.execute("UPDATE crm_customers SET last_contact_ts=?, updated_ts=? WHERE id=?", (time.time(), time.time(), cid))
            self.db.commit()

    # ------------------------------------------------------------------ تاریخچه
    async def add_event(self, cid, kind, text, deal_id=None):
        async with self.mem.lock:
            self.db.execute("INSERT INTO crm_events(customer_id, deal_id, kind, text, ts) VALUES(?,?,?,?,?)", (cid, deal_id, kind, clean(text, 800), time.time()))
            self.db.commit()
        if kind in ("note", "call", "sms", "visit", "payment", "sale", "stage"):
            await self.touch_contact(cid)

    async def events(self, cid, limit=40):
        async with self.mem.lock:
            rows = self.db.execute("SELECT id, deal_id, kind, text, ts FROM crm_events WHERE customer_id=? ORDER BY id DESC LIMIT ?", (cid, limit)).fetchall()
        return [{"id": r[0], "deal_id": r[1], "kind": r[2], "text": r[3], "ts": r[4]} for r in rows]

    # ------------------------------------------------------------------ معامله
    async def list_deals(self, cid=None, open_only=False, limit=300):
        q, args, cond = f"SELECT {D_COLS} FROM crm_deals", [], []
        if cid is not None:
            cond.append("customer_id=?")
            args.append(cid)
        if open_only:
            cond.append("stage IN ('lead','contacted','proposal','negotiation')")
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY id DESC LIMIT ?"
        async with self.mem.lock:
            rows = self.db.execute(q, (*args, limit)).fetchall()
            names = dict(self.db.execute("SELECT id, name FROM crm_customers").fetchall())
        out = [self._d(r) for r in rows]
        for d in out:
            d["customer"] = names.get(d["customer_id"], "؟")
        return out

    async def get_deal(self, did):
        async with self.mem.lock:
            r = self.db.execute(f"SELECT {D_COLS} FROM crm_deals WHERE id=?", (did,)).fetchone()
        return self._d(r) if r else None

    async def add_deal(self, cid, title, value=0.0, stage="lead", expected_close=""):
        now = time.time()
        stage = stage if stage in STAGES else "lead"
        async with self.mem.lock:
            cur = self.db.execute("INSERT INTO crm_deals(customer_id, title, value, stage, expected_close, created_ts, updated_ts, closed_ts) VALUES(?,?,?,?,?,?,?,?)",
                                  (cid, clean(title, 120) or "معامله", float(value or 0), stage, clean(expected_close, 12), now, now, now if stage in ("won", "lost") else None))
            self.db.commit()
            did = cur.lastrowid
        return await self.get_deal(did)

    async def update_deal(self, did, patch):
        d = await self.get_deal(did)
        if not d:
            return None
        sets, args = [], []
        if patch.get("title"):
            sets.append("title=?")
            args.append(clean(patch["title"], 120))
        if patch.get("value") is not None and num(patch["value"]) is not None:
            sets.append("value=?")
            args.append(num(patch["value"]))
        if patch.get("expected_close") is not None:
            sets.append("expected_close=?")
            args.append(clean(patch["expected_close"], 12))
        if patch.get("lost_reason") is not None:
            sets.append("lost_reason=?")
            args.append(clean(patch["lost_reason"], 200))
        new_stage = patch.get("stage")
        if new_stage in STAGES and new_stage != d["stage"]:
            sets.append("stage=?")
            args.append(new_stage)
            sets.append("closed_ts=?")
            args.append(time.time() if new_stage in ("won", "lost") else None)
        if not sets:
            return d
        sets.append("updated_ts=?")
        args += [time.time(), did]
        async with self.mem.lock:
            self.db.execute(f"UPDATE crm_deals SET {', '.join(sets)} WHERE id=?", args)
            self.db.commit()
        out = await self.get_deal(did)
        if new_stage in STAGES and new_stage != d["stage"]:
            await self.add_event(d["customer_id"], "stage", f"«{d['title']}»: {STAGE_FA[d['stage']]} ← {STAGE_FA[new_stage]}" + (f" ({out['lost_reason']})" if new_stage == "lost" and out["lost_reason"] else ""), did)
            if new_stage == "won":
                await self.update_customer(d["customer_id"], {"status": "customer"})
            elif new_stage in ("contacted", "proposal", "negotiation"):
                c = await self.get_customer(d["customer_id"])
                if c and c["status"] in ("lead",):
                    await self.update_customer(d["customer_id"], {"status": "prospect"})
        return out

    async def delete_deal(self, did):
        async with self.mem.lock:
            self.db.execute("UPDATE crm_followups SET deal_id=NULL WHERE deal_id=?", (did,))
            cur = self.db.execute("DELETE FROM crm_deals WHERE id=?", (did,))
            self.db.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ پیگیری
    async def add_followup(self, cid, due, note="", channel="", deal_id=None):
        async with self.mem.lock:
            dup = self.db.execute("SELECT id FROM crm_followups WHERE customer_id=? AND done=0 AND due=? AND COALESCE(note,'')=?", (cid, due, clean(note, 300))).fetchone()
            if dup:
                return None
            cur = self.db.execute("INSERT INTO crm_followups(customer_id, deal_id, due, note, channel, created_ts) VALUES(?,?,?,?,?,?)",
                                  (cid, deal_id, due, clean(note, 300), channel if channel in CHANNELS else "", time.time()))
            self.db.commit()
            fid = cur.lastrowid
        return await self.get_followup(fid)

    async def get_followup(self, fid):
        async with self.mem.lock:
            r = self.db.execute(f"SELECT {F_COLS} FROM crm_followups WHERE id=?", (fid,)).fetchone()
        return self._f(r) if r else None

    async def list_followups(self, done=False, upto=None, cid=None, limit=200):
        q, args = f"SELECT {F_COLS} FROM crm_followups WHERE done=?", [1 if done else 0]
        if upto:
            q += " AND due<=?"
            args.append(upto)
        if cid is not None:
            q += " AND customer_id=?"
            args.append(cid)
        q += " ORDER BY due ASC, id ASC LIMIT ?" if not done else " ORDER BY done_ts DESC LIMIT ?"
        async with self.mem.lock:
            rows = self.db.execute(q, (*args, limit)).fetchall()
            cmap = {r[0]: (r[1], r[2]) for r in self.db.execute("SELECT id, name, phone FROM crm_customers").fetchall()}
        out = [self._f(r) for r in rows]
        for f in out:
            f["customer"], f["phone"] = cmap.get(f["customer_id"], ("؟", ""))
        return out

    async def finish_followup(self, fid, done=True):
        async with self.mem.lock:
            cur = self.db.execute("UPDATE crm_followups SET done=?, done_ts=? WHERE id=?", (1 if done else 0, time.time() if done else None, fid))
            self.db.commit()
            ok = cur.rowcount > 0
        if ok and done:
            f = await self.get_followup(fid)
            await self.add_event(f["customer_id"], "followup", "پیگیری انجام شد" + (f": {f['note']}" if f["note"] else ""))
        return ok

    async def move_followup(self, fid, due):
        async with self.mem.lock:
            cur = self.db.execute("UPDATE crm_followups SET due=? WHERE id=? AND done=0", (due, fid))
            self.db.commit()
            return cur.rowcount > 0

    async def delete_followup(self, fid):
        async with self.mem.lock:
            cur = self.db.execute("DELETE FROM crm_followups WHERE id=?", (fid,))
            self.db.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ داشبورد
    async def dashboard(self, today=None):
        today = today or life.now_tehran().date()
        iso = today.isoformat()
        week = (today + datetime.timedelta(days=7)).isoformat()
        fus = await self.list_followups(done=False)
        overdue = [f for f in fus if f["due"] < iso]
        due_today = [f for f in fus if f["due"] == iso]
        upcoming = [f for f in fus if iso < f["due"] <= week]
        for f in overdue:
            f["days_late"] = days_between(f["due"], today)
        deals = await self.list_deals(open_only=True)
        async with self.mem.lock:
            counts = dict(self.db.execute("SELECT status, COUNT(*) FROM crm_customers GROUP BY status").fetchall())
            last_ev = dict(self.db.execute("SELECT customer_id, MAX(ts) FROM crm_events GROUP BY customer_id").fetchall())
            won_rows = self.db.execute("SELECT value, closed_ts FROM crm_deals WHERE stage='won' AND closed_ts IS NOT NULL").fetchall()
            lost_n = self.db.execute("SELECT COUNT(*) FROM crm_deals WHERE stage='lost'").fetchone()[0]
        pipeline = []
        for st in OPEN_STAGES:
            ds = [d for d in deals if d["stage"] == st]
            pipeline.append({"stage": st, "label": STAGE_FA[st], "count": len(ds), "value": sum(d["value"] for d in ds)})
        has_fu = {f["customer_id"] for f in fus}
        cutoff = time.time() - STALE_DAYS * 86400
        stale = [d for d in deals if d["stage"] in ("proposal", "negotiation", "contacted") and d["customer_id"] not in has_fu
                 and max(d["updated_ts"] or 0, last_ev.get(d["customer_id"]) or 0) < cutoff]
        month_start = life.range_bounds("month")[0]
        won_month = [r for r in won_rows if (r[1] or 0) >= month_start]
        won_n = len(won_rows)
        return {"today": iso, "today_jalali": jd(iso), "customers": sum(counts.values()), "by_status": counts,
                "followups": {"overdue": overdue, "today": due_today, "upcoming": upcoming},
                "pipeline": pipeline, "open_deals": len(deals), "open_value": sum(d["value"] for d in deals), "stale": stale,
                "won_month": {"count": len(won_month), "value": sum(r[0] or 0 for r in won_month)},
                "win_rate": round(100 * won_n / (won_n + lost_n)) if (won_n + lost_n) else None}

    # ------------------------------------------------------------------ مغز و تلگرام
    async def prompt(self, max_chars=3400):
        d = await self.dashboard()
        if not d["customers"] and not d["open_deals"] and not d["followups"]["overdue"] and not d["followups"]["today"] and not d["followups"]["upcoming"]:
            return (f"### فروش و پیگیری (CRM): هنوز چیزی ثبت نشده. امروز {d['today']} ({d['today_jalali']}). "
                    "وقتی کاربر از مشتری، سرنخ، قیمت‌دادن، پیگیری یا فروش حرف زد با crm ثبت کن.")
        lines = [f"### فروش و پیگیری‌های کاربر (CRM) — امروز {d['today']} ({d['today_jalali']}). برای ثبت از crm استفاده کن؛ شناسه‌ها را از همین‌جا بگیر:"]
        p = ["%s %s" % (x["label"], life.fa(x["count"])) for x in d["pipeline"] if x["count"]]
        lines.append(f"- مشتری/سرنخ: {life.fa(d['customers'])}؛ معامله‌های باز: {life.fa(d['open_deals'])} به ارزش {tm(d['open_value'])}" + (f" ({'، '.join(p)})" if p else "")
                     + f"؛ فروش این ماه: {tm(d['won_month']['value'])} ({life.fa(d['won_month']['count'])} معامله)")
        for title, key, extra in (("پیگیری‌های عقب‌افتاده", "overdue", True), ("پیگیری امروز", "today", False), ("پیگیری ۷ روز آینده", "upcoming", False)):
            fs = d["followups"][key]
            if fs:
                lines.append(f"- {title}: " + "؛ ".join(f"[f{f['id']}] {f['customer']}" + (f" ({CHANNEL_FA[f['channel']]})" if f["channel"] else "") + (f": {f['note'][:60]}" if f["note"] else "")
                                                       + (f" — {life.fa(f['days_late'])} روز عقب" if extra else (f" — {jd(f['due'])}" if key == "upcoming" else "")) for f in fs[:8]))
        deals = await self.list_deals(open_only=True, limit=12)
        if deals:
            lines.append("- معامله‌های باز: " + "؛ ".join(f"[d{x['id']}] {x['customer']}: {x['title'][:40]} {tm(x['value'])} ({STAGE_FA[x['stage']]})" for x in deals[:10]))
        if d["stale"]:
            lines.append(f"- ⚠️ بدون پیگیری بیش از {life.fa(STALE_DAYS)} روز: " + "؛ ".join(f"{x['customer']} ({x['title'][:30]})" for x in d["stale"][:5]))
        cs = await self.list_customers(limit=30)
        if cs:
            lines.append("- اسم مشتری‌ها (برای تشخیص): " + "، ".join(f"{c['name']}" + (f" ({c['company']})" if c["company"] else "") for c in cs[:30]))
        return "\n".join(lines)[:max_chars]

    async def search(self, query, limit=4):
        """نتیجه‌های جست‌وجوی حافظه از CRM (هم‌شکل search_memory)."""
        tokens = [t for t in re.findall(r"\w+", normalize_fa(query)) if len(t) > 1][:6]
        if not tokens:
            return []
        out = []
        for c in await self.list_customers(limit=300):
            hay = " ".join((c["norm"], normalize_fa(c["company"]), normalize_fa(c["notes"]), c["phone"]))
            if not any(t in hay for t in tokens):
                continue
            ev = await self.events(c["id"], 5)
            fus = await self.list_followups(cid=c["id"], limit=3)
            deals = await self.list_deals(cid=c["id"], limit=4)
            bits = [f"وضعیت: {STATUS_FA[c['status']]}"]
            if c["phone"]:
                bits.append("شماره: " + c["phone"])
            bits += [f"معامله: {x['title']} {tm(x['value'])} ({STAGE_FA[x['stage']]})" for x in deals]
            bits += [f"پیگیری {jd(f['due'])}: {f['note']}" for f in fus]
            bits += [f"{datetime.datetime.fromtimestamp(e['ts'], life.TEHRAN).strftime('%m-%d')} {e['text']}" for e in ev]
            out.append({"type": "crm", "summary": f"[مشتری {c['name']}] " + "؛ ".join(bits)[:300], "detail": (c["notes"] + "\n" + "\n".join(bits))[:900], "amount": None, "ts": c["updated_ts"]})
            if len(out) >= limit:
                break
        return out

    def _brief(self, f, today):
        late = days_between(f["due"], today)
        s = f"• {f['customer']}"
        if f["note"]:
            s += f" — {f['note']}"
        if f["channel"]:
            s += f" ({CHANNEL_FA[f['channel']]})"
        if late > 0:
            s += f" ⏰ {life.fa(late)} روز عقب"
        return s

    async def morning_view(self):
        """(متن, کیبورد) پیگیری‌های امروز و عقب‌افتاده؛ None اگر چیزی نیست."""
        from .telegram import btn
        d = await self.dashboard()
        today = datetime.date.fromisoformat(d["today"])
        fus = d["followups"]["overdue"] + d["followups"]["today"]
        if not fus and not d["stale"]:
            return None
        lines = [f"☀️ فروش و پیگیری — {d['today_jalali']}"]
        kb = []
        if fus:
            lines.append(f"\n📞 پیگیری‌های امروز و عقب‌افتاده ({life.fa(len(fus))}):")
            lines += [self._brief(f, today) for f in fus[:10]]
            for f in fus[:6]:
                row = [btn("✅ " + f["customer"][:14], f"cf:{f['id']}:d"), btn("⏭ فردا", f"cf:{f['id']}:t")]
                if f["phone"]:
                    row.append(btn("📞", f"cf:{f['id']}:c"))
                kb.append(row)
        if d["stale"]:
            lines.append(f"\n⚠️ معامله‌های بی‌پیگیری (بیش از {life.fa(STALE_DAYS)} روز):")
            lines += [f"• {x['customer']} — {x['title']} ({tm(x['value'])})" for x in d["stale"][:5]]
        lines.append(f"\n💼 معامله‌های باز: {life.fa(d['open_deals'])} ({tm(d['open_value'])})")
        return "\n".join(lines), kb

    async def callback(self, data):
        """دکمه‌های پیام صبحگاهی: cf:<id>:d|t|c → (متن کوتاه برای toast)."""
        try:
            _, fid_s, act = data.split(":")
            fid = int(fid_s)
        except ValueError:
            return "نامعتبر"
        f = await self.get_followup(fid)
        if not f:
            return "این پیگیری دیگه نیست"
        if act == "d":
            await self.finish_followup(fid)
            return "✅ انجام شد"
        if act == "t":
            await self.move_followup(fid, (life.now_tehran().date() + datetime.timedelta(days=1)).isoformat())
            return "⏭ شد فردا"
        if act == "c":
            c = await self.get_customer(f["customer_id"])
            if not c or not c["phone"]:
                return "شماره‌ای ندارم"
            notes = await self.bot.phone.create("call", c["phone"], "", f"زنگ بزن به {c['name']}")
            return "کارت تأیید تماس برات اومد" if notes else "نشد"
        return "نامعتبر"

    async def text(self):
        d = await self.dashboard()
        if not d["customers"]:
            return "هنوز مشتری یا سرنخی ثبت نشده. توی چت بگو «یه مشتری جدید دارم: …» یا از تب «فروش» اپ اضافه کن."
        today = datetime.date.fromisoformat(d["today"])
        out = [f"💼 فروش و پیگیری — {d['today_jalali']}",
               f"مشتری/سرنخ: {life.fa(d['customers'])} | معامله باز: {life.fa(d['open_deals'])} ({tm(d['open_value'])}) | فروش این ماه: {tm(d['won_month']['value'])}"]
        for title, key in (("⏰ عقب‌افتاده", "overdue"), ("📞 امروز", "today"), ("📅 ۷ روز آینده", "upcoming")):
            fs = d["followups"][key]
            if fs:
                out.append(f"\n{title}:")
                out += [self._brief(f, today) + (f" ({jd(f['due'])})" if key == "upcoming" else "") for f in fs[:8]]
        busy = [p for p in d["pipeline"] if p["count"]]
        if busy:
            out.append("\n📊 قیف فروش: " + " | ".join(f"{p['label']} {life.fa(p['count'])} ({tm(p['value'])})" for p in busy))
        return "\n".join(out)

    # ------------------------------------------------------------------ ثبت از چت
    async def _phone_from_contacts(self, name):
        try:
            st, opts = await self.bot.phone.resolve_contact(name)
        except Exception:
            return ""
        return opts[0]["number"] if st == "one" and opts and opts[0].get("number") else ""

    async def _customer_for(self, op, create=True):
        """→ (مشتری یا None, خطا یا None, تازه‌ساخته؟)"""
        ref = clean(op.get("customer"), 80)
        if not ref:
            return None, "⚠️ اسم مشتری رو نفهمیدم؛ بگو دقیقاً کیه.", False
        st, found = await self.find_customer(ref)
        if st == "one":
            return found[0], None, False
        if st == "many":
            return None, f"⚠️ چند مشتری شبیه «{ref}» دارم: " + "، ".join(c["name"] for c in found[:5]) + "؛ دقیق‌تر بگو.", False
        if not create:
            return None, f"⚠️ مشتری «{ref}» رو پیدا نکردم.", False
        c = await self.add_customer({"name": ref, "status": "lead", "source": "چت"})
        ph = await self._phone_from_contacts(ref)
        if ph:
            c = await self.update_customer(c["id"], {"phone": ph})
        return c, None, True

    async def _pick_deal(self, c, ref="", open_only=True):
        deals = await self.list_deals(cid=c["id"], open_only=open_only)
        ref = str(ref or "").strip().translate(_DIGITS)
        if ref.lstrip("dD").isdigit():
            hit = [d for d in deals if d["id"] == int(ref.lstrip("dD"))]
            if hit:
                return hit[0], len(hit)
        n = normalize_fa(ref).strip()
        if n:
            hits = [d for d in deals if n in normalize_fa(d["title"]) or normalize_fa(d["title"]) in n]
            return (hits[0] if hits else None), len(hits)
        return (deals[0] if len(deals) == 1 else None), len(deals)

    async def apply_ops(self, ops):
        notes = []
        for op in ops[:8]:
            try:
                n = await self._apply_one(op)
            except Exception:
                log.exception("ثبت CRM ناموفق: %s", op)
                n = "⚠️ ثبت یکی از موارد فروش/پیگیری نشد."
            if n:
                notes.append(n)
        return notes

    async def _apply_one(self, op):
        kind = op["op"]
        today = life.now_tehran().date()
        if kind == "customer":
            ref = clean(op.get("customer"), 80)
            if not ref:
                return "⚠️ اسم مشتری رو نفهمیدم."
            st, found = await self.find_customer(ref)
            if st == "many":
                return f"⚠️ چند مشتری شبیه «{ref}» دارم: " + "، ".join(c["name"] for c in found[:5]) + "؛ دقیق‌تر بگو."
            fields = {k: op[k] for k in ("company", "phone", "email", "status", "source") if op.get(k)}
            if st == "one":
                c = found[0]
                if "phone" not in fields and not c["phone"]:
                    ph = await self._phone_from_contacts(c["name"])
                    if ph:
                        fields["phone"] = ph
                c = await self.update_customer(c["id"], fields)
                if op.get("text"):
                    await self.add_event(c["id"], "note", op["text"])
                return f"🤝 مشتری «{c['name']}» به‌روز شد ({STATUS_FA[c['status']]})"
            c = await self.add_customer({"name": ref, **fields, "notes": op.get("text") or ""})
            if not c["phone"]:
                ph = await self._phone_from_contacts(ref)
                if ph:
                    c = await self.update_customer(c["id"], {"phone": ph})
            await self.add_event(c["id"], "note", "مشتری/سرنخ ثبت شد" + (f": {op['text']}" if op.get("text") else ""))
            return f"🤝 مشتری تازه «{c['name']}» ({STATUS_FA[c['status']]}) ثبت شد" + (" — شمارهٔ مخاطبین گوشی هم برداشته شد" if c["phone"] and not op.get("phone") else "")
        c, err, new = await self._customer_for(op)
        if err:
            return err
        tag = " (مشتری تازه ساخته شد)" if new else ""
        if kind == "note":
            if not op.get("text"):
                return "⚠️ متن یادداشت خالیه."
            await self.add_event(c["id"], "note", op["text"])
            return f"📝 یادداشت برای «{c['name']}» ثبت شد{tag}"
        if kind == "deal":
            title = op.get("title") or op.get("text") or "معامله"
            deals = await self.list_deals(cid=c["id"], open_only=True)
            same = [d for d in deals if normalize_fa(d["title"]).strip() == normalize_fa(title).strip()]
            patch = {"value": op.get("value"), "stage": op.get("stage"), "expected_close": op.get("expected_close")}
            if same:
                d = await self.update_deal(same[0]["id"], {k: v for k, v in patch.items() if v not in (None, "")})
                return f"💼 معامله «{d['title']}» ({c['name']}) به‌روز شد: {tm(d['value'])}، {STAGE_FA[d['stage']]}"
            d = await self.add_deal(c["id"], title, op.get("value") or 0, op.get("stage") or "lead", op.get("expected_close") or "")
            await self.add_event(c["id"], "deal", f"معامله «{d['title']}» ({tm(d['value'])}) ساخته شد", d["id"])
            if d["stage"] in ("contacted", "proposal", "negotiation") and c["status"] == "lead":
                await self.update_customer(c["id"], {"status": "prospect"})
            return f"💼 معامله «{d['title']}» برای «{c['name']}» ساخته شد: {tm(d['value'])}، {STAGE_FA[d['stage']]}{tag}"
        if kind == "stage":
            stage = op.get("stage")
            d, n = await self._pick_deal(c, op.get("deal") or op.get("title") or "")
            if not d:
                return (f"⚠️ چند معامله برای «{c['name']}» هست؛ بگو کدوم." if n > 1 else f"⚠️ معاملهٔ بازی برای «{c['name']}» پیدا نکردم.")
            patch = {"stage": stage}
            if stage == "lost":
                patch["lost_reason"] = op.get("reason") or op.get("text") or ""
            d2 = await self.update_deal(d["id"], patch)
            return f"📈 «{d2['title']}» ({c['name']}) شد «{STAGE_FA[d2['stage']]}»"
        if kind == "followup":
            due = parse_due(op.get("due"), today)
            if not due:
                return f"⚠️ تاریخ پیگیری «{c['name']}» رو نفهمیدم؛ بگو چه روزی."
            if due < today.isoformat():
                return f"⚠️ تاریخ پیگیری «{c['name']}» گذشته؛ یه روز از امروز به بعد بگو."
            d, _ = await self._pick_deal(c, op.get("deal") or "")
            f = await self.add_followup(c["id"], due, op.get("note") or op.get("text") or "", op.get("channel") or "", d["id"] if d else None)
            if not f:
                return f"⏰ پیگیری «{c['name']}» برای {jd(due)} از قبل بود"
            return f"⏰ پیگیری «{c['name']}» برای {jd(due)} ثبت شد" + (f": {f['note']}" if f["note"] else "") + tag
        if kind == "done":
            fus = await self.list_followups(cid=c["id"])
            if op.get("followup"):
                fus = [f for f in fus if f["id"] == int(op["followup"])] or fus
            iso = today.isoformat()
            due_now = [f for f in fus if f["due"] <= iso] or fus[:1]
            if not due_now:
                msg = f"ℹ️ پیگیری بازی برای «{c['name']}» نبود"
            else:
                for f in due_now:
                    await self.finish_followup(f["id"])
                msg = f"✅ پیگیری «{c['name']}» انجام شد" + (f" ({life.fa(len(due_now))} مورد)" if len(due_now) > 1 else "")
            if op.get("text"):
                await self.add_event(c["id"], "note", op["text"])
            nd = parse_due(op.get("next_due"), today)
            if nd and nd >= iso:
                nf = await self.add_followup(c["id"], nd, op.get("next_note") or "", op.get("channel") or "")
                if nf:
                    msg += f"؛ پیگیری بعدی {jd(nd)}"
            return msg
        if kind in ("sale", "payment"):
            amount = num(op.get("amount")) if op.get("amount") is not None else num(op.get("value"))
            if kind == "payment" and not amount:
                return "⚠️ مبلغ دریافتی رو نفهمیدم."
            title = op.get("title") or "فروش"
            msg = ""
            if kind == "sale":
                d, _ = await self._pick_deal(c, op.get("deal") or op.get("title") or "")
                if d:
                    d = await self.update_deal(d["id"], {"stage": "won", "value": amount if amount else None})
                else:
                    d = await self.add_deal(c["id"], title, amount or 0, "won")
                    await self.update_customer(c["id"], {"status": "customer"})
                    await self.add_event(c["id"], "sale", f"فروش «{d['title']}» {tm(d['value'])}", d["id"])
                amount = amount or d["value"]
                msg = f"💰 فروش «{d['title']}» به «{c['name']}» ثبت شد: {tm(d['value'])}"
            paid = bool(op.get("paid")) or kind == "payment"
            if paid and amount:
                await self.mem.add_memory([{"type": "income", "summary": f"{'فروش' if kind == 'sale' else 'دریافتی'} از {c['name']}: {title}", "detail": None, "amount": amount,
                                            "category": "فروش", "when_ts": time.time(), "fields": None}])
                await self.add_event(c["id"], "payment", f"دریافت {tm(amount)}")
                return (msg + " — و در درآمدها هم ثبت شد ✓") if msg else f"💵 دریافتی {tm(amount)} از «{c['name']}» در درآمدها ثبت شد ✓"
            return msg + " (هنوز وصول نشده؛ بگو کِی پیگیری وصول بذارم)"
        return None
