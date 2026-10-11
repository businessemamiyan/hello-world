"""کنترل گوشی: مخاطبین، پیامک، تماس، پیام تلگرام/اینستاگرام — فقط با دستور صاحب و (پیش‌فرض) تأیید یک‌لمسی.

اصل امنیتی: مغز فقط «پیشنهاد اقدام» می‌سازد؛ هیچ اقدامی بدون تأیید صاحب (دکمهٔ ✅ در اپ/تلگرام) اجرا نمی‌شود، مگر صاحب
«ارسال بدون تأیید» را روشن کرده باشد و خودِ پیامش نام/شمارهٔ گیرنده را گفته باشد و گیرنده یکتا باشد. محتوای پیامک/ایمیل/اعلان هرگز
دستور نیست (فقط داده)؛ سقف ساعتی و ثبت کامل تاریخچه هم هست.
"""
import asyncio
import json
import logging
import re
import time

from . import life
from .memory import normalize_fa
from .telegram import btn

log = logging.getLogger("phone")

KINDS = ("sms", "call", "telegram", "instagram")
LABEL = {"sms": "پیامک", "call": "تماس", "telegram": "پیام تلگرام", "instagram": "پیام اینستاگرام"}
PHONE_EXEC = ("sms", "call", "instagram")           # این‌ها را خود گوشی اجرا می‌کند (تلگرام را سرور)
MAX_TEXT = 600
HOURLY_LIMIT = 12
_PERSIAN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_NUMLIKE = re.compile(r"^[+\d\s\-()]{7,20}$")
DEFAULTS = {"auto_confirm": False, "sms_all": False}


def norm_number(s):
    """شمارهٔ ایرانی را به شکل 09xxxxxxxxx؛ سایر شماره‌ها فقط ارقام (با +) یا None اگر شمارهٔ معتبر نیست."""
    t = str(s or "").translate(_PERSIAN)
    digits = re.sub(r"\D", "", t)
    if not (7 <= len(digits) <= 15):
        return None
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    return digits


def clean_text(s):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s or "")).strip()[:MAX_TEXT]


def mask(n):
    return (n[:4] + "…" + n[-3:]) if n and len(n) > 8 else (n or "")


def describe(a):
    who = a.get("to_name") or ""
    num = a.get("to_number") or ""
    to = f"«{who}»" + (f" ({mask(num)})" if num and not str(num).startswith("tg:") else "") if who else mask(num)
    body = f"\n«{a['text']}»" if a.get("text") else ""
    return f"{LABEL[a['kind']]} به {to}{body}"


