"""مربی: برنامهٔ روزانهٔ شخصی (تمرکز، روتین، درس، چالش، سؤال، تبدیل عادت بد، کتاب).

مبنا (از پژوهش دربارهٔ اپ‌های رشد فردی):
- قدم‌های بسیار کوچک و مشخص، نه آرزوی بزرگ (Tiny Habits)
- «وقتی X آنگاه Y» (implementation intention) و جایگزین‌کردن عادت بد، نه فقط مقاومت
- بازخورد هویتی: هر کار یک رأی به آدمی است که می‌خواهی بشوی
- استریک بخشنده: یک روز غیبت زنجیره را نمی‌شکند
- گفتگوی پرسشگرانه به‌جای نصیحت
داده‌ها در kv: coach:day:<تاریخ> (برنامه + انجام‌شده‌ها + پاسخ‌ها) و coach:books.
"""
import asyncio
import json
import logging
import re
import time

from . import life

log = logging.getLogger("coach")

COACH_SYSTEM = """تو «مهراد»، مربی و استاد شخصی کاربر هستی (نه مشاور عمومی): هر چیزی که می‌گویی باید به زندگی همین آدم و آنچه از او می‌دانی بچسبد.
اصول:
- فقط از واقعیت‌هایی که در «شناخت از کاربر» پایین می‌بینی استفاده کن؛ چیزی دربارهٔ او نساز. اگر چیزی نمی‌دانی، همان را سؤال کن.
- کوچک و مشخص: هر کار روتین/چالش در حداکثر ۱۵–۳۰ دقیقه انجام‌شدنی باشد و زمان دقیق داشته باشد.
- عادت بد را «حذف» نکن، جایگزین کن: نشانه (cue) را حدس بزن، یک جایگزین هم‌پاداش بده و «وقتی … آنگاه …» بنویس؛ هدف را تدریجی کن (مثلاً این هفته یک‌بار کمتر).
- هویتی حرف بزن: «امروز رأی می‌دهی به آدمی که …». شرم‌ده نباش، قضاوت نکن؛ صادق و دوستانه باش.
- از او سؤال بپرس و او را به چالش بکش (سؤال‌های باز و عمیق، نه بله/خیر).
- درس‌ها آموزندهٔ واقعی باشند (مفهوم + مثال + کاری که امروز بکند)، نه جملهٔ انگیزشی کلی. با کلمات خودت بنویس.
- موضوع پزشکی/روان‌درمانی جدی بود، محترمانه پیشنهاد کن با متخصص صحبت کند.
- فارسی روان و صمیمی؛ بدون ایموجی زیاد."""

PLAN_FORMAT = """فقط و فقط یک JSON معتبر بده، بدون هیچ متن دیگر، با همین شکل:
{"focus": {"title": "تمرکز امروز (کوتاه)", "identity": "امروز رأی می‌دهی به آدمی که …"},
 "routine": [{"time": "06:30", "title": "کار مشخص", "why": "چرا (یک جمله)", "minutes": 20}],
 "lesson": {"title": "عنوان درس", "body": "درس ۱۲۰ تا ۲۲۰ کلمه: مفهوم، مثال، و کاری که امروز بکند", "takeaway": "یک جملهٔ ماندگار"},
 "challenge": {"title": "چالش امروز", "steps": ["قدم ۱", "قدم ۲"], "minutes": 15},
 "questions": ["سؤال باز و چالشی ۱", "سؤال ۲"],
 "swaps": [{"bad": "عادت بدی که از او دیده‌ای", "cue": "نشانهٔ احتمالی", "replacement": "جایگزین خوب", "if_then": "وقتی … آنگاه …", "tiny_step": "قدم ۲ دقیقه‌ای", "target": "هدف تدریجی این هفته"}],
 "book": {"title": "کتاب واقعی و شناخته‌شده", "author": "نویسنده", "why": "چرا الان برای او"},
 "note": "یک جملهٔ پایانی صادقانه و دلگرم‌کننده"}
قواعد: routine بین ۴ تا ۷ مورد و به ترتیب ساعت (با توجه به ساعت بیداری/کار شناخته‌شدهٔ او)؛ questions دقیقاً ۲ تا ۳ مورد؛ swaps فقط اگر واقعاً عادت بدی از او می‌دانی (وگرنه []) حداکثر ۲ مورد؛ book اگر پیشنهاد مناسبی نداری null (کتاب نساز، فقط کتاب‌های واقعی)."""


