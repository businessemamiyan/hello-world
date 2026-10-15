"""API اپ اندروید مهرداد — جفت‌سازی با کد یک‌بارمصرف، چت، تاریخچه، و دریافت پیامک/اعلان مالی.

احراز هویت: توکن اختصاصی هر دستگاه (Bearer)؛ فقط هش آن در دیتابیس است و با /unpair در تلگرام باطل می‌شود.
هیچ رمز ثابتی در .env یا داخل اپ نیست. /api/pair با محدودیت تعداد تلاش ناموفق محافظت می‌شود.
"""
import asyncio
import hashlib
import json
import logging
import os
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import finance, life, novatunnel, payroll as payroll_mod, profile
from .ingest import is_sensitive, memory_entry, parse_bank_text
from .memory import normalize_fa
from .phone import norm_number
from .media import decode_image_b64
from .tts import TTSError
from .crm import parse_due, tm
from .coaches import CoachRoomError

log = logging.getLogger("api")

MAX_PAIR_FAILS = 5
PAIR_WINDOW = 600


class PairIn(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field(default="گوشی", max_length=60)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class PendingSettingsIn(BaseModel):
    confirm: bool


class PendingEditIn(BaseModel):
    amount: float | None = Field(default=None, ge=0, le=1e12)
    summary: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, max_length=60)
    type: str | None = Field(default=None, pattern="^(expense|income)$")


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    voice: str | None = Field(default=None, pattern="^(male|female)$")


KIND_PATTERN = "^(" + "|".join(life.KINDS) + ")$"


class EventIn(BaseModel):
    type: str = Field(pattern=KIND_PATTERN)
    summary: str = Field(min_length=1, max_length=300)
    detail: str | None = Field(default=None, max_length=1000)
    amount: float | None = Field(default=None, ge=0, le=1e12)
    category: str | None = Field(default=None, max_length=60)
    when: str | None = Field(default=None, max_length=20)
    end: str | None = Field(default=None, max_length=20)
    minutes: float | None = Field(default=None, gt=0, le=1440)
    status: str | None = Field(default=None, pattern="^(done|ongoing|planned|maybe)$")
    fields: dict | None = None


class EventPatch(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=300)
    detail: str | None = Field(default=None, max_length=1000)
    amount: float | None = Field(default=None, ge=0, le=1e12)
    category: str | None = Field(default=None, max_length=60)
    when: str | None = Field(default=None, max_length=20)
    end: str | None = Field(default=None, max_length=20)
    minutes: float | None = Field(default=None, gt=0, le=1440)
    status: str | None = Field(default=None, pattern="^(done|ongoing|planned|maybe)$")
    fields: dict | None = None


def _span_fields(fields, when_ts, end, minutes, status):
    """end/minutes/status از فرم → داخل fields (end_ts به epoch)."""
    out = dict(fields or {})
    end_ts = life.parse_end(end, when_ts) if end else None
    if end_ts is None and minutes and when_ts:
        end_ts = when_ts + minutes * 60
    if end_ts:
        out["end_ts"] = end_ts
    if minutes:
        out["minutes"] = minutes
    if status:
        out["status"] = status
    return out or None


def _check_date(s):
    if s:
        import datetime
        try:
            datetime.date.fromisoformat(s)
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")


def _check_fields(fields):
    if fields is not None and len(str(fields)) > 2000:
        raise HTTPException(status_code=422, detail="fields too large")


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: str = Field(default="bank", pattern="^(bank|cash|wallet|crypto|other)$")
    balance: float = Field(default=0, ge=-1e13, le=1e13)
    note: str | None = Field(default=None, max_length=200)


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    kind: str | None = Field(default=None, pattern="^(bank|cash|wallet|crypto|other)$")
    balance: float | None = Field(default=None, ge=-1e13, le=1e13)
    note: str | None = Field(default=None, max_length=200)


DEBT_KIND = "^(installment|loan|credit_card|personal|other)$"


class DebtIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    kind: str = Field(default="installment", pattern=DEBT_KIND)
    creditor: str | None = Field(default=None, max_length=80)
    total: float = Field(default=0, ge=0, le=1e13)
    remaining: float | None = Field(default=None, ge=0, le=1e13)
    installment_amount: float = Field(default=0, ge=0, le=1e13)
    installments_total: int | None = Field(default=None, ge=1, le=600)
    installments_paid: int = Field(default=0, ge=0, le=600)
    due_day: int | None = Field(default=None, ge=1, le=31)
    next_due: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=200)


class DebtPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    kind: str | None = Field(default=None, pattern=DEBT_KIND)
    creditor: str | None = Field(default=None, max_length=80)
    total: float | None = Field(default=None, ge=0, le=1e13)
    remaining: float | None = Field(default=None, ge=0, le=1e13)
    installment_amount: float | None = Field(default=None, ge=0, le=1e13)
    installments_total: int | None = Field(default=None, ge=1, le=600)
    installments_paid: int | None = Field(default=None, ge=0, le=600)
    due_day: int | None = Field(default=None, ge=1, le=31)
    next_due: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, pattern="^(active|paid)$")
    note: str | None = Field(default=None, max_length=200)


class PayIn(BaseModel):
    amount: float | None = Field(default=None, ge=0, le=1e13)
    record_expense: bool = True


class HabitIn(BaseModel):
    good: str = Field(min_length=1, max_length=120)
    bad: str | None = Field(default=None, max_length=120)


class ChatImageIn(BaseModel):
    image: str = Field(min_length=100, max_length=9_000_000)
    text: str = Field(default="", max_length=2000)


class PayslipIn(BaseModel):
    earn: dict[str, float] = Field(default_factory=dict, max_length=20)
    ded: dict[str, float] = Field(default_factory=dict, max_length=20)
    work: dict[str, float] = Field(default_factory=dict, max_length=20)
    totals: dict[str, float] | None = Field(default=None, max_length=5)
    unit: str = Field(default="toman", pattern="^(toman|rial)$")


class PayVarIn(BaseModel):
    month: str | None = Field(default=None, max_length=8)
    op: str = Field(max_length=20)
    value: float = Field(ge=0, le=1e13)
    mode: str = Field(default="add", pattern="^(add|set)$")


class PayrollSettingsIn(BaseModel):
    unit: str | None = Field(default=None, pattern="^(toman|rial)$")
    day_basis: str | None = Field(default=None, pattern="^(auto|month|30|30cap)$")
    insurable: list[str] | None = Field(default=None, max_length=12)


class CrmCustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    company: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, pattern="^(lead|prospect|customer|lost|inactive)$")
    source: str | None = Field(default=None, max_length=60)
    tags: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1500)


class CrmCustomerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    company: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, pattern="^(lead|prospect|customer|lost|inactive)$")
    source: str | None = Field(default=None, max_length=60)
    tags: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1500)


class CrmNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=800)


