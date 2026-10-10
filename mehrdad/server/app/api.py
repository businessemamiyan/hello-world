"""API اپ اندروید مهراد — جفت‌سازی با کد یک‌بارمصرف، چت، تاریخچه، و دریافت پیامک/اعلان مالی.

احراز هویت: توکن اختصاصی هر دستگاه (Bearer)؛ فقط هش آن در دیتابیس است و با /unpair در تلگرام باطل می‌شود.
هیچ رمز ثابتی در .env یا داخل اپ نیست. /api/pair با محدودیت تعداد تلاش ناموفق محافظت می‌شود.
"""
import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import finance, life, novatunnel, profile
from .ingest import is_sensitive, memory_entry, parse_bank_text
from .media import decode_image_b64

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


class CoachDoneIn(BaseModel):
    key: str = Field(min_length=1, max_length=12)
    on: bool = True


class CoachAnswerIn(BaseModel):
    idx: int = Field(ge=0, le=5)
    text: str = Field(min_length=1, max_length=2000)


class CoachTeachIn(BaseModel):
    topic: str = Field(min_length=2, max_length=300)


class CoachBookIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    author: str = Field(default="", max_length=80)


class CoachBookPatch(BaseModel):
    status: str = Field(pattern="^(suggested|reading|done)$")


class InviteIn(BaseModel):
    label: str | None = Field(default=None, max_length=40)
    days: int = Field(default=14, ge=1, le=60)


class WifeIn(BaseModel):
    answers: dict[str, str] = Field(max_length=20)
    who: str | None = Field(default=None, max_length=40)


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
        await svc.notify_owner(f"📱 دستگاه «{body.name}» به مهراد وصل شد (#{device_id}). اگر خودت نبودی: /unpair {device_id}")
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

    def _public_limit(request: Request, limit=40, window=600):
        """لینک‌های عمومی (پرسش‌نامه) را در برابر سوءاستفاده محدود می‌کند."""
        ip = _client_ip(request)
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

    # ---------- مربی ----------
    def _coach():
        c = getattr(svc, "coach", None)
        if c is None:
            raise HTTPException(status_code=503, detail="coach unavailable")
        return c

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
        try:
            reply = await _coach().answer(body.idx, body.text)
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
        try:
            text = await _coach().teach(body.topic)
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
        inv = await mem.get_invite(token)
        if not inv:
            raise HTTPException(status_code=404, detail="invalid or expired")
        qmap = {q[0]: q for q in profile.WIFE_QUESTIONS}
        clean = {}
        for qid, text in body.answers.items():
            text = (text or "").strip()
            if qid in qmap and text:
                clean[qid] = text[:1500]
        if not clean:
            raise HTTPException(status_code=422, detail="no answers")
        # ارسال دوباره‌ی همان سؤال، پاسخ قبلی را جایگزین می‌کند (نه تکرار)
        for old in await mem.latest_of_kinds(("profile",), 300):
            f = old.get("fields") or {}
            if f.get("source") == "همسر" and f.get("qid") in clean:
                await mem.delete_event(old["id"])
        who = (body.who or "").strip()[:40]
        await mem.add_memory([{
            "type": "profile", "summary": text if len(text) <= 280 else text[:277] + "…", "detail": text,
            "category": qmap[qid][1], "fields": {"source": "همسر", "qid": qid, "question": qmap[qid][2], **({"who": who} if who else {})}}
            for qid, text in clean.items()])
        await mem.use_invite(inv["id"])
        await svc.notify_owner(f"✅ همسرت به {life.fa(len(clean))} سؤال دربارهٔ تو جواب داد. در اپ ← هدف‌ها ← پروفایل ببین (و هر چه خواستی حذف کن).")
        return {"saved": len(clean)}

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

    @router.post("/chat/image")
    async def chat_image(body: ChatImageIn, dev=Depends(current_device)):
        dec = decode_image_b64(body.image)
        if not dec:
            raise HTTPException(status_code=422, detail="فقط عکس jpg/png/webp تا ۶ مگابایت")
        try:
            reply = await svc.chat(body.text.strip() or "این عکس را ببین؛ اگر فیش پرداخت، رسید یا چیز قابل‌ثبت است ثبتش کن و بگو چه خواندی.", images=[dec])
        except Exception:
            log.exception("image chat failed")
            raise HTTPException(status_code=502, detail="brain unavailable")
        return {"reply": reply}

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
