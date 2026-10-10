"""موتور «مغز» — یک تماس با Claude (Anthropic Messages API) که هم جواب مکالمه‌ای می‌دهد
هم واقعیت‌های قابل‌ذخیره را از پیام کاربر استخراج می‌کند. بدون SDK اضافه؛ فقط httpx.
"""
import asyncio
import json
import logging
import os
import re
import time

import httpx

log = logging.getLogger("brain")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOOL_ROUNDS = 4

SEARCH_TOOL = {
    "name": "search_memory",
    "description": "جست‌وجو در کل حافظهٔ بلندمدت کاربر (خرج، درآمد، ایده، کار، حس‌وحال، عادت، یادداشت) با کلمات کلیدی فارسی. "
                   "برای چیزهایی که در ۴۰ خاطرهٔ اخیر پرامپت نیست.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "کلمات کلیدی، مثلاً «قهوه تیچای قیمت»"}},
        "required": ["query"],
    },
}

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

### حافظهٔ قدیمی
در پرامپت فقط ۴۰ خاطرهٔ آخر هست. اگر کاربر درباره‌ی چیزی می‌پرسد که ممکن است قدیمی‌تر باشد («پارسال دربارهٔ … چی گفتم؟»،
«این ماه خرجم چقدر بود؟»، اسم یا ماجرایی که نمی‌بینی)، **قبل از جواب دادن** با ابزار `search_memory` جست‌وجو کن؛ حدس نزن.
اگر چیزی پیدا نشد، صادقانه بگو یادت نیست.

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


def _format_found(found):
    lines = []
    for m in found:
        day = time.strftime("%Y-%m-%d", time.localtime(m["ts"])) if m.get("ts") else "؟"
        amt = f" ({int(m['amount']):,} تومان)" if m.get("amount") else ""
        det = f" — {m['detail']}" if m.get("detail") else ""
        lines.append(f"- {day} [{m['type']}] {m['summary']}{amt}{det}")
    return "\n".join(lines)


class CLIError(Exception):
    pass