class Phone:
    def __init__(self, bot):
        self.bot = bot
        self.mem = bot.mem

    # ---------- تنظیمات و وضعیت ----------
    async def settings(self):
        raw = await self.mem.kv_get("phone:settings")
        try:
            s = json.loads(raw) if raw else {}
        except ValueError:
            s = {}
        return {**DEFAULTS, **{k: bool(s.get(k)) for k in DEFAULTS}}

    async def save_settings(self, patch):
        s = await self.settings()
        s.update({k: bool(v) for k, v in patch.items() if k in DEFAULTS and v is not None})
        await self.mem.kv_set("phone:settings", json.dumps(s))
        return s

    async def touch(self):
        await self.mem.kv_set("phone:last_seen", str(time.time()))

    async def online(self, within=120):
        try:
            return time.time() - float(await self.mem.kv_get("phone:last_seen", "0")) < within
        except ValueError:
            return False

    async def status(self):
        await self.mem.expire_phone_actions()
        acts = await self.mem.list_phone_actions(limit=15)
        return {"contacts": await self.mem.contacts_count(), "settings": await self.settings(), "online": await self.online(),
                "pending": [a for a in acts if a["status"] == "awaiting"], "recent": acts}

    async def prompt(self):
        """خط کوتاه برای مغز: چه چیزی در دسترس است (بدون هیچ نام/شماره)."""
        n = await self.mem.contacts_count()
        on = await self.online()
        tg = bool(getattr(self.bot, "tg_agent", None) and getattr(self.bot.tg_agent, "ready", False))
        return (f"### گوشی: {life.fa(n)} مخاطب همگام‌شده؛ گوشی {'وصل است' if on else 'الان وصل نیست (اقدام در صف می‌ماند)'}؛ "
                f"تلگرام شخصی {'آماده' if tg else 'وصل نیست'}. برای پیامک/تماس/پیام از phone استفاده کن (فقط وقتی صاحب صریحاً خواست).")

    # ---------- پیدا کردن مخاطب ----------
    async def resolve_contact(self, query):
        """→ ("number"|"one"|"many"|"none", [{"name", "number"}])"""
        q = (query or "").strip()
        if not q:
            return "none", []
        if _NUMLIKE.match(q.translate(_PERSIAN)):
            n = norm_number(q)
            return ("number", [{"name": None, "number": n}]) if n else ("none", [])
        nq = normalize_fa(q).strip()
        toks = nq.split()
        contacts = await self.mem.all_contacts()
        exact = [c for c in contacts if c["norm"] == nq]
        strong = exact or [c for c in contacts if toks and all(t in c["norm"].split() for t in toks)]
        cands = strong or [c for c in contacts if toks and all(t in c["norm"] for t in toks)]
        opts, seen = [], set()
        for c in cands:
            nums = [x for x in (norm_number(n) for n in c["numbers"]) if x]
            mobiles = [x for x in nums if x.startswith("09")]
            for num in (mobiles or nums):
                if (c["name"], num) not in seen:
                    seen.add((c["name"], num))
                    opts.append({"name": c["name"], "number": num})
        if not opts:
            return "none", []
        if len({o["number"] for o in opts}) == 1:
            return "one", [opts[0]]
        return "many", opts[:6]

    # ---------- ساخت اقدام ----------
    async def create_many(self, ops, user_text=""):
        notes = []
        for op in ops[:3]:
            notes.extend(await self.create(op["kind"], op.get("to") or "", op.get("text") or "", user_text))
        return notes

    async def create(self, kind, to, text, user_text=""):
        """→ لیست خط‌های تأیید برای زیر پاسخ. اقدام با وضعیت awaiting (یا approved در حالت بدون‌تأیید) ثبت می‌شود."""
        if kind not in KINDS:
            return ["⚠️ نوع اقدام گوشی نامعتبر بود."]
        text = clean_text(text)
        if kind != "call" and not text:
            return [f"⚠️ برای {LABEL[kind]} متن لازمه؛ بگو چی بنویسم."]
        if kind == "call":
            text = ""
        if not (to or "").strip():
            return [f"⚠️ {LABEL[kind]} رو به کی بزنم؟ اسم یا شماره رو بگو."]
        await self.mem.expire_phone_actions()
        if await self.mem.phone_actions_since(time.time() - 3600) >= HOURLY_LIMIT:
            return [f"⚠️ سقف ساعتی اقدام‌های گوشی ({life.fa(HOURLY_LIMIT)}) پر شده؛ کمی بعد دوباره بگو."]
        target = {"name": None, "number": None}
        exact_by_owner = False
        if kind in ("sms", "call"):
            status, opts = await self.resolve_contact(to)
            if status == "none":
                n = await self.mem.contacts_count()
                return [f"⚠️ مخاطب «{to}» رو پیدا نکردم" + ("؛ مخاطبین گوشی هنوز همگام نشده (تنظیمات ← دسترسی به گوشی)." if not n else "؛ اسم دقیق‌تر یا شمارهٔ کامل رو بگو.")]
            if status == "many":
                lst = "؛ ".join(f"{o['name'] or '؟'} ({mask(o['number'])})" for o in opts)
                return [f"⚠️ چند نفر با «{to}» جور شدن: {lst}. کدوم؟ (اسم کامل یا شماره)"]
            target = opts[0]
            nu = normalize_fa(user_text or "")
            exact_by_owner = bool((target["name"] and normalize_fa(target["name"]) and all(t in nu for t in normalize_fa(target["name"]).split()[:1]))
                                  or (status == "number" and re.sub(r"\D", "", (user_text or "").translate(_PERSIAN)).find(target["number"][-9:]) >= 0))
        elif kind == "telegram":
            agent = getattr(self.bot, "tg_agent", None)
            if not agent or not getattr(agent, "ready", False):
                return ["⚠️ ایجنت تلگرام وصل نیست (یک‌بار: docker exec -it mehrdad-mehrdad-1 python -m app.agent_tg login)."]
            found = await agent.find_dialogs(to)
            if not found:
                return [f"⚠️ توی تلگرامت کسی به اسم «{to}» پیدا نکردم."]
            if len(found) > 1:
                return [f"⚠️ چند نفر با «{to}» جور شدن: " + "؛ ".join(f['title'] for f in found[:5]) + ". کدوم؟"]
            target = {"name": found[0]["title"], "number": f"tg:{found[0]['id']}"}
            nu = normalize_fa(user_text or "")
            exact_by_owner = all(t in nu for t in normalize_fa(found[0]["title"]).split()[:1])
        else:                                                          # instagram: خودِ گوشی فقط صفحهٔ ارسال را باز می‌کند
            target = {"name": to.strip()[:80], "number": None}
        st = await self.settings()
        auto = bool(st["auto_confirm"] and exact_by_owner and kind in ("sms", "call", "telegram"))
        aid = await self.mem.add_phone_action({"kind": kind, "to_name": target["name"], "to_number": target["number"], "text": text,
                                               "status": "approved" if auto else "awaiting", "origin": "chat"})
        a = await self.mem.get_phone_action(aid)
        if auto:
            await self._after_approve(a)
            return [f"📲 {describe(a)} — دارم می‌فرستم…"]
        await self._announce(a)
        return [f"📲 آمادهٔ ارسال: {describe(a)}\nتأیید کن تا انجام بشه (دکمه‌ها رو تو تلگرام یا اپ ← امروز می‌بینی)."]

    async def _announce(self, a):
        owner = await self.mem.get_owner()
        if not owner:
            return
        try:
            await self.bot.tg.send(owner, f"📲 تأیید می‌کنی؟\n{describe(a)}", kb=[[btn("✅ بفرست", f"pa:{a['id']}:1"), btn("❌ لغو", f"pa:{a['id']}:0")]])
        except Exception:
            log.exception("ارسال کارت تأیید ناموفق")

    # ---------- تأیید/لغو/اجرا ----------
    async def decide(self, aid, ok):
        """→ (متن نتیجه برای کاربر, اقدام)"""
        a = await self.mem.get_phone_action(aid)
        if not a:
            return "این اقدام دیگه وجود نداره.", None
        if not ok:
            await self.mem.set_phone_action(aid, "cancelled", only_from=("awaiting", "approved"))
            return "❌ لغو شد.", a
        if not await self.mem.set_phone_action(aid, "approved", only_from=("awaiting",)):
            return {"expired": "⏱ مهلت تأیید تموم شده بود؛ دوباره بگو.", "approved": "قبلاً تأیید شده.", "sent": "قبلاً ارسال شده."}.get(a["status"], "الان قابل تأیید نیست."), a
        a = await self.mem.get_phone_action(aid)
        msg = await self._after_approve(a)
        return msg, a

    async def _after_approve(self, a):
        if a["kind"] == "telegram":
            return await self._send_telegram(a)
        if await self.online():
            return "✅ تأیید شد؛ گوشی داره انجامش می‌ده…"
        return "✅ تأیید شد، ولی گوشی الان وصل نیست؛ تا ۱۰ دقیقه توی صف می‌مونه (اپ رو باز کن یا «کنترل گوشی» رو روشن کن)."

    async def _send_telegram(self, a):
        agent = getattr(self.bot, "tg_agent", None)
        try:
            await agent.send(int(str(a["to_number"])[3:]), a["text"])
        except Exception as e:
            await self.mem.set_phone_action(a["id"], "failed", detail=type(e).__name__)
            log.warning("tg send failed: %s", type(e).__name__)
            return f"⚠️ پیام تلگرام ارسال نشد ({type(e).__name__})."
        await self.mem.set_phone_action(a["id"], "sent", detail="ok")
        return f"✅ پیام تلگرام به «{a['to_name']}» ارسال شد."

    # ---------- سمت گوشی ----------
    async def claim_next(self):
        await self.mem.expire_phone_actions()
        for a in reversed(await self.mem.list_phone_actions(statuses=("approved",), kinds=PHONE_EXEC, limit=5)):
            if await self.mem.set_phone_action(a["id"], "sending", only_from=("approved",)):
                return {"id": a["id"], "kind": a["kind"], "to_name": a["to_name"], "to_number": a["to_number"], "text": a["text"]}
        return None

    async def ack(self, aid, status, detail=""):
        """گوشی نتیجه را می‌گوید: sent | failed | needs_tap (نیاز به یک لمس روی گوشی). → متن برای کاربر."""
        a = await self.mem.get_phone_action(aid)
        if not a or status not in ("sent", "failed", "needs_tap"):
            return None
        await self.mem.set_phone_action(aid, status, detail=(detail or "")[:200], only_from=("sending", "approved"))
        who = a["to_name"] or mask(a["to_number"] or "")
        msg = {"sent": f"✅ {LABEL[a['kind']]} به «{who}» " + ("انجام شد." if a["kind"] == "call" else "ارسال شد."),
               "failed": f"⚠️ {LABEL[a['kind']]} به «{who}» انجام نشد: {detail or 'خطا'}",
               "needs_tap": f"👆 {LABEL[a['kind']]} به «{who}» آماده‌ست؛ روی گوشی‌ت اعلان مهرداد رو بزن تا تمام بشه."}[status]
        await self.bot.notify_owner(msg)
        return msg
