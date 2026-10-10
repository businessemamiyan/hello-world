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

### ساخت عادت و دیسیپلین — این بخش مهم‌ترین نقش توست
کاربر صریحاً گفته: اکثر آدم‌ها نه به‌خاطر کمبود استعداد بلکه کمبود دیسیپلین شکست می‌خورند، و
می‌خواهد تو کمکش کنی عادت‌های بد را کنار بگذارد و عادت‌های قدرتمند جایگزین بسازد. اصولی که
همیشه رعایت کن:
- **هویت‌محور فکر کن، نه فقط رفتار**: به‌جای «باید ورزش کنی» بگو چیزی که نشان دهد او در حال
  تبدیل‌شدن به «کسی‌ست که…» است (مثل اصل عادت‌های اتمی جیمز کلییر). تغییر کوچک و پایدار از
  یک قهرمانی یک‌روزه و بی‌دوام مهم‌تر است.
- وقتی کاربر توی مکالمه‌ی عادی (نه با فرمان /habit) اشاره کرد که می‌خواهد یک عادت بد را کنار
  بگذارد یا عادتی بسازد، تشویقش کن با `/habit` ثبتش کند تا استریک و یادآوری شبانه برایش فعال
  شود — دستور دقیق را بگو: «/habit به‌جای <عادت بد>، <عادت خوب>» یا فقط «/habit <عادت خوب>».
- وقتی در بخش «عادت‌های فعال» (پایین‌تر) می‌بینی استریکی شکسته شده یا صفر شده، **سرزنش نکن** —
  مثل یک مربی واقعی، با همدلی ولی جدی برگردان به مسیر: چرا شکست؟ چه مانعی بود؟ قدم بعدی چیست؟
  وقتی استریک بالا می‌رود، واقعاً تشویق کن — نه چاپلوسی، بلکه تصدیق واقعی پیشرفت.
- اگر کاربر درباره‌ی یک عادت بد (مثلاً تنبلی، اهمال‌کاری، اعتیاد به گوشی) حرف زد بدون اینکه
  هنوز ثبتش کرده باشد، کمکش کن محرک (trigger) آن را پیدا کند و یک جایگزین کوچک و عملی پیشنهاد
  بده — نه یک برنامه‌ی غیرواقعی و بزرگ.

**قالب خروجی**: فقط و فقط یک JSON معتبر (بدون ```json و بدون هیچ متن قبل/بعدش) با این شکل:
{"reply": "<جواب فارسی تو به کاربر>", "memory": [{"type": "<expense|income|idea|task|feeling|habit|note|other>", "summary": "<خلاصه یک‌خطی>", "detail": "<جزئیات اختیاری>", "amount": <عدد تومان یا null>}]}
نوع "habit" فقط برای وقتی است که کاربر درباره‌ی عادتی حرف می‌زند بدون اینکه با /habit ثبتش کرده
باشد (فقط برای حافظه — ساخت ردیف واقعی عادت و استریک فقط با دستور /habit انجام می‌شود، نه این JSON).

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


def _build_habits_block(active_habits):
    if not active_habits:
        return "(هنوز هیچ عادتی ثبت نکرده — اگر مناسب بود پیشنهاد بده با /habit شروع کند.)"
    lines = []
    for h in active_habits:
        base = h["good"] if not h.get("bad") else f"{h['good']} (به‌جای {h['bad']})"
        lines.append(f"- #{h['id']} {base} — استریک فعلی: {h['streak']} روز (بهترین: {h['best_streak']})")
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

    async def think(self, recent_history, recent_memory, user_text, active_habits=None):
        """recent_history: لیست (role, text) از پیام‌های اخیر (بدون پیام جدید).
        recent_memory: خروجی memory.recent_memory().
        user_text: پیام تازه‌ی کاربر.
        active_habits: خروجی memory.list_habits("active") — اختیاری.
        برمی‌گرداند: (reply_text, memory_entries)
        """
        context = _build_context_block(recent_memory)
        habits_block = _build_habits_block(active_habits or [])
        system = (
            SYSTEM_PROMPT
            + "\n\n### عادت‌های فعال کاربر (برای تشویق/پیگیری، بدون اینکه هر بار درباره‌شان حرف بزنی مگر مرتبط باشد):\n"
            + habits_block
            + "\n\n### خاطرات اخیر کاربر (برای زمینه، تکرار نکن مگر لازم باشد):\n"
            + context
        )

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
        valid_types = {"expense", "income", "idea", "task", "feeling", "habit", "note", "other"}
        clean = []
        for e in entries:
            if not isinstance(e, dict) or not e.get("summary"):
                continue
            t = e.get("type") if e.get("type") in valid_types else "note"
            amount = e.get("amount")
            amount = float(amount) if isinstance(amount, (int, float)) else None
            clean.append({"type": t, "summary": str(e["summary"]), "detail": e.get("detail"), "amount": amount})
        return parsed["reply"], clean
