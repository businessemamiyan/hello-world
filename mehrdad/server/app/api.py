"""API اپ اندروید مهرداد — جفت‌سازی با کد یک‌بارمصرف، چت، تاریخچه، و دریافت پیامک/اعلان مالی.

احراز هویت: توکن اختصاصی هر دستگاه (Bearer)؛ فقط هش آن در دیتابیس است و با /unpair در تلگرام باطل می‌شود.
هیچ رمز ثابتی در .env یا داخل اپ نیست. /api/pair با محدودیت تعداد تلاش ناموفق محافظت می‌شود.
"""
import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import life
from .ingest import is_sensitive, memory_entry, parse_bank_text

log = logging.getLogger("api")

MAX_PAIR_FAILS = 5
PAIR_WINDOW = 600


class PairIn(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field(default="گوشی", max_length=60)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


KIND_PATTERN = "^(" + "|".join(life.KINDS) + ")$"


class EventIn(BaseModel):
    type: str = Field(pattern=KIND_PATTERN)
    summary: str = Field(min_length=1, max_length=300)
    detail: str | None = Field(default=None, max_length=1000)
    amount: float | None = Field(default=None, ge=0, le=1e12)
    category: str | None = Field(default=None, max_length=60)
    when: str | None = Field(default=None, max_length=20)
    fields: dict | None = None


class EventPatch(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=300)
    detail: str | None = Field(default=None, max_length=1000)
    amount: float | None = Field(default=None, ge=0, le=1e12)
    category: str | None = Field(default=None, max_length=60)
    when: str | None = Field(default=None, max_length=20)
    fields: dict | None = None


def _check_fields(fields):
    if fields is not None and len(str(fields)) > 2000:
        raise HTTPException(status_code=422, detail="fields too large")


class IngestItem(BaseModel):
    kind: str = Field(pattern="^(sms|notification)$")
    source: str = Field(default="", max_length=120)
    text: str = Field(min_length=1, max_length=2000)
    ts: float


class IngestIn(BaseModel):
    items: list[IngestItem] = Field(max_length=50)


def _client_ip(request: Request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def create_router(mem, svc):
    """svc: شیئی با `async chat(text) -> reply` و `async notify_owner(text)` (همان Bot)."""
    router = APIRouter(prefix="/api")
    fails = defaultdict(deque)

    async def current_device(authorization: str = Header(default="")):
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        dev = await mem.device_for_token(token)
        if not dev:
            raise HTTPException(status_code=401, detail="invalid token")
        return dev

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
        await svc.notify_owner(f"📱 دستگاه «{body.name}» به مهرداد وصل شد (#{device_id}). اگر خودت نبودی: /unpair {device_id}")
        return {"token": token, "device_id": device_id}

    @router.get("/me")
    async def me(dev=Depends(current_device)):
        return {"ok": True, "device": dev}

    @router.post("/chat")
    async def chat(body: ChatIn, dev=Depends(current_device)):
        reply = await svc.chat(body.text)
        return {"reply": reply, "ts": time.time()}

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
        ids = await mem.add_memory([{
            "type": body.type, "summary": body.summary, "detail": body.detail, "amount": body.amount,
            "category": body.category, "fields": body.fields, "when_ts": life.parse_when(body.when)}])
        return await mem.get_event(ids[0])

    @router.patch("/events/{event_id}")
    async def patch_event(event_id: int, body: EventPatch, dev=Depends(current_device)):
        _check_fields(body.fields)
        patch = body.model_dump(exclude_unset=True)
        if "when" in patch:
            patch["when_ts"] = life.parse_when(patch.pop("when"))
        ev = await mem.update_event(event_id, patch)
        if not ev:
            raise HTTPException(status_code=404, detail="not found")
        return ev

    @router.delete("/events/{event_id}")
    async def delete_event(event_id: int, dev=Depends(current_device)):
        if not await mem.delete_event(event_id):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @router.get("/history")
    async def history(limit: int = 50, dev=Depends(current_device)):
        return {"messages": await mem.recent_messages_ts(max(1, min(limit, 200)))}

    @router.post("/ingest")
    async def ingest(body: IngestIn, dev=Depends(current_device)):
        stored = duplicate = skipped = parsed_n = 0
        lines = []
        for it in body.items:
            if is_sensitive(it.text):       # دفاع در عمق: اپ هم فیلتر می‌کند
                skipped += 1
                continue
            inbox_id = await mem.add_inbox(it.kind, it.source, it.text, it.ts)
            if inbox_id is None:
                duplicate += 1
                continue
            stored += 1
            parsed = parse_bank_text(it.text)
            if parsed:
                entry = memory_entry(parsed, it.source, it.text)
                await mem.add_memory([entry])
                await mem.mark_inbox_parsed(inbox_id)
                parsed_n += 1
                lines.append(("💸 " if parsed["type"] == "expense" else "💰 ") + entry["summary"].split(" (")[0])
        if lines:
            await svc.notify_owner("ثبت شد:\n" + "\n".join(lines[:5]))
        return {"stored": stored, "duplicate": duplicate, "skipped": skipped, "parsed": parsed_n}

    return router
