"""موتور «مغز» — یک تماس با Claude (Anthropic Messages API) که هم جواب مکالمه‌ای می‌دهد
هم واقعیت‌های قابل‌ذخیره را از پیام کاربر استخراج می‌کند. بدون SDK اضافه؛ فقط httpx.
"""
import json
import logging
import re
import time

import httpx

log = logging.getLogger("brain")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """تو «مهرداد» هستی — مغز دومِ کاربر. نه یک اپ، نه یک فرم؛ یک همراه واقعی که همه‌چیز
زندگی و کار و پول کاربر را پیگیری می‌کند و کنارش می‌ماند.

نقش تو ثابت نیست — بر اساس چیزی که کاربر الان نیاز دارد، همان نقش را واقعاً بازی کن (نه فقط اسمش را بیاور):
- وقتی باید برنامه بچیند → پلنر باش: مشخص، قابل‌اجرا، با قدم بعدی روشن.
- وقتی دلش شکسته یا گیر کرده → مربی/همراه باش: اول گوش کن و حس را تصدیق کن، بعد راهنمایی کن.
- وقتی چیزی نمی‌داند یا می‌خواهد یاد بگیرد → استاد باش: ساده و دقیق توضیح بده، مثال بزن.
- وقتی دنبال فکر تازه است → ایده‌پرداز باش: جسور و عملی فکر کن، گزینه بده نه فقط یک جواب.
- در همه حالت‌ها → رفیق باش: صمیمی، صادق، بدون چاپلوسی بی‌دلیل؛ واقعیت و مزایا/معایب را بگو، نه فقط تعریف.

کاربر صاحب این مغز، مهرداد نام دارد: سرپرست واحد سپیا در یک کارخانه تولیدی، در حال ساخت چند
منبع درآمد مستقل (ازجمله فروش قهوه فوری تیچای) و در مسیر یادگیری فروش و هوش مصنوعی برای رسیدن
به آزادی مالی. بلندپرواز و نتیجه‌گراست؛ تعریف بی‌دلیل نمی‌خواهد، واقعیت و چالش را می‌خواهد.

قانون کلیدی: هر پیامی که می‌فرستد را به‌خاطر بسپار — خرج، درآمد، ایده، کار، احساس، هرچی. تو باید
علاوه بر جواب مکالمه‌ای، واقعیت‌های قابل‌ذخیره را هم استخراج کنی.

**قالب خروجی**: فقط و فقط یک JSON معتبر (بدون ```json و بدون هیچ متن قبل/بعدش) با این شکل:
{"reply": "<جواب فارسی تو به کاربر>", "memory": [{"type": "<expense|income|idea|task|feeling|note|other>", "summary": "<خلاصه یک‌خطی>", "detail": "<جزئیات اختیاری>", "amount": <عدد تومان یا null>}]}

اگر پیام کاربر چیز قابل‌ذخیره‌ای نداشت (مثلاً فقط سلام یا یک سوال عمومی)، memory را [] بگذار.
جواب‌ها را کوتاه و مستقیم بنویس — مثل یک رفیق باهوش، نه یک مقاله."""


def _build_context_block(recent_memory):
    if not recent_memory:
        return "(هنوز هیچ خاطره‌ای ثبت نشده.)"
    lines = []
    for m in recent_memory[-40:]:
        amt = f" ({int(m['amount']):,} تومان)" if m.get("amount") else ""
        lines.append(f"- [{m['type']}] {m['summary']}{amt}")
    return "\n".join(lines)


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).rstrip("`").strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                pass
    return None


class Brain:
    def __init__(self, api_key, model="claude-sonnet-5", proxy=""):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(proxy=proxy or None, timeout=httpx.Timeout(60, connect=15))

    async def think(self, recent_history, recent_memory, user_text):
        """recent_history: لیست (role, text) از پیام‌های اخیر (بدون پیام جدید).
        recent_memory: خروجی memory.recent_memory().
        user_text: پیام تازه‌ی کاربر.
        برمی‌گرداند: (reply_text, memory_entries)
        """
        context = _build_context_block(recent_memory)
        system = SYSTEM_PROMPT + "\n\n### خاطرات اخیر کاربر (برای زمینه، تکرار نکن مگر لازم باشد):\n" + context

        messages = []
        for role, text in recent_history[-20:]:
            messages.append({"role": "user" if role == "user" else "assistant", "content": text})
        messages.append({"role": "user", "content": user_text})

        try:
            r = await self.client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": messages,
                },
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("anthropic call failed: %s", e)
            return "الان نمی‌تونم فکر کنم (مشکل در اتصال). دوباره امتحان کن.", []

        blocks = data.get("content", [])
        raw = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        parsed = _extract_json(raw)
        if not parsed or "reply" not in parsed:
            log.warning("could not parse brain JSON: %r", raw[:300])
            return raw.strip() or "یه لحظه گیر کردم؛ دوباره بگو چی گفتی؟", []

        entries = parsed.get("memory") or []
        valid_types = {"expense", "income", "idea", "task", "feeling", "note", "other"}
        clean = []
        for e in entries:
            if not isinstance(e, dict) or not e.get("summary"):
                continue
            t = e.get("type") if e.get("type") in valid_types else "note"
            amount = e.get("amount")
            amount = float(amount) if isinstance(amount, (int, float)) else None
            clean.append({"type": t, "summary": str(e["summary"]), "detail": e.get("detail"), "amount": amount})
        return parsed["reply"], clean
