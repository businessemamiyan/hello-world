"""منطق مشترک ایجنت‌های پیام (ایمیل/تلگرام): تجزیهٔ ایمیل، امتیازدهی اهمیت، و ثبت در inbox مهرداد.

اصول ایمنی:
- فقط‌خواندنی: هیچ پیامی ارسال، حذف یا علامت‌گذاری (خوانده‌شده) نمی‌شود.
- رمز یک‌بارمصرف/کد تأیید هرگز ذخیره یا فوروارد نمی‌شود (همان فیلتر ingest.is_sensitive).
- فقط خلاصهٔ کوتاه (موضوع + چند خط اول) ذخیره می‌شود، نه متن کامل.
- محتوای پیام «داده» است؛ هیچ دستوری داخلش اجرا نمی‌شود (جایی به مغز به‌عنوان دستور نمی‌رود).
"""
import email
import email.header
import email.utils
import html
import re
import time

from . import life
from .ingest import is_sensitive

HIGH_WORDS = ("فوری", "urgent", "سررسید", "due date", "invoice", "فاکتور", "پرداخت", "payment", "قرارداد", "contract",
              "جلسه", "meeting", "deadline", "مهلت", "اخطار", "warning", "بدهی", "قسط", "رسید", "receipt", "تماس بگیر",
              "reminder", "یادآوری")
LOW_HINTS = ("unsubscribe", "no-reply", "noreply", "do-not-reply", "newsletter", "خبرنامه", "تخفیف", "promotion", "sale")
SNIPPET = 600


def _decode(value):
    if not value:
        return ""
    parts = []
    for text, enc in email.header.decode_header(value):
        if isinstance(text, bytes):
            try:
                text = text.decode(enc or "utf-8", "replace")
            except LookupError:
                text = text.decode("utf-8", "replace")
        parts.append(text)
    return " ".join("".join(parts).split())


def _body_text(msg):
    """اولین بخش text/plain؛ اگر نبود HTML بدون تگ. حداکثر SNIPPET کاراکتر، فشرده."""
    plain = html_part = None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        if ctype in ("text/plain", "text/html"):
            try:
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", "replace")
            except (LookupError, ValueError):
                continue
            if ctype == "text/plain" and plain is None:
                plain = text
            elif ctype == "text/html" and html_part is None:
                html_part = text
    text = plain
    if text is None and html_part is not None:
        text = html.unescape(re.sub(r"<(script|style).*?</\1>|<[^>]+>", " ", html_part, flags=re.S | re.I))
    return " ".join((text or "").split())[:SNIPPET]


def parse_email(raw):
    """raw: بایت‌های (حتی ناقص) یک ایمیل → dict(subject, sender, sender_addr, snippet, message_id, ts, list_unsub)."""
    msg = email.message_from_bytes(raw)
    name, addr = email.utils.parseaddr(_decode(msg.get("From", "")))
    try:
        ts = email.utils.parsedate_to_datetime(msg.get("Date")).timestamp() if msg.get("Date") else time.time()
    except (TypeError, ValueError):
        ts = time.time()
    return {"subject": _decode(msg.get("Subject", "")) or "(بدون موضوع)", "sender": name or addr or "نامشخص",
            "sender_addr": addr.lower(), "snippet": _body_text(msg), "message_id": (msg.get("Message-ID") or "").strip(),
            "ts": ts, "list_unsub": bool(msg.get("List-Unsubscribe"))}


def score(text, sender="", sender_addr="", allow=(), list_unsub=False):
    """«high» (اعلان فوری)، «normal» (فقط در خلاصهٔ دوره‌ای)، یا «skip» (ذخیره/ارسال نشود)."""
    if is_sensitive(text):
        return "skip"
    addr = (sender_addr or "").lower()
    if any(a and (addr == a or addr.endswith("@" + a.lstrip("@")) or a.lower() in (sender or "").lower()) for a in allow):
        return "high"
    low = text.lower()
    if list_unsub or any(h in addr for h in ("noreply", "no-reply", "donotreply")) or any(h in low[:200] for h in LOW_HINTS):
        return "normal" if any(w in low for w in HIGH_WORDS[:8]) else "skip"
    if any(w in low for w in HIGH_WORDS):
        return "high"
    return "normal"


def one_line(kind_icon, source, text, limit=160):
    t = " ".join(text.split())
    return f"{kind_icon} {source}: {t[:limit]}{'…' if len(t) > limit else ''}"


def digest_text(items, limit=12):
    """items: ردیف‌های inbox (kind/source/text). متن خلاصهٔ تلگرامی برای مواردی که هنوز اعلام نشده‌اند."""
    if not items:
        return None
    icon = {"email": "📧", "telegram": "💬"}
    lines = [f"📬 خلاصهٔ پیام‌های جدید ({life.fa(len(items))} مورد)"]
    for it in items[:limit]:
        lines.append(one_line(icon.get(it["kind"], "•"), it["source"] or "؟", it["text"], 110))
    if len(items) > limit:
        lines.append(f"… و {life.fa(len(items) - limit)} مورد دیگر (/inbox)")
    return "\n".join(lines)