def _s(x, n):
    return str(x).strip()[:n] if isinstance(x, (str, int, float)) and not isinstance(x, bool) and str(x).strip() else ""


def _hhmm(x):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(x or ""))
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return "%02d:%02d" % (int(m.group(1)), int(m.group(2)))
    return ""


def parse_plan(raw):
    """خروجی مدل → برنامهٔ اعتبارسنجی‌شده، یا None اگر قابل‌استفاده نیست."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).rstrip("`").strip()
    data = None
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except ValueError:
                pass
    if not isinstance(data, dict):
        return None
    focus = data.get("focus") if isinstance(data.get("focus"), dict) else {}
    lesson = data.get("lesson") if isinstance(data.get("lesson"), dict) else {}
    chal = data.get("challenge") if isinstance(data.get("challenge"), dict) else {}
    plan = {
        "focus": {"title": _s(focus.get("title"), 120), "identity": _s(focus.get("identity"), 240)},
        "routine": [], "questions": [], "swaps": [], "book": None,
        "lesson": {"title": _s(lesson.get("title"), 120), "body": _s(lesson.get("body"), 2200), "takeaway": _s(lesson.get("takeaway"), 240)},
        "challenge": {"title": _s(chal.get("title"), 140), "minutes": int(chal["minutes"]) if isinstance(chal.get("minutes"), (int, float)) and 0 < chal["minutes"] <= 240 else None,
                      "steps": [_s(x, 200) for x in (chal.get("steps") or []) if _s(x, 200)][:5] if isinstance(chal.get("steps"), list) else []},
        "note": _s(data.get("note"), 300),
    }
    for r in (data.get("routine") or [])[:8] if isinstance(data.get("routine"), list) else []:
        if isinstance(r, dict) and _s(r.get("title"), 140):
            mins = r.get("minutes")
            plan["routine"].append({"time": _hhmm(r.get("time")), "title": _s(r.get("title"), 140), "why": _s(r.get("why"), 200),
                                    "minutes": int(mins) if isinstance(mins, (int, float)) and 0 < mins <= 600 else None})
    plan["questions"] = [_s(q, 260) for q in (data.get("questions") or []) if _s(q, 260)][:3] if isinstance(data.get("questions"), list) else []
    for sw in (data.get("swaps") or [])[:2] if isinstance(data.get("swaps"), list) else []:
        if isinstance(sw, dict) and _s(sw.get("bad"), 100) and _s(sw.get("replacement"), 140):
            plan["swaps"].append({k: _s(sw.get(k), n) for k, n in (("bad", 100), ("cue", 160), ("replacement", 140), ("if_then", 240), ("tiny_step", 200), ("target", 200))})
    b = data.get("book")
    if isinstance(b, dict) and _s(b.get("title"), 120):
        plan["book"] = {"title": _s(b.get("title"), 120), "author": _s(b.get("author"), 80), "why": _s(b.get("why"), 240)}
    if not plan["focus"]["title"] and not plan["routine"] and not plan["lesson"]["body"]:
        return None
    return plan


def done_keys(plan):
    keys = [f"r{i}" for i in range(len(plan.get("routine", [])))]
    if plan.get("lesson", {}).get("body"):
        keys.append("lesson")
    if plan.get("challenge", {}).get("title"):
        keys.append("challenge")
    keys += [f"s{i}" for i in range(len(plan.get("swaps", [])))]
    keys += [f"q{i}" for i in range(len(plan.get("questions", [])))]
    return keys


def compute_stats(days, today):
    """days: {'YYYY-MM-DD': day_record}. استریک بخشنده (یک روز غیبت در هر ۷ روز اشکالی ندارد) + سطح + نوار ۷ روز."""
    import datetime
    t = datetime.date.fromisoformat(today)
    active, week, xp = {}, [], 0
    for d, rec in days.items():
        plan = rec.get("plan") or {}
        keys = done_keys(plan)
        done = [k for k in (rec.get("done") or {}) if rec["done"][k] and k in keys]
        xp += len(done)
        active[d] = (len(done), len(keys))
    for i in range(6, -1, -1):
        d = (t - datetime.timedelta(days=i)).isoformat()
        n, tot = active.get(d, (0, 0))
        week.append({"date": d, "done": n, "total": tot})
    streak, forgiven, i = 0, 0, 0
    d0 = t if active.get(t.isoformat(), (0, 0))[0] > 0 else t - datetime.timedelta(days=1)
    day = lambda k: (d0 - datetime.timedelta(days=k)).isoformat()
    while i < 400:
        if active.get(day(i), (0, 0))[0] > 0:
            streak += 1
        elif active.get(day(i + 1), (0, 0))[0] > 0 and forgiven < 1 + streak // 7:     # یک روز غیبتِ منفرد بخشیده می‌شود
            forgiven += 1
        else:
            break
        i += 1
    level = int((xp / 5) ** 0.5) + 1
    return {"streak": streak, "xp": xp, "level": level, "week": week, "today": {"done": active.get(today, (0, 0))[0], "total": active.get(today, (0, 0))[1]}}


class CoachError(Exception):
    pass


class Coach:
    def __init__(self, bot):
        self.bot = bot
        self.mem = bot.mem
        self.generating = False
        self.last_error = ""
        self._lock = asyncio.Lock()

    # ---------- ذخیره ----------
    @staticmethod
    def today():
        return life.now_tehran().date().isoformat()

    async def get_day(self, date):
        raw = await self.mem.kv_get(f"coach:day:{date}")
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    async def save_day(self, date, rec):
        await self.mem.kv_set(f"coach:day:{date}", json.dumps(rec, ensure_ascii=False))

    async def recent_days(self, n=45):
        import datetime
        t = life.now_tehran().date()
        out = {}
        for i in range(n):
            d = (t - datetime.timedelta(days=i)).isoformat()
            rec = await self.get_day(d)
            if rec:
                out[d] = rec
        return out

    async def books(self):
        raw = await self.mem.kv_get("coach:books")
        try:
            data = json.loads(raw) if raw else []
        except ValueError:
            data = []
        return data if isinstance(data, list) else []

    async def save_books(self, books):
        await self.mem.kv_set("coach:books", json.dumps(books, ensure_ascii=False))

    # ---------- وضعیت برای اپ ----------
    async def state(self):
        date = self.today()
        rec = await self.get_day(date)
        days = await self.recent_days()
        return {"date": date, "plan": (rec or {}).get("plan"), "done": (rec or {}).get("done") or {}, "answers": (rec or {}).get("answers") or {},
                "generating": self.generating, "error": self.last_error, "stats": compute_stats(days, date), "books": await self.books()}

    # ---------- ساخت برنامهٔ امروز ----------
    async def _ctx(self):
        ctx = await self.bot.context_prompt()
        habits = await self.mem.list_habits("active")
        tasks = [t for t in await self.mem.latest_of_kinds(("task",), 20) if (t.get("fields") or {}).get("status") != "done"]
        parts = []
        if ctx:
            parts.append("### شناخت از کاربر\n" + ctx)
        if habits:
            parts.append("### عادت‌هایی که دارد پیگیری می‌کند\n" + "\n".join(f"- {h['good']}" + (f" (به‌جای {h['bad']})" if h.get("bad") else "") + f" — استریک {h['streak']}" for h in habits))
        if tasks:
            parts.append("### کارهای باز\n" + "\n".join(f"- {t['summary']}" for t in tasks[:10]))
        return "\n\n".join(parts)

    async def generate(self, force=False):
        """برنامهٔ امروز را می‌سازد و ذخیره می‌کند. اگر امروز ساخته شده باشد و force نباشد، همان را برمی‌گرداند."""
        date = self.today()
        async with self._lock:
            old = await self.get_day(date)
            if old and old.get("plan") and not force:
                return old
            self.generating, self.last_error = True, ""
            try:
                days = await self.recent_days(8)
                prev = [rec["plan"] for d, rec in sorted(days.items(), reverse=True) if d != date and rec.get("plan")]
                avoid = "؛ ".join(filter(None, [p["focus"]["title"] for p in prev[:5]] + [p["lesson"]["title"] for p in prev[:5]]))
                import datetime
                yrec = days.get((life.now_tehran().date() - datetime.timedelta(days=1)).isoformat())
                ydone = len([k for k, v in (yrec or {}).get("done", {}).items() if v]) if yrec else 0
                ctx = await self._ctx()
                now = life.now_tehran()
                wd = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"][now.weekday()]
                system = COACH_SYSTEM + "\n\n" + ctx
                user = (f"امروز {wd} {life.jalali_str(now)} است. برنامهٔ امروز مرا بساز.\n"
                        + (f"دیروز {ydone} مورد از برنامه را انجام دادم.\n" if yrec else "")
                        + (f"تمرکز و درس‌های روزهای اخیر (تکرار نکن): {avoid}\n" if avoid else "")
                        + PLAN_FORMAT)
                async with self.bot.brain_lock:
                    raw = await self.bot.brain.complete(system, user)
                plan = parse_plan(raw)
                if not plan:
                    raise CoachError("خروجی مربی قابل‌خواندن نبود")
                rec = {"plan": plan, "done": (old or {}).get("done") or {}, "answers": (old or {}).get("answers") or {}, "created": time.time()}
                await self.save_day(date, rec)
                return rec
            except Exception as e:
                self.last_error = str(e)[:200] or "خطا"
                log.exception("ساخت برنامهٔ مربی ناموفق")
                raise
            finally:
                self.generating = False

    def morning_message(self, plan):
        lines = ["☀️ صبح بخیر! برنامهٔ مربی برای امروز آماده است:"]
        if plan["focus"]["title"]:
            lines.append(f"🎯 تمرکز: {plan['focus']['title']}")
        if plan["focus"]["identity"]:
            lines.append(plan["focus"]["identity"])
        if plan["challenge"]["title"]:
            lines.append(f"⚡ چالش: {plan['challenge']['title']}")
        if plan["lesson"]["title"]:
            lines.append(f"📖 درس: {plan['lesson']['title']}")
        lines.append("جزئیات و تیک‌زدن کارها: اپ ← تب مربی")
        return "\n".join(lines)

    # ---------- تعامل ----------
    async def set_done(self, key, on):
        date = self.today()
        rec = await self.get_day(date)
        if not rec or key not in done_keys(rec.get("plan") or {}):
            return None
        rec.setdefault("done", {})[key] = bool(on)
        await self.save_day(date, rec)
        return rec["done"]

    async def answer(self, idx, text):
        date = self.today()
        rec = await self.get_day(date)
        qs = ((rec or {}).get("plan") or {}).get("questions") or []
        if not rec or not (0 <= idx < len(qs)) or not text.strip():
            return None
        reply = await self.bot.chat(f"(پاسخ من به سؤال مربی: «{qs[idx]}»)\n{text.strip()[:2000]}")
        rec.setdefault("answers", {})[str(idx)] = {"text": text.strip()[:2000], "reply": reply}
        rec.setdefault("done", {})[f"q{idx}"] = True
        await self.save_day(date, rec)
        return reply

    async def track_swap(self, idx):
        """جایگزین پیشنهادی را به‌عنوان عادت قابل‌پیگیری ثبت می‌کند (چک‌این شبانه)."""
        rec = await self.get_day(self.today())
        sws = ((rec or {}).get("plan") or {}).get("swaps") or []
        if not (0 <= idx < len(sws)):
            return None
        sw = sws[idx]
        from .memory import normalize_fa
        for h in await self.mem.list_habits("active"):
            if normalize_fa(h["good"]).strip() == normalize_fa(sw["replacement"]).strip():
                return {"id": h["id"], "existing": True}
        hid = await self.mem.add_habit(sw["replacement"], sw["bad"])
        return {"id": hid, "existing": False}

    async def teach(self, topic):
        """درس کوتاه و کاربردی دربارهٔ هر موضوع، شخصی‌سازی‌شده."""
        topic = topic.strip()[:300]
        if not topic:
            return None
        ctx = await self._ctx()
        system = (COACH_SYSTEM + "\n\nحالا نقش «استاد» را داری: یک درس مستقل بده، نه برنامهٔ روزانه. متن ساده بنویس (بدون JSON، بدون مارک‌داون سنگین).\n\n" + ctx)
        user = (f"دربارهٔ «{topic}» به من آموزش بده. ساختار: ۱) ایدهٔ اصلی در دو جمله ۲) توضیح با یک مثال مرتبط با زندگی/کار خودم "
                "۳) یک تمرین ۱۰ دقیقه‌ای برای امروز ۴) دو سؤال برای سنجش فهمم. حداکثر ۴۰۰ کلمه. اگر دربارهٔ چیزی مطمئن نیستی حدس نزن و بگو.")
        async with self.bot.brain_lock:
            return (await self.bot.brain.complete(system, user)).strip()

    # ---------- کتاب ----------
    async def recommend_books(self):
        ctx = await self._ctx()
        have = "؛ ".join(b["title"] for b in await self.books())
        system = COACH_SYSTEM + "\n\n" + ctx
        user = ("۳ کتاب واقعی و شناخته‌شده پیشنهاد بده که همین الان بیشترین کمک را به هدف‌ها و مشکل‌های من می‌کند (ترجیحاً کتاب‌هایی که ترجمهٔ فارسی دارند). "
                + (f"این‌ها را قبلاً دارم، تکرار نکن: {have}. " if have else "")
                + 'فقط یک آرایهٔ JSON: [{"title": "عنوان فارسی/اصلی", "author": "نویسنده", "why": "چرا برای من (به چیزی که از من می‌دانی اشاره کن)", "level": "مبتدی|متوسط|پیشرفته"}]. کتاب نساز.')
        async with self.bot.brain_lock:
            raw = await self.bot.brain.complete(system, user)
        m = re.search(r"\[.*\]", raw or "", re.DOTALL)
        try:
            data = json.loads(m.group(0)) if m else []
        except ValueError:
            data = []
        books = await self.books()
        added = []
        for b in data[:4] if isinstance(data, list) else []:
            if isinstance(b, dict) and _s(b.get("title"), 120):
                if any(x["title"] == _s(b["title"], 120) for x in books):
                    continue
                item = {"id": int(time.time() * 1000) + len(added), "title": _s(b["title"], 120), "author": _s(b.get("author"), 80),
                        "why": _s(b.get("why"), 260), "level": _s(b.get("level"), 20), "status": "suggested", "lessons": [], "added": time.time()}
                books.append(item)
                added.append(item)
        await self.save_books(books)
        return added

    async def add_book(self, title, author="", why=""):
        books = await self.books()
        title = _s(title, 120)
        if not title:
            return None
        for b in books:
            if b["title"] == title:
                return b
        item = {"id": int(time.time() * 1000), "title": title, "author": _s(author, 80), "why": _s(why, 260), "level": "",
                "status": "suggested", "lessons": [], "added": time.time()}
        books.append(item)
        await self.save_books(books)
        return item

    async def book_lesson(self, book_id):
        """درس بعدی کتاب (به‌ترتیب ایده‌های اصلی کتاب، با کلمات خودِ مربی؛ نه بازنویسی متن کتاب)."""
        books = await self.books()
        b = next((x for x in books if x["id"] == book_id), None)
        if not b:
            return None
        n = len(b["lessons"]) + 1
        if n > 12:
            return {"book": b, "lesson": None, "finished": True}
        ctx = await self._ctx()
        prev = "؛ ".join(l["title"] for l in b["lessons"])
        system = (COACH_SYSTEM + "\n\nنقش «استاد» را داری و داری کتابی را برای او درس می‌دهی. از دانستهٔ خودت دربارهٔ کتاب استفاده کن، با کلمات خودت؛ متن کتاب را کپی نکن. "
                  "اگر مطمئن نیستی فصل/ایده‌ای در کتاب هست یا نه، آن را به کتاب نسبت نده. متن ساده، بدون JSON.\n\n" + ctx)
        user = (f"کتاب «{b['title']}»{(' از ' + b['author']) if b['author'] else ''}. درس شمارهٔ {n} را بده"
                + (f" (درس‌های قبلی: {prev})" if prev else " (از مهم‌ترین ایدهٔ کتاب شروع کن)")
                + ". ساختار: عنوان در خط اول؛ سپس ایدهٔ اصلی، توضیح با مثال مرتبط با زندگی من، و یک تمرین کوچک. حداکثر ۳۵۰ کلمه.")
        async with self.bot.brain_lock:
            text = (await self.bot.brain.complete(system, user)).strip()
        if not text:
            raise CoachError("درس خالی بود")
        first, _, rest = text.partition("\n")
        lesson = {"n": n, "title": _s(first.strip("#* :"), 100) or f"درس {n}", "body": (rest.strip() or text)[:3500], "ts": time.time()}
        b["lessons"].append(lesson)
        b["status"] = "reading"
        await self.save_books(books)
        return {"book": b, "lesson": lesson, "finished": False}

    async def set_book(self, book_id, status=None, delete=False):
        books = await self.books()
        b = next((x for x in books if x["id"] == book_id), None)
        if not b:
            return None
        if delete:
            books = [x for x in books if x["id"] != book_id]
        elif status in ("suggested", "reading", "done"):
            b["status"] = status
        await self.save_books(books)
        return True