class CrmDealIn(BaseModel):
    customer_id: int
    title: str = Field(min_length=1, max_length=120)
    value: float = Field(default=0, ge=0, le=1e12)
    stage: str = Field(default="lead", pattern="^(lead|contacted|proposal|negotiation|won|lost)$")
    expected_close: str | None = Field(default=None, max_length=12)


class CrmDealPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    value: float | None = Field(default=None, ge=0, le=1e12)
    stage: str | None = Field(default=None, pattern="^(lead|contacted|proposal|negotiation|won|lost)$")
    expected_close: str | None = Field(default=None, max_length=12)
    lost_reason: str | None = Field(default=None, max_length=200)
    paid: bool | None = None


class CrmFollowupIn(BaseModel):
    customer_id: int
    due: str = Field(max_length=12)
    note: str | None = Field(default=None, max_length=300)
    channel: str | None = Field(default=None, pattern="^(call|sms|visit|telegram|whatsapp|email|other)$")
    deal_id: int | None = None


class CrmFollowupPatch(BaseModel):
    done: bool | None = None
    due: str | None = Field(default=None, max_length=12)


class CrmContactIn(BaseModel):
    kind: str = Field(pattern="^(call|sms)$")
    text: str | None = Field(default=None, max_length=600)


class ProjectItemIn(BaseModel):
    kind: str = Field(pattern="^(task|note)$")
    text: str = Field(min_length=1, max_length=500)


class ProjectItemPatch(BaseModel):
    done: bool


class ProjectPatch(BaseModel):
    status: str | None = Field(default=None, min_length=1, max_length=40)
    summary: str | None = Field(default=None, max_length=700)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    subtitle: str = Field(default="", max_length=160)