def parse_cli_output(stdout):
    """خروجی `claude -p --output-format json` → متن نتیجه. هم شکل شیء واحد و هم آرایهٔ رویدادها را می‌فهمد."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        raise CLIError(f"خروجی CLI JSON نیست: {stdout[:200]!r}")
    if isinstance(data, list):
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), None) or {}
    if not isinstance(data, dict):
        raise CLIError("شکل خروجی CLI ناشناخته است")
    if data.get("is_error"):
        raise CLIError(f"CLI خطا برگرداند: {str(data.get('result'))[:300]}")
    result = data.get("result")
    if not isinstance(result, str):
        raise CLIError("فیلد result در خروجی CLI نیست")
    return result


async def run_claude_cli(system, prompt, model="sonnet", timeout=150, binary="claude", cwd=None):
    """یک نوبت مکالمه با باینری رسمی و دست‌نخوردهٔ Claude Code (-p) با اشتراک خود کاربر
    (CLAUDE_CODE_OAUTH_TOKEN از env). بدون ابزار، یک نوبت، بدون ذخیرهٔ سشن. --bare عمداً نیست:
    آن حالت توکن OAuth را نمی‌خواند."""
    args = [binary, "-p", "--output-format", "json", "--system-prompt", system, "--tools", "",
            "--max-turns", "1", "--no-session-persistence", "--disable-slash-commands", "--model", model]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=cwd, env=os.environ.copy(),
        )
    except OSError as e:
        raise CLIError(f"اجرای {binary} ناموفق: {e}")
    try:
        out, err = await asyncio.wait_for(proc.communicate(prompt.encode("utf-8")), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise CLIError(f"CLI بعد از {timeout} ثانیه جواب نداد")
    if proc.returncode != 0:
        raise CLIError(
            f"CLI با کد {proc.returncode} خارج شد: {err.decode('utf-8', 'replace')[:300]} {out.decode('utf-8', 'replace')[:200]}"
        )
    return parse_cli_output(out.decode("utf-8", "replace"))


def _cli_prompt(messages):
    """تاریخچه + پیام تازه → یک متن برای stdin (CLI یک گفتگوی چندنوبتی نمی‌گیرد)."""
    *history, last = messages
    parts = []
    if history:
        parts.append("گفتگوی اخیر:")
        parts += [("کاربر: " if m["role"] == "user" else "مهرداد: ") + m["content"] for m in history]
        parts.append("")
    parts.append("پیام تازهٔ کاربر:")
    parts.append(last["content"])
    parts.append("")
    parts.append("جواب مهرداد را فقط به‌صورت همان JSON گفته‌شده در دستور سیستم بده.")
    return "\n".join(parts)


class Brain:
    def __init__(self, api_key, model="claude-sonnet-5-5", proxy="", search=None, provider="api",
                 cli_model="sonnet", cli_runner=None, cli_cwd=None):
        """search: coroutine async (query) -> list[dict] برای جست‌وجوی حافظه (ابزار در حالت api، پیش‌بازیابی در cli).
        provider: "api" (کلید Anthropic API، پولی) یا "cli" (باینری Claude Code با اشتراک خود کاربر).
        cli_runner: coroutine async (system, prompt, model) -> متن؛ برای تست قابل‌تزریق است."""
        self.api_key = api_key
        self.model = model
        self.search = search
        self.provider = provider
        self.cli_model = cli_model
        self.cli_runner = cli_runner or (lambda s, p, m: run_claude_cli(s, p, m, cwd=cli_cwd))
        self.client = httpx.AsyncClient(proxy=proxy or None, timeout=httpx.Timeout(60, connect=15))

    async def _call(self, system, messages, tools):
        body = {"model": self.model, "max_tokens": 1024, "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
        r = await self.client.post(
            ANTHROPIC_URL,
            headers={"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION,
                     "content-type": "application/json"},
            json=body,
        )
        if r.status_code >= 400:
            log.error("anthropic %s: %s", r.status_code, r.text[:300])
        r.raise_for_status()
        return r.json()

    async def _run_tool_loop(self, system, messages):
        """تا MAX_TOOL_ROUNDS دور: اگر مدل ابزار خواست، اجرا و نتیجه را برمی‌گردانیم؛ وگرنه جواب نهایی."""
        tools = [SEARCH_TOOL] if self.search else None
        data = await self._call(system, messages, tools)
        for _ in range(MAX_TOOL_ROUNDS):
            if data.get("stop_reason") != "tool_use":
                break
            content = data.get("content", [])
            results = []
            for b in content:
                if b.get("type") != "tool_use":
                    continue
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": await self._run_tool(b)})
            if not results:
                break
            messages = messages + [{"role": "assistant", "content": content}, {"role": "user", "content": results}]
            data = await self._call(system, messages, tools)
        return data

    async def _run_tool(self, block):
        if block.get("name") != "search_memory" or not self.search:
            return "ابزار ناشناخته."
        found = await self.search((block.get("input") or {}).get("query", ""))
        if not found:
            return "چیزی پیدا نشد."
        return _format_found(found)

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
            if self.provider == "cli":
                if self.search:  # CLI ابزار ندارد → پیش‌بازیابی از کل حافظه بر اساس پیام تازه
                    found = await self.search(user_text)
                    if found:
                        system += "\n\n### نتایج جست‌وجو در کل حافظه برای پیام تازه (اگر مرتبط است استفاده کن):\n" + _format_found(found)
                raw = await self.cli_runner(system, _cli_prompt(messages), self.cli_model)
            else:
                data = await self._run_tool_loop(system, messages)
                blocks = data.get("content", [])
                raw = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (httpx.HTTPError, ValueError, CLIError) as e:
            log.warning("brain call failed (%s): %s", self.provider, e)
            return "الان نمی‌تونم فکر کنم (مشکل در اتصال). دوباره امتحان کن.", []

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