class ContactIn(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    numbers: list[str] = Field(default_factory=list, max_length=6)


class ContactsSyncIn(BaseModel):
    contacts: list[ContactIn] = Field(max_length=600)
    replace: bool = False


class PhoneSettingsIn(BaseModel):
    auto_confirm: bool | None = None
    sms_all: bool | None = None


class PhoneAckIn(BaseModel):
    status: str = Field(pattern="^(sent|failed|needs_tap)$")
    detail: str = Field(default="", max_length=200)


class SmsSyncItem(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    address: str = Field(default="", max_length=60)
    body: str = Field(min_length=1, max_length=1500)
    ts: float
    box: str = Field(default="inbox", pattern="^(inbox|sent)$")


class SmsSyncIn(BaseModel):
    messages: list[SmsSyncItem] = Field(max_length=300)


class CoachDoneIn(BaseModel):
    key: str = Field(min_length=1, max_length=12)
    on: bool = True


class CoachAnswerIn(BaseModel):
    idx: int = Field(ge=0, le=5)
    kind: str = Field(default="q", pattern="^[qe]$")
    text: str = Field(default="", max_length=2000)
    image: str | None = Field(default=None, min_length=100, max_length=9_000_000)


class CoachRoomAskIn(BaseModel):
    text: str = Field(default="", max_length=2000)
    image: str | None = Field(default=None, min_length=100, max_length=9_000_000)


class CoachRoomLessonIn(BaseModel):
    topic: str = Field(default="", max_length=300)


class CoachRoomPathIn(BaseModel):
    goal: str = Field(default="", max_length=300)


class CoachSubIn(BaseModel):
    on: bool
    time: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")


class CoachRoomDoneIn(BaseModel):
    on: bool = True


class CoachTeachIn(BaseModel):
    topic: str = Field(default="", max_length=300)
    image: str | None = Field(default=None, min_length=100, max_length=9_000_000)


class CoachBookIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    author: str = Field(default="", max_length=80)


class CoachBookPatch(BaseModel):
    status: str = Field(pattern="^(suggested|reading|done)$")


class InviteIn(BaseModel):
    label: str | None = Field(default=None, max_length=40)
    days: int = Field(default=14, ge=1, le=60)


class WifeOneIn(BaseModel):
    qid: str = Field(min_length=1, max_length=8)
    text: str = Field(default="", max_length=1600)
    who: str | None = Field(default=None, max_length=40)


class WifeIn(BaseModel):
    answers: dict[str, str] = Field(max_length=20)
    who: str | None = Field(default=None, max_length=40)


class IngestItem(BaseModel):
    kind: str = Field(pattern="^(sms|notification)$")
    source: str = Field(default="", max_length=120)
    text: str = Field(min_length=1, max_length=2000)
    ts: float
    app: str = Field(default="", max_length=40)            # فقط اعلان پیام‌رسان‌ها (واتس‌اپ/تلگرام/اینستاگرام/…)
    conv: str = Field(default="", max_length=160)          # کلید گفتگو روی گوشی (برای جواب‌دادن)
    title: str = Field(default="", max_length=120)         # نام فرستنده/گروه


class CallItem(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    number: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=100)
    type: str = Field(pattern="^(incoming|outgoing|missed|rejected)$")
    ts: float
    duration: int = Field(default=0, ge=0, le=86400)


class CallsSyncIn(BaseModel):
    calls: list[CallItem] = Field(max_length=300)


class CalendarItem(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    title: str = Field(default="", max_length=140)
    start: float
    end: float = 0
    location: str = Field(default="", max_length=140)


class CalendarSyncIn(BaseModel):
    events: list[CalendarItem] = Field(max_length=300)


class IngestIn(BaseModel):
    items: list[IngestItem] = Field(max_length=50)


def _client_ip(request: Request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


async def _store_wife_answers(mem, clean, who):
    """clean: {qid: text}. جواب قبلیِ همان سؤال جایگزین می‌شود (نه تکرار)."""
    qmap = {q[0]: q for q in profile.WIFE_QUESTIONS}
    for old in await mem.latest_of_kinds(("profile",), 300):
        f = old.get("fields") or {}
        if f.get("source") == "همسر" and f.get("qid") in clean:
            await mem.delete_event(old["id"])
    who = (who or "").strip()[:40]
    await mem.add_memory([{
        "type": "profile", "summary": text if len(text) <= 280 else text[:277] + "…", "detail": text,
        "category": qmap[qid][1], "fields": {"source": "همسر", "qid": qid, "question": qmap[qid][2], **({"who": who} if who else {})}}
        for qid, text in clean.items() if text])


async def save_wife_answers(mem, svc, token, answers, who=None):
    """ثبت همهٔ پاسخ‌های همسر یک‌جا (fetch/JSON یا فرم ساده). LookupError = لینک نامعتبر؛ ValueError = بدون پاسخ."""
    inv = await mem.get_invite(token)
    if not inv:
        raise LookupError("invalid")
    qmap = {q[0]: q for q in profile.WIFE_QUESTIONS}
    clean = {}
    for qid, text in (answers or {}).items():
        text = (text or "").strip()
        if qid in qmap and text:
            clean[qid] = text[:1500]
    if not clean:
        raise ValueError("no answers")
    await _store_wife_answers(mem, clean, who)
    await mem.use_invite(inv["id"])
    await svc.notify_owner(f"✅ همسرت به {life.fa(len(clean))} سؤال جواب داد. توی اپ ← هدف‌ها ← پروفایل ببین (هر کدوم رو خواستی می‌تونی پاک کنی).")
    return len(clean)


async def save_one_wife_answer(mem, token, qid, text, who=None):
    """ذخیرهٔ خودکار یک جواب (درخواست کوچک، مناسب اینترنت ضعیف). متن خالی = پاک‌کردن جواب قبلی. مصرف «نوبت» لینک نمی‌شود."""
    inv = await mem.get_invite(token)
    if not inv:
        raise LookupError("invalid")
    if qid not in {q[0] for q in profile.WIFE_QUESTIONS}:
        raise ValueError("bad qid")
    text = (text or "").strip()[:1500]
    if text:
        await _store_wife_answers(mem, {qid: text}, who)
    else:
        for old in await mem.latest_of_kinds(("profile",), 300):
            f = old.get("fields") or {}
            if f.get("source") == "همسر" and f.get("qid") == qid:
                await mem.delete_event(old["id"])
    return 1 if text else 0


def create_router(mem, svc):
    """svc: شیئی با `async chat(text) -> reply` و `async notify_owner(text)` (همان Bot)."""
    router = APIRouter(prefix="/api")
    fails = defaultdict(deque)
    public_hits = defaultdict(deque)

    async def current_device(authorization: str = Header(default="")):
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        dev = await mem.device_for_token(token)
        if not dev:
            raise HTTPException(status_code=401, detail="invalid token")
        return dev

    @router.get("/app/version")
    async def app_version():
        """نسخهٔ آخرین APK منتشرشده (عمومی؛ APK هیچ رمزی ندارد و فقط با کلید امضای ثابت قابل نصب روی نسخهٔ قبلی است)."""
        cfg = getattr(svc, "cfg", None)
        path = os.path.join(getattr(cfg, "data_dir", "/data"), "apk", "version.json")
        try:
            with open(path, encoding="utf-8") as f:
                v = json.load(f)
            return {"versionCode": int(v["versionCode"]), "versionName": str(v.get("versionName", "")),
                    "sha256": str(v["sha256"]), "size": int(v.get("size", 0)), "notes": str(v.get("notes", ""))[:500],
                    "url": "/download/mehrdad.apk"}
        except (OSError, ValueError, KeyError):
            return {"versionCode": 0}

    @router.post("/pair")
    async def pair(body: PairIn, request: Request):
        ip = _client_ip(request)
        q = fails[ip]
        now = time.time()
        while q and now - q[0] > PAIR_WINDOW:
            q.popleft()
        if len(q) >= MAX_PAIR_FAILS:
            raise HTTPException(status_code=429, detail="too many attempts")
        if not await mem.consume_pair_code(body.code):
            q.append(now)
            raise HTTPException(status_code=403, detail="invalid or expired code")
        device_id, token = await mem.add_device(body.name)
        await svc.notify_owner(f"📱 دستگاه «{body.name}» به مهرداد وصل شد (#{device_id}). اگه خودت نبودی: /unpair {device_id}")
        return {"token": token, "device_id": device_id}

    @router.get("/me")
    async def me(dev=Depends(current_device)):
        return {"ok": True, "device": dev}

    @router.post("/chat")
    async def chat(body: ChatIn, dev=Depends(current_device)):
        pend = getattr(svc, "pending", None)
        before = await pend.max_id() if pend else 0
        reply = await svc.chat(body.text)
        fresh = await pend.since(before) if pend else []
        return {"reply": reply, "ts": time.time(), "pending": fresh}

    @router.post("/tts")
    async def tts(body: TTSIn, dev=Depends(current_device)):
        """متن → MP3 فارسی (برای «جواب‌ها رو بلند بخون» و گفتگوی صوتی)."""
        engine = getattr(svc, "tts", None)
        if engine is None:
            raise HTTPException(status_code=503, detail="tts disabled")
        try:
            data = await engine.synth(body.text, body.voice or (await mem.kv_get("tts_voice")) or None)
        except TTSError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return Response(content=data, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    @router.get("/dashboard")
    async def dashboard(range: str = "today", dev=Depends(current_device)):
        if range not in ("today", "week", "month"):
            raise HTTPException(status_code=422, detail="range must be today|week|month")
        return await svc.dashboard(range)

    @router.get("/events")
    async def list_events(kind: str = "", limit: int = 50, dev=Depends(current_device)):
        kinds = tuple(k for k in kind.split(",") if k in life.KINDS)
        if not kinds:
            raise HTTPException(status_code=422, detail="kind required")
        return {"events": await mem.latest_of_kinds(kinds, max(1, min(limit, 200)))}

    @router.post("/events")
    async def create_event(body: EventIn, dev=Depends(current_device)):
        _check_fields(body.fields)
        when_ts = life.parse_when(body.when)
        ids = await mem.add_memory([{
            "type": body.type, "summary": body.summary, "detail": body.detail, "amount": body.amount,
            "category": body.category, "when_ts": when_ts,
            "fields": _span_fields(body.fields, when_ts or life.now_tehran().timestamp(), body.end, body.minutes, body.status)}])
        return await mem.get_event(ids[0])

    @router.patch("/events/{event_id}")
    async def patch_event(event_id: int, body: EventPatch, dev=Depends(current_device)):
        _check_fields(body.fields)
        patch = body.model_dump(exclude_unset=True)
        if "when" in patch:
            patch["when_ts"] = life.parse_when(patch.pop("when"))
        end, minutes, status = patch.pop("end", None), patch.pop("minutes", None), patch.pop("status", None)
        if end or minutes or status:
            cur = await mem.get_event(event_id)
            if not cur:
                raise HTTPException(status_code=404, detail="not found")
            start_ts = patch.get("when_ts") or cur["when_ts"]
            extra = _span_fields({}, start_ts, end, minutes, status) or {}
            patch["fields"] = {**(patch.get("fields") or {}), **extra}
        ev = await mem.update_event(event_id, patch)
        if not ev:
            raise HTTPException(status_code=404, detail="not found")
        return ev

    @router.delete("/events/{event_id}")
    async def delete_event(event_id: int, dev=Depends(current_device)):
        if not await mem.delete_event(event_id):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    def _public_limit(request: Request, limit=40, window=600, bucket=""):
        """لینک‌های عمومی (پرسش‌نامه) را در برابر سوءاستفاده محدود می‌کند."""
        ip = _client_ip(request) + bucket
        q = public_hits[ip]
        now = time.time()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status_code=429, detail="too many requests")
        q.append(now)

    @router.get("/profile")
    async def get_profile(dev=Depends(current_device)):
        snap = await svc.profile_snapshot()
        snap["sections"] = list(profile.SECTIONS)
        snap["next_questions"] = [{"id": q[0], "section": q[1], "text": q[2]} for q in profile.SELF_QUESTIONS]
        return snap

    # ---------- گوشی: مخاطبین، پیامک، اقدام‌ها ----------
    def _phone():
        p = getattr(svc, "phone", None)
        if p is None:
            raise HTTPException(status_code=503, detail="phone unavailable")
        return p

    @router.put("/contacts")
    async def contacts_sync(body: ContactsSyncIn, dev=Depends(current_device)):
        items = []
        for c in body.contacts:
            nums = []
            for n in c.numbers:
                nn = norm_number(n)
                if nn and nn not in nums:
                    nums.append(nn)
            if nums:
                items.append({"key": c.key, "name": c.name.strip(), "norm": normalize_fa(c.name).strip(), "numbers": nums})
        await mem.replace_contacts(items, replace=body.replace)
        return {"stored": len(items), "total": await mem.contacts_count()}

    @router.get("/phone/status")
    async def phone_status(dev=Depends(current_device)):
        return await _phone().status()

    @router.put("/phone/settings")
    async def phone_settings(body: PhoneSettingsIn, dev=Depends(current_device)):
        return await _phone().save_settings(body.model_dump(exclude_none=True))

    @router.get("/phone/next")
    async def phone_next(wait: int = 20, dev=Depends(current_device)):
        """گوشی (سرویس پس‌زمینه) اینجا long-poll می‌کند تا اقدام تأییدشده را بگیرد؛ ۲۰۴ = فعلاً چیزی نیست."""
        ph = _phone()
        await ph.touch()
        deadline = time.time() + max(0, min(wait, 25))
        notices = getattr(svc, "notices", None)
        while True:
            n = await notices.claim() if notices else None
            if n:                                   # اعلان اپ (مثلاً «درس تازه داری»): گوشی فقط نمایش می‌دهد
                return {"id": n["id"], "kind": "notice", "to_name": n["title"], "to_number": n["target"], "text": n["text"]}
            a = await ph.claim_next()
            if a:
                return a
            if time.time() >= deadline:
                return Response(status_code=204)
            await asyncio.sleep(1.0)

    @router.post("/phone/actions/{aid}/ack")
    async def phone_ack(aid: int, body: PhoneAckIn, dev=Depends(current_device)):
        msg = await _phone().ack(aid, body.status, body.detail)
        if msg is None:
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.post("/phone/actions/{aid}/approve")
    async def phone_approve(aid: int, dev=Depends(current_device)):
        msg, a = await _phone().decide(aid, True)
        if a is None:
            raise HTTPException(status_code=404, detail="not found")
        return {"message": msg, "action": await mem.get_phone_action(aid)}

    @router.post("/phone/actions/{aid}/cancel")
    async def phone_cancel(aid: int, dev=Depends(current_device)):
        msg, a = await _phone().decide(aid, False)
        if a is None:
            raise HTTPException(status_code=404, detail="not found")
        return {"message": msg, "action": await mem.get_phone_action(aid)}

    @router.post("/calls/sync")
    async def calls_sync(body: CallsSyncIn, dev=Depends(current_device)):
        names = {}
        for c in await mem.all_contacts():
            for n in c["numbers"]:
                names[n] = c["name"]
        label = {"incoming": "تماس ورودی", "outgoing": "تماس خروجی", "missed": "تماس از دست رفته", "rejected": "تماس ردشده"}
        stored = dup = 0
        for c in body.calls:
            who = c.name or names.get(norm_number(c.number)) or c.number or "نامشخص"
            text = label[c.type] + (f" ({c.duration // 60}:{c.duration % 60:02d})" if c.duration else "")
            rid = await mem.add_inbox("call", who, text, c.ts, dedup_key=f"call:{c.id}", notified=1)
            stored, dup = (stored + 1, dup) if rid else (stored, dup + 1)
        return {"stored": stored, "duplicate": dup}

    @router.post("/calendar/sync")
    async def calendar_sync(body: CalendarSyncIn, dev=Depends(current_device)):
        events = [{"id": e.id, "title": e.title, "start": e.start, "end": e.end or e.start, "location": e.location} for e in body.events]
        await mem.kv_set("phone:calendar", json.dumps(events, ensure_ascii=False))
        return {"stored": len(events)}

    @router.post("/sms/sync")
    async def sms_sync(body: SmsSyncIn, dev=Depends(current_device)):
        """پیامک‌های گوشی (قدیمی‌ها/ارسالی‌ها) → صندوق مهرداد برای جست‌وجو؛ رمز یک‌بارمصرف هرگز ذخیره نمی‌شود."""
        names = {}
        for c in await mem.all_contacts():
            for n in c["numbers"]:
                names[n] = c["name"]
        stored = dup = skipped = 0
        for m in body.messages:
            if is_sensitive(m.body) or not m.body.strip():
                skipped += 1
                continue
            num = norm_number(m.address)
            who = names.get(num) or m.address or "نامشخص"
            text = ("[ارسالی] " if m.box == "sent" else "") + m.body.strip()[:600]
            rid = await mem.add_inbox("sms", who, text, m.ts, dedup_key=f"sms:{m.box}:{m.id}", notified=1)
            stored, dup = (stored + 1, dup) if rid else (stored, dup + 1)
        return {"stored": stored, "duplicate": dup, "skipped": skipped}

    # ---------- پروژه‌ها ----------
    def _proj():
        p = getattr(svc, "projects", None)
        if p is None:
            raise HTTPException(status_code=503, detail="projects unavailable")
        return p

    @router.get("/projects")
    async def projects_list(dev=Depends(current_device)):
        return {"projects": await _proj().listing()}

    @router.post("/projects")
    async def projects_create(body: ProjectIn, dev=Depends(current_device)):
        import re as _re
        base = _re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-") or "proj"
        existing = {p["id"] for p in await _proj().listing()}
        pid, n = base, 2
        while pid in existing:
            pid, n = f"{base}-{n}", n + 1
        await mem.upsert_project({"id": pid, "name": body.name.strip(), "subtitle": body.subtitle.strip(), "status": "فعال", "color": "#E3B35C", "icon": "🗂",
                                  "summary": "", "meta": {}, "pos": 100 + len(existing)})
        return {"id": pid}

    @router.get("/projects/doc/{doc_id}")
    async def projects_doc(doc_id: int, dev=Depends(current_device)):
        d = await mem.get_project_doc(doc_id)
        if not d:
            raise HTTPException(status_code=404, detail="not found")
        return d

    @router.patch("/projects/items/{item_id}")
    async def projects_item_patch(item_id: int, body: ProjectItemPatch, dev=Depends(current_device)):
        if not await mem.set_project_item_done(item_id, body.done):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.delete("/projects/items/{item_id}")
    async def projects_item_delete(item_id: int, dev=Depends(current_device)):
        if not await mem.delete_project_item(item_id):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.get("/projects/{pid}")
    async def projects_detail(pid: str, dev=Depends(current_device)):
        d = await _proj().detail(pid)
        if not d:
            raise HTTPException(status_code=404, detail="not found")
        return d

    @router.patch("/projects/{pid}")
    async def projects_patch(pid: str, body: ProjectPatch, dev=Depends(current_device)):
        if not await mem.get_project(pid):
            raise HTTPException(status_code=404, detail="not found")
        await mem.update_project(pid, body.model_dump(exclude_none=True))
        return await _proj().detail(pid)

    @router.post("/projects/{pid}/items")
    async def projects_item_add(pid: str, body: ProjectItemIn, dev=Depends(current_device)):
        if not await mem.get_project(pid):
            raise HTTPException(status_code=404, detail="not found")
        return {"id": await mem.add_project_item(pid, body.kind, body.text.strip(), source="app")}

    # ---------- فیش حقوقی ----------
    def _pay():
        p = getattr(svc, "payroll", None)
        if p is None:
            raise HTTPException(status_code=503, detail="payroll unavailable")
        return p

    def _month(m):
        if m is None:
            return payroll_mod.current_month()
        pm = payroll_mod.parse_month(m)
        if not pm:
            raise HTTPException(status_code=422, detail="ماه نامعتبر (مثل 1405-07)")
        return payroll_mod.month_key(*pm)

    @router.get("/payroll")
    async def payroll_state(month: str | None = None, dev=Depends(current_device)):
        return await _pay().snapshot(_month(month) if month else None)

    @router.put("/payroll/slips/{month}")
    async def payroll_save_slip(month: str, body: PayslipIn, dev=Depends(current_device)):
        key = _month(month)
        raw = {"earn": body.earn, "ded": body.ded, "work": body.work}
        if body.totals:
            raw["read_totals"] = body.totals
        slip, bad = await _pay().save_actual(key, raw, body.unit)
        snap = await _pay().snapshot(key)
        snap["mismatch"] = bad
        return snap

    @router.delete("/payroll/slips/{month}")
    async def payroll_delete_slip(month: str, dev=Depends(current_device)):
        if not await _pay().delete_slip(_month(month)):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.post("/payroll/vars")
    async def payroll_var(body: PayVarIn, dev=Depends(current_device)):
        if body.op not in payroll_mod.OPS and body.op != "days_worked":
            raise HTTPException(status_code=422, detail="نوع نامعتبر")
        key = _month(body.month)
        notes = await _pay().apply_ops([{"kind": body.op, "value": body.value, "mode": body.mode, "month": key}])
        snap = await _pay().snapshot(key)
        snap["notes"] = notes
        return snap

    @router.put("/payroll/settings")
    async def payroll_settings(body: PayrollSettingsIn, dev=Depends(current_device)):
        patch = body.model_dump(exclude_none=True)
        if "insurable" in patch:
            patch["insurable"] = [k for k in patch["insurable"] if k in payroll_mod.EARN_KEYS]
        await _pay().save_settings(patch)
        return await _pay().snapshot()

    # ---------- مربی ----------
    def _decode_images(image):
        if not image:
            return None
        dec = decode_image_b64(image)
        if not dec:
            raise HTTPException(status_code=422, detail="فقط عکس jpg/png/webp تا ۶ مگابایت")
        return [dec]

    def _coach():
        c = getattr(svc, "coach", None)
        if c is None:
            raise HTTPException(status_code=503, detail="coach unavailable")
        return c

    # ---------- مربی‌های تخصصی (کلاس‌ها) ----------
    def _rooms():
        c = getattr(svc, "coaches", None)
        if c is None:
            raise HTTPException(status_code=503, detail="coaches unavailable")
        return c

    @router.get("/coaches")
    async def coaches_list(dev=Depends(current_device)):
        return {"coaches": await _rooms().listing()}

    @router.get("/coaches/{cid}")
    async def coaches_room(cid: str, dev=Depends(current_device)):
        d = await _rooms().detail(cid)
        if d is None:
            raise HTTPException(status_code=404, detail="coach not found")
        return d

    @router.put("/coaches/{cid}/sub")
    async def coaches_sub(cid: str, body: CoachSubIn, dev=Depends(current_device)):
        sub = await _rooms().set_sub(cid, body.on, body.time)
        if sub is None:
            raise HTTPException(status_code=404, detail="coach not found")
        return sub

    @router.post("/coaches/{cid}/send")
    async def coaches_send(cid: str, dev=Depends(current_device)):
        """همین حالا درس بعدی را بساز و در تلگرام هم بفرست."""
        try:
            r = await _rooms().deliver(cid, force=True)
        except CoachRoomError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception:
            log.exception("coach send failed")
            raise HTTPException(status_code=502, detail="مربی الان جواب نداد؛ کمی بعد دوباره امتحان کن")
        if r is None:
            raise HTTPException(status_code=404, detail="coach not found")
        return {"ok": True, "title": r["lesson"]["title"]}

    @router.get("/badges")
    async def badges(dev=Depends(current_device)):
        pend = getattr(svc, "pending", None)
        rooms = getattr(svc, "coaches", None)
        return {"coach": await rooms.unread_total() if rooms else 0, "pending": len(await pend.list()) if pend else 0}

    @router.post("/coaches/{cid}/path")
    async def coaches_path(cid: str, body: CoachRoomPathIn, dev=Depends(current_device)):
        try:
            r = await _rooms().make_path(cid, body.goal)
        except CoachRoomError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception:
            log.exception("coach path failed")
            raise HTTPException(status_code=502, detail="مربی الان جواب نداد؛ کمی بعد دوباره امتحان کن")
        if r is None:
            raise HTTPException(status_code=404, detail="coach not found")
        return {"curriculum": r["curriculum"]}

    @router.post("/coaches/{cid}/lesson")
    async def coaches_lesson(cid: str, body: CoachRoomLessonIn, dev=Depends(current_device)):
        try:
            r = await _rooms().next_lesson(cid, body.topic)
        except CoachRoomError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception:
            log.exception("coach lesson failed")
            raise HTTPException(status_code=502, detail="مربی الان جواب نداد؛ کمی بعد دوباره امتحان کن")
        if r is None:
            raise HTTPException(status_code=404, detail="coach not found")
        return r["lesson"]

    @router.post("/coaches/{cid}/ask")
    async def coaches_ask(cid: str, body: CoachRoomAskIn, dev=Depends(current_device)):
        images = None
        if body.image:
            dec = decode_image_b64(body.image)
            if not dec:
                raise HTTPException(status_code=422, detail="فقط عکس jpg/png/webp تا ۶ مگابایت")
            images = [dec]
        if not body.text.strip() and not images:
            raise HTTPException(status_code=422, detail="متن یا عکس لازمه")
        try:
            reply = await _rooms().ask(cid, body.text, images)
        except CoachRoomError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception:
            log.exception("coach ask failed")
            raise HTTPException(status_code=502, detail="مربی الان جواب نداد؛ کمی بعد دوباره امتحان کن")
        if reply is None:
            raise HTTPException(status_code=404, detail="coach not found")
        return {"reply": reply, "ts": time.time()}

    @router.post("/coaches/{cid}/lessons/{n}/done")
    async def coaches_done(cid: str, n: int, body: CoachRoomDoneIn, dev=Depends(current_device)):
        if not await _rooms().set_done(cid, n, body.on):
            raise HTTPException(status_code=404, detail="lesson not found")
        return {"ok": True}

    @router.delete("/coaches/{cid}")
    async def coaches_reset(cid: str, dev=Depends(current_device)):
        if not await _rooms().reset(cid):
            raise HTTPException(status_code=404, detail="coach not found")
        return {"ok": True}

    @router.get("/coach")
    async def coach_state(dev=Depends(current_device)):
        return await _coach().state()

    @router.post("/coach/generate", status_code=202)
    async def coach_generate(force: bool = False, dev=Depends(current_device)):
        c = _coach()
        if not c.generating:
            async def run():
                try:
                    await c.generate(force=force)
                except Exception:
                    pass                     # علت در c.last_error و لاگ است
            asyncio.create_task(run())
            await asyncio.sleep(0)           # generating باید همین حالا true شود تا اپ منتظر بماند
        return {"generating": True}

    @router.post("/coach/done")
    async def coach_done(body: CoachDoneIn, dev=Depends(current_device)):
        done = await _coach().set_done(body.key, body.on)
        if done is None:
            raise HTTPException(status_code=404, detail="not found")
        return {"done": done}

    @router.post("/coach/answer")
    async def coach_answer(body: CoachAnswerIn, dev=Depends(current_device)):
        images = _decode_images(body.image)
        if not body.text.strip() and not images:
            raise HTTPException(status_code=422, detail="متن یا عکس لازمه")
        try:
            reply = await _coach().answer(body.idx, body.text, body.kind, images)
        except Exception:
            log.exception("coach answer failed")
            raise HTTPException(status_code=502, detail="brain unavailable")
        if reply is None:
            raise HTTPException(status_code=404, detail="not found")
        return {"reply": reply}

    @router.post("/coach/swap/{idx}/track")
    async def coach_track_swap(idx: int, dev=Depends(current_device)):
        r = await _coach().track_swap(idx)
        if r is None:
            raise HTTPException(status_code=404, detail="not found")
        return r

    @router.post("/coach/teach")
    async def coach_teach(body: CoachTeachIn, dev=Depends(current_device)):
        images = _decode_images(body.image)
        if len(body.topic.strip()) < 2 and not images:
            raise HTTPException(status_code=422, detail="موضوع یا عکس لازمه")
        try:
            text = await _coach().teach(body.topic, images)
        except Exception:
            log.exception("coach teach failed")
            raise HTTPException(status_code=502, detail="brain unavailable")
        return {"text": text}

    @router.post("/coach/books/recommend")
    async def coach_recommend(dev=Depends(current_device)):
        try:
            return {"added": await _coach().recommend_books()}
        except Exception:
            log.exception("coach recommend failed")
            raise HTTPException(status_code=502, detail="brain unavailable")

    @router.post("/coach/books")
    async def coach_add_book(body: CoachBookIn, dev=Depends(current_device)):
        b = await _coach().add_book(body.title, body.author)
        if not b:
            raise HTTPException(status_code=422, detail="invalid")
        return b

    @router.post("/coach/books/{book_id}/lesson")
    async def coach_book_lesson(book_id: int, dev=Depends(current_device)):
        try:
            r = await _coach().book_lesson(book_id)
        except Exception:
            log.exception("coach book lesson failed")
            raise HTTPException(status_code=502, detail="brain unavailable")
        if r is None:
            raise HTTPException(status_code=404, detail="not found")
        return r

    @router.patch("/coach/books/{book_id}")
    async def coach_book_patch(book_id: int, body: CoachBookPatch, dev=Depends(current_device)):
        if not await _coach().set_book(book_id, status=body.status):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.delete("/coach/books/{book_id}")
    async def coach_book_delete(book_id: int, dev=Depends(current_device)):
        if not await _coach().set_book(book_id, delete=True):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.post("/goals/suggest")
    async def suggest_goals(dev=Depends(current_device)):
        try:
            return {"goals": await svc.suggest_goals()}
        except Exception:
            log.exception("goal suggestion failed")
            raise HTTPException(status_code=502, detail="brain unavailable")

    @router.post("/habits")
    async def create_habit(body: HabitIn, dev=Depends(current_device)):
        return {"id": await mem.add_habit(body.good.strip(), (body.bad or "").strip() or None)}

    @router.post("/invites")
    async def create_invite(body: InviteIn, dev=Depends(current_device)):
        cfg = getattr(svc, "cfg", None)
        base = getattr(cfg, "public_url", "")
        iid, token = await mem.create_invite("wife", body.label or "همسر", days=body.days, max_uses=3)
        return {"id": iid, "url": f"{base}/who/{token}", "days": body.days}

    @router.get("/invites")
    async def list_invites(dev=Depends(current_device)):
        return {"invites": await mem.list_invites()}

    @router.delete("/invites/{invite_id}")
    async def revoke_invite(invite_id: int, dev=Depends(current_device)):
        if not await mem.revoke_invite(invite_id):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.get("/invite/{token}")
    async def invite_info(token: str, request: Request):
        _public_limit(request)
        inv = await mem.get_invite(token)
        if not inv:
            raise HTTPException(status_code=404, detail="invalid or expired")
        return {"valid": True, "kind": inv["kind"],
                "questions": [{"id": q[0], "section": q[1], "text": q[2]} for q in profile.WIFE_QUESTIONS]}

    @router.post("/invite/{token}")
    async def invite_submit(token: str, body: WifeIn, request: Request):
        _public_limit(request, limit=20)
        try:
            n = await save_wife_answers(mem, svc, token, body.answers, body.who)
        except LookupError:
            raise HTTPException(status_code=404, detail="invalid or expired")
        except ValueError:
            raise HTTPException(status_code=422, detail="no answers")
        return {"saved": n}

    @router.put("/invite/{token}/answer")
    async def invite_answer(token: str, body: WifeOneIn, request: Request):
        _public_limit(request, limit=300, bucket=":answer")
        try:
            n = await save_one_wife_answer(mem, token, body.qid, body.text, body.who)
        except LookupError:
            raise HTTPException(status_code=404, detail="invalid or expired")
        except ValueError:
            raise HTTPException(status_code=422, detail="bad question")
        return {"saved": n}

    @router.post("/invite/{token}/done")
    async def invite_done(token: str, request: Request):
        """همسر «تموم شد» را زد: یک نوبت مصرف می‌شود و مالک خبردار می‌شود (جواب‌ها قبلاً خودکار ذخیره شده‌اند)."""
        _public_limit(request, limit=30, bucket=":done")
        inv = await mem.get_invite(token)
        if not inv:
            raise HTTPException(status_code=404, detail="invalid or expired")
        n = len([e for e in await mem.latest_of_kinds(("profile",), 300) if (e.get("fields") or {}).get("source") == "همسر"])
        await mem.use_invite(inv["id"])
        await svc.notify_owner(f"✅ همسرت جواب‌هاش رو فرستاد ({life.fa(n)} سؤال تا الان). توی اپ ← هدف‌ها ← پروفایل ببین (هر کدوم رو خواستی می‌تونی پاک کنی).")
        return {"saved": n}

    @router.get("/novatunnel")
    async def get_novatunnel(dev=Depends(current_device)):
        cfg = getattr(svc, "cfg", None)
        return await novatunnel.snapshot(getattr(cfg, "novatunnel_db_url", ""))

    @router.get("/finance")
    async def get_finance(dev=Depends(current_device)):
        return await svc.finance_snapshot()

    @router.post("/accounts")
    async def create_account(body: AccountIn, dev=Depends(current_device)):
        aid = await mem.add_account(body.name, body.kind, body.balance, body.note)
        return {"id": aid}

    @router.patch("/accounts/{account_id}")
    async def patch_account(account_id: int, body: AccountPatch, dev=Depends(current_device)):
        acc = await mem.update_account(account_id, body.model_dump(exclude_unset=True))
        if not acc:
            raise HTTPException(status_code=404, detail="not found")
        return acc

    @router.delete("/accounts/{account_id}")
    async def remove_account(account_id: int, dev=Depends(current_device)):
        if not await mem.delete_account(account_id):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.post("/debts")
    async def create_debt(body: DebtIn, dev=Depends(current_device)):
        d = body.model_dump()
        d["remaining"] = d["remaining"] if d["remaining"] is not None else d["total"]
        if not d.get("next_due") and d.get("due_day"):
            d["next_due"] = finance.next_due_from_day(d["due_day"], life.now_tehran().date()).isoformat()
        _check_date(d.get("next_due"))
        return {"id": await mem.add_debt(d)}

    @router.patch("/debts/{debt_id}")
    async def patch_debt(debt_id: int, body: DebtPatch, dev=Depends(current_device)):
        patch = body.model_dump(exclude_unset=True)
        _check_date(patch.get("next_due"))
        d = await mem.update_debt(debt_id, patch)
        if not d:
            raise HTTPException(status_code=404, detail="not found")
        return d

    @router.delete("/debts/{debt_id}")
    async def remove_debt(debt_id: int, dev=Depends(current_device)):
        if not await mem.delete_debt(debt_id):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.post("/debts/{debt_id}/pay")
    async def pay_debt(debt_id: int, body: PayIn, dev=Depends(current_device)):
        updated = await svc.pay_debt(debt_id, body.amount, body.record_expense)
        if not updated:
            raise HTTPException(status_code=404, detail="not found")
        return updated

    # ---------- تأیید قبل از ثبت خرج/درآمد ----------
    def _pending():
        p = getattr(svc, "pending", None)
        if p is None:
            raise HTTPException(status_code=503, detail="pending unavailable")
        return p

    @router.get("/pending")
    async def pending_list(dev=Depends(current_device)):
        p = _pending()
        return {"items": await p.list(), "confirm": await p.enabled()}

    @router.put("/pending/settings")
    async def pending_settings(body: PendingSettingsIn, dev=Depends(current_device)):
        await _pending().set_enabled(body.confirm)
        return {"confirm": body.confirm}

    @router.post("/pending/{pid}/confirm")
    async def pending_confirm(pid: int, body: PendingEditIn, dev=Depends(current_device)):
        p = _pending()
        line, item = await p.confirm(pid, body.model_dump(exclude_none=True))
        if line is None:
            raise HTTPException(status_code=404 if item is None else 409, detail="not found" if item is None else "already decided")
        return {"message": line}

    @router.post("/pending/{pid}/reject")
    async def pending_reject(pid: int, dev=Depends(current_device)):
        line, item = await _pending().reject(pid)
        if line is None:
            raise HTTPException(status_code=404 if item is None else 409, detail="not found" if item is None else "already decided")
        return {"message": line}

    @router.post("/chat/image")
    async def chat_image(body: ChatImageIn, dev=Depends(current_device)):
        dec = decode_image_b64(body.image)
        if not dec:
            raise HTTPException(status_code=422, detail="فقط عکس jpg/png/webp تا ۶ مگابایت")
        pend = getattr(svc, "pending", None)
        before = await pend.max_id() if pend else 0
        try:
            reply = await svc.chat(body.text.strip() or "این عکس رو ببین؛ اگه فیش پرداخت، رسید یا چیز قابل‌ثبته ثبتش کن و بگو چی خوندی.", images=[dec])
        except Exception:
            log.exception("image chat failed")
            raise HTTPException(status_code=502, detail="brain unavailable")
        return {"reply": reply, "pending": await pend.since(before) if pend else []}

    @router.get("/history")
    async def history(limit: int = 50, dev=Depends(current_device)):
        return {"messages": await mem.recent_messages_ts(max(1, min(limit, 200)))}

    @router.post("/ingest")
    async def ingest(body: IngestIn, dev=Depends(current_device)):
        stored = duplicate = skipped = parsed_n = 0
        lines, waiting = [], []
        for it in body.items:
            if is_sensitive(it.text):       # دفاع در عمق: اپ هم فیلتر می‌کند
                skipped += 1
                continue
            if it.app:                      # اعلان پیام‌رسان: ذخیره برای جست‌وجو/پاسخ؛ هرگز تراکنش بانکی حدس زده نمی‌شود
                key = f"n:{it.conv}:{hashlib.sha256(it.text.encode()).hexdigest()[:12]}:{int(it.ts // 600)}"
                inbox_id = await mem.add_inbox(it.kind, f"{it.app} — {it.title or it.source}".strip(" —"), it.text, it.ts, dedup_key=key, notified=1)
                if inbox_id is None:
                    duplicate += 1
                    continue
                stored += 1
                await mem.kv_set("phone:last_notif", str(time.time()))
                if it.conv:
                    await mem.touch_conv(it.conv, it.app, it.title or it.source or it.conv, it.ts)
                continue
            inbox_id = await mem.add_inbox(it.kind, it.source, it.text, it.ts)
            if inbox_id is None:
                duplicate += 1
                continue
            stored += 1
            parsed = parse_bank_text(it.text)
            if parsed:
                entry = memory_entry(parsed, it.source, it.text)
                pend = getattr(svc, "pending", None)
                if pend is not None and await pend.enabled():          # فقط پیشنهاد؛ بعد از تأیید صاحب ثبت می‌شود
                    made = await pend.add_many([entry], origin="sms" if it.kind == "sms" else "notification", source=it.source or "", inbox_id=inbox_id)
                    waiting.extend(made)
                    parsed_n += 1
                    continue
                await mem.add_memory([entry])
                await mem.mark_inbox_parsed(inbox_id)
                parsed_n += 1
                lines.append(("💸 " if parsed["type"] == "expense" else "💰 ") + entry["summary"].split(" (")[0])
        if lines:
            await svc.notify_owner("ثبت شد:\n" + "\n".join(lines[:5]))
        if waiting:
            owner = await mem.get_owner()
            if owner:
                await svc.pending.offer(owner, waiting)
        res = {"stored": stored, "duplicate": duplicate, "skipped": skipped, "parsed": parsed_n}
        if waiting:
            res["pending"] = len(waiting)
        return res


    # ---------- فروش و پیگیری (CRM) ----------
    def _crm():
        c = getattr(svc, "crm", None)
        if c is None:
            raise HTTPException(status_code=503, detail="crm unavailable")
        return c

    async def _cust(cid):
        c = await _crm().get_customer(cid)
        if not c:
            raise HTTPException(status_code=404, detail="customer not found")
        return c

    @router.get("/crm")
    async def crm_dashboard(dev=Depends(current_device)):
        return await _crm().dashboard()

    @router.get("/crm/customers")
    async def crm_customers(q: str = "", status: str = "", dev=Depends(current_device)):
        return {"customers": await _crm().list_customers(q, status or None)}

    @router.post("/crm/customers")
    async def crm_customer_add(body: CrmCustomerIn, dev=Depends(current_device)):
        crm = _crm()
        data = body.model_dump(exclude_none=True)
        st, found = await crm.find_customer(body.name)
        if st == "one" and found[0]["norm"] == normalize_fa(body.name).strip():
            raise HTTPException(status_code=409, detail="این مشتری از قبل هست")
        if not data.get("phone"):
            ph = await crm._phone_from_contacts(body.name)
            if ph:
                data["phone"] = ph
        c = await crm.add_customer({**data, "source": data.get("source") or "اپ"})
        await crm.add_event(c["id"], "note", "مشتری/سرنخ ثبت شد")
        return c

    @router.get("/crm/customers/{cid}")
    async def crm_customer_detail(cid: int, dev=Depends(current_device)):
        crm = _crm()
        c = await _cust(cid)
        return {"customer": c, "deals": await crm.list_deals(cid=cid), "followups": await crm.list_followups(cid=cid),
                "done_followups": await crm.list_followups(done=True, cid=cid, limit=10), "events": await crm.events(cid)}

    @router.patch("/crm/customers/{cid}")
    async def crm_customer_patch(cid: int, body: CrmCustomerPatch, dev=Depends(current_device)):
        await _cust(cid)
        return await _crm().update_customer(cid, body.model_dump(exclude_none=True))

    @router.delete("/crm/customers/{cid}")
    async def crm_customer_delete(cid: int, dev=Depends(current_device)):
        if not await _crm().delete_customer(cid):
            raise HTTPException(status_code=404, detail="customer not found")
        return {"ok": True}

    @router.post("/crm/customers/{cid}/notes")
    async def crm_customer_note(cid: int, body: CrmNoteIn, dev=Depends(current_device)):
        await _cust(cid)
        await _crm().add_event(cid, "note", body.text)
        return {"ok": True}

    @router.post("/crm/customers/{cid}/contact")
    async def crm_customer_contact(cid: int, body: CrmContactIn, dev=Depends(current_device)):
        """دکمهٔ «زنگ بزن / پیامک» در کارت مشتری: اقدام گوشی می‌سازد و برای تأیید یک‌لمسی می‌گذارد (مستقیم نمی‌فرستد)."""
        c = await _cust(cid)
        to = c["phone"] or c["name"]
        notes = await _phone().create(body.kind, to, "" if body.kind == "call" else (body.text or ""), ("زنگ بزن" if body.kind == "call" else "پیامک بزن") + " به " + c["name"])
        await _crm().add_event(cid, body.kind, ("تماس" if body.kind == "call" else "پیامک") + " (درخواست از اپ)" + (": " + body.text if body.text and body.kind == "sms" else ""))
        return {"message": "\n".join(notes)}

    @router.get("/crm/deals")
    async def crm_deals(open: bool = False, dev=Depends(current_device)):
        return {"deals": await _crm().list_deals(open_only=open)}

    @router.post("/crm/deals")
    async def crm_deal_add(body: CrmDealIn, dev=Depends(current_device)):
        crm = _crm()
        c = await _cust(body.customer_id)
        d = await crm.add_deal(c["id"], body.title, body.value, body.stage, body.expected_close or "")
        await crm.add_event(c["id"], "deal", "معامله «" + d["title"] + "» ساخته شد", d["id"])
        return d

    @router.patch("/crm/deals/{did}")
    async def crm_deal_patch(did: int, body: CrmDealPatch, dev=Depends(current_device)):
        crm = _crm()
        old = await crm.get_deal(did)
        if not old:
            raise HTTPException(status_code=404, detail="deal not found")
        d = await crm.update_deal(did, body.model_dump(exclude_none=True, exclude={"paid"}))
        if body.stage == "won" and old["stage"] != "won" and body.paid and d["value"]:
            c = await crm.get_customer(d["customer_id"])
            await mem.add_memory([{"type": "income", "summary": "فروش به " + c["name"] + ": " + d["title"], "detail": None, "amount": d["value"],
                                   "category": "فروش", "when_ts": time.time(), "fields": None}])
            await crm.add_event(d["customer_id"], "payment", "دریافت " + tm(d["value"]))
        return d

    @router.delete("/crm/deals/{did}")
    async def crm_deal_delete(did: int, dev=Depends(current_device)):
        if not await _crm().delete_deal(did):
            raise HTTPException(status_code=404, detail="deal not found")
        return {"ok": True}

    @router.get("/crm/followups")
    async def crm_followups(done: bool = False, dev=Depends(current_device)):
        return {"followups": await _crm().list_followups(done=done, limit=100 if done else 200)}

    @router.post("/crm/followups")
    async def crm_followup_add(body: CrmFollowupIn, dev=Depends(current_device)):
        crm = _crm()
        await _cust(body.customer_id)
        due = parse_due(body.due)
        if not due:
            raise HTTPException(status_code=422, detail="تاریخ نامعتبر")
        f = await crm.add_followup(body.customer_id, due, body.note or "", body.channel or "", body.deal_id)
        if not f:
            raise HTTPException(status_code=409, detail="این پیگیری از قبل هست")
        return f

    @router.patch("/crm/followups/{fid}")
    async def crm_followup_patch(fid: int, body: CrmFollowupPatch, dev=Depends(current_device)):
        crm = _crm()
        f = await crm.get_followup(fid)
        if not f:
            raise HTTPException(status_code=404, detail="followup not found")
        if body.due:
            due = parse_due(body.due)
            if not due:
                raise HTTPException(status_code=422, detail="تاریخ نامعتبر")
            await crm.move_followup(fid, due)
        if body.done is not None:
            await crm.finish_followup(fid, body.done)
        return await crm.get_followup(fid)

    @router.delete("/crm/followups/{fid}")
    async def crm_followup_delete(fid: int, dev=Depends(current_device)):
        if not await _crm().delete_followup(fid):
            raise HTTPException(status_code=404, detail="followup not found")
        return {"ok": True}

    return router
