import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest
from fastapi.testclient import TestClient

from app import projects as pj
from app.bot import Bot
from app.brain import Brain, _parse_projects
from app.config import Config
from app.memory import Memory
from app.web import create_app

MD = """# عنوان کل

متن مقدمه

## ۱. معماری
فلسک و دیتابیس SQL Server روی پورت ۵۰۵۰

### زیرساخت
یک سرور و یک تونل

## ۲. باگ‌ها
باگ بارکد تکراری در لعاب‌زنی رفع شد

## ۳. بزرگ
""" + "\n\n".join(f"پاراگراف شمارهٔ {i} " + "الف " * 400 for i in range(10))


def test_chunk_markdown_splits_by_headings_and_size():
    ch = pj.chunk_markdown(MD, max_chars=3000)
    titles = [t for t, _ in ch]
    assert titles[0] == "مقدمه" and "۱. معماری" in titles and "۱. معماری — زیرساخت" in titles and "۲. باگ‌ها" in titles
    big = [t for t in titles if t.startswith("۳. بزرگ")]
    assert len(big) >= 2 and all(len(b) <= 3600 for _, b in ch)                        # بخش بزرگ تکه‌تکه شد
    assert pj.chunk_markdown("", 100) == []


def test_match_project_by_id_name_or_unique_fragment():
    ps = [{"id": "vq-erp", "name": "VQ ERP", "subtitle": "جایگزین سپیا"}, {"id": "nova", "name": "NovaTunnel + Vista Edge", "subtitle": "فروش VPN"},
          {"id": "vq-factory", "name": "VQ Factory", "subtitle": "تحلیل تولید"}]
    assert pj.match_project(ps, "vq-erp")["id"] == "vq-erp" and pj.match_project(ps, "نواتانل") is None
    assert pj.match_project(ps, "novatunnel")["id"] == "nova" and pj.match_project(ps, "Vista Edge")["id"] == "nova"
    assert pj.match_project(ps, "vq") is None                                              # مبهم: حدس نمی‌زند
    assert pj.match_project(ps, "vq factory")["id"] == "vq-factory" and pj.match_project(ps, "") is None and pj.match_project(ps, "ERP")["id"] == "vq-erp"


def write_seed(tmp_path):
    d = tmp_path / "seed"
    d.mkdir()
    (d / "alef.json").write_text(json.dumps({"id": "alef", "name": "پروژهٔ الف", "subtitle": "آزمایشی", "status": "فعال", "icon": "🏭", "pos": 1,
                                           "summary": "یک پروژهٔ نمونه برای تست", "kpis": [["خط کد", "۱۰۰۰"], ["مشتری", "۳"]],
                                           "tasks": ["وصل کردن چاپگر", "نوشتن گزارش هفتگی"], "notes": ["شروع شد"], "doc": "alef.md"}, ensure_ascii=False), encoding="utf-8")
    (d / "alef.md").write_text(MD, encoding="utf-8")
    (d / "be.json").write_text(json.dumps({"id": "be", "name": "پروژهٔ ب", "summary": "بدون مستند", "pos": 2}, ensure_ascii=False), encoding="utf-8")
    return str(d)


@pytest.mark.asyncio
async def test_import_is_idempotent_and_keeps_user_state(tmp_path):
    mem = Memory(str(tmp_path / "p.db"))
    p = pj.Projects(mem)
    out = await p.import_dir(write_seed(tmp_path))
    assert out[0][0] == "alef" and out[0][1] >= 4 and out[1] == ("be", 0)
    d = await p.detail("alef")
    assert d["name"] == "پروژهٔ الف" and d["kpis"] == [["خط کد", "۱۰۰۰"], ["مشتری", "۳"]] and len(d["tasks"]) == 2 and len(d["notes"]) == 1 and len(d["docs"]) >= 4
    await mem.set_project_item_done(d["tasks"][0]["id"], True)
    await mem.update_project("alef", {"status": "متوقف"})
    await p.import_dir(str(tmp_path / "seed"))                                           # دوباره ورود
    d2 = await p.detail("alef")
    assert len(d2["tasks"]) == 2 and len(d2["notes"]) == 1 and len(d2["docs"]) == len(d["docs"])      # تکراری نشد
    assert d2["status"] == "متوقف" and [t["done"] for t in d2["tasks"]].count(True) == 1               # دست‌کاری کاربر دست‌نخورده
    assert await p.detail("nope") is None


@pytest.mark.asyncio
async def test_docs_are_searchable_through_search_memory(tmp_path):
    mem = Memory(str(tmp_path / "s.db"))
    await pj.Projects(mem).import_dir(write_seed(tmp_path))
    await mem.add_memory([{"type": "note", "summary": "یادداشت معمولی دربارهٔ لعاب"}])
    hits = await mem.search_memory("باگ بارکد تکراری لعاب‌زنی")
    kinds = [h["type"] for h in hits]
    assert "note" in kinds and "project" in kinds
    proj = next(h for h in hits if h["type"] == "project")
    assert proj["summary"].startswith("[پروژه پروژهٔ الف]") and "بارکد تکراری" in proj["detail"]
    assert [h for h in await mem.search_memory("چیزی کاملاً بی‌ربط زرافه") if h["type"] == "project"] == []


@pytest.mark.asyncio
async def test_apply_ops_note_task_done_status_and_errors(tmp_path):
    mem = Memory(str(tmp_path / "o.db"))
    p = pj.Projects(mem)
    await p.import_dir(write_seed(tmp_path))
    notes = await p.apply_ops([
        {"op": "note", "project": "پروژهٔ الف", "text": "امروز گزارش درجه‌بندی رو تحویل دادم"},
        {"op": "task", "project": "alef", "text": "تست روی سرور"},
        {"op": "done", "project": "alef", "text": "چاپگر"},
        {"op": "done", "project": "alef", "text": "کاری که نیست"},
        {"op": "status", "project": "alef", "status": "در انتظار تأیید"},
        {"op": "note", "project": "ناشناخته", "text": "x"}])
    assert "یادداشت ثبت شد" in notes[0] and "کار تازه اضافه شد: تست روی سرور" in notes[1] and "انجام شد ✓ وصل کردن چاپگر" in notes[2]
    assert "به‌عنوان یادداشت" in notes[3] and "وضعیت شد «در انتظار تأیید»" in notes[4] and notes[5].startswith("⚠️ پروژهٔ «ناشناخته»") and "پروژهٔ الف" in notes[5]
    d = await p.detail("alef")
    assert d["status"] == "در انتظار تأیید" and {t["text"]: t["done"] for t in d["tasks"]}["وصل کردن چاپگر"] is True
    assert any("گزارش درجه‌بندی" in n["text"] for n in d["notes"]) and any(n["text"].startswith("انجام شد: کاری که نیست") for n in d["notes"])
    await p.import_dir(str(tmp_path / "seed"))
    await mem.add_project_item("alef", "task", "گزارش یک")
    await mem.add_project_item("alef", "task", "گزارش دو")
    amb = await p.apply_ops([{"op": "done", "project": "alef", "text": "گزارش"}])
    assert "چند کار شبیه" in amb[0]


@pytest.mark.asyncio
async def test_prompt_and_text_summaries(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    p = pj.Projects(mem)
    assert await p.prompt() == "" and "هنوز پروژه‌ای" in await p.text()
    await p.import_dir(write_seed(tmp_path))
    pr = await p.prompt()
    assert "پروژهٔ الف (id=alef) [فعال]" in pr and "وصل کردن چاپگر" in pr and "آخرین یادداشت: شروع شد" in pr and "project_op" in pr
    tx = await p.text()
    assert "🏭 پروژهٔ الف — فعال" in tx and "باز:" in tx and "اپ ← هدف‌ها ← پروژه‌ها" in tx


def test_parse_projects_validates_model_output():
    ops = _parse_projects({"projects": [{"op": "note", "project": "alef", "text": "پیشرفت"}, {"op": "task", "project": "alef", "text": ""},
                                        {"op": "status", "project": "alef", "status": "متوقف"}, {"op": "bogus", "project": "alef", "text": "x"},
                                        {"op": "done", "project": "", "text": "x"}, "str", {"op": "status", "project": "alef"}]})
    assert [o["project_op"]["op"] for o in ops] == ["note", "status"] and ops[1]["project_op"]["status"] == "متوقف"
    assert len(_parse_projects({"projects": [{"op": "note", "project": "a", "text": str(i)} for i in range(20)]})) == 5 and _parse_projects({}) == []


class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, *a, **k):
        pass


def _brain(payload):
    def handler(request):
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]})

    b = Brain("k")
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b


@pytest.mark.asyncio
async def test_chat_logs_project_progress_and_context_includes_projects(tmp_path):
    mem = Memory(str(tmp_path / "c.db"))
    tg = FakeTG()
    bot = Bot(mem, tg, _brain({"reply": "عالیه", "memory": [], "projects": [{"op": "note", "project": "alef", "text": "ایندکس‌ها اجرا شد"}]}),
              Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    await bot.projects.import_dir(write_seed(tmp_path))
    reply = await bot.chat("ایندکس‌های پروژه الف رو اجرا کردم")
    assert "🗂 «پروژهٔ الف»: یادداشت ثبت شد" in reply
    assert "ایندکس‌ها اجرا شد" in (await bot.context_prompt()) and "پروژه‌های کاربر" in (await bot.context_prompt())
    await mem.set_owner(7)
    await bot.handle_message({"chat": {"id": 7}, "text": "/projects"})
    assert "پروژهٔ الف" in tg.sent[-1] and "ایندکس‌ها اجرا شد" in tg.sent[-1]


@pytest.fixture
def api(tmp_path):
    mem = Memory(str(tmp_path / "a.db"))
    bot = Bot(mem, FakeTG(), _brain({"reply": "ok", "memory": []}), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    loop = asyncio.new_event_loop()
    loop.run_until_complete(bot.projects.import_dir(write_seed(tmp_path)))
    code = loop.run_until_complete(mem.create_pair_code())
    c = TestClient(create_app(mem, time.time(), bot))
    token = c.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return c, {"Authorization": f"Bearer {token}"}


def test_projects_api(api):
    c, h = api
    assert c.get("/api/projects").status_code == 401
    ps = c.get("/api/projects", headers=h).json()["projects"]
    assert [p["id"] for p in ps] == ["alef", "be"] and ps[0]["open_count"] == 2 and ps[0]["docs_count"] >= 4 and ps[0]["kpis"][0] == ["خط کد", "۱۰۰۰"]
    d = c.get("/api/projects/alef", headers=h).json()
    assert d["name"] == "پروژهٔ الف" and len(d["tasks"]) == 2 and d["docs"][0]["section"]
    doc = c.get(f"/api/projects/doc/{d['docs'][1]['id']}", headers=h).json()
    assert doc["project"] == "پروژهٔ الف" and doc["body"]
    assert c.get("/api/projects/doc/999999", headers=h).status_code == 404 and c.get("/api/projects/nope", headers=h).status_code == 404
    new = c.post("/api/projects/alef/items", json={"kind": "task", "text": "کار تازه از اپ"}, headers=h).json()["id"]
    assert c.post("/api/projects/alef/items", json={"kind": "weird", "text": "x"}, headers=h).status_code == 422
    assert c.post("/api/projects/nope/items", json={"kind": "note", "text": "x"}, headers=h).status_code == 404
    assert c.patch(f"/api/projects/items/{new}", json={"done": True}, headers=h).status_code == 200
    assert [t for t in c.get("/api/projects/alef", headers=h).json()["tasks"] if t["id"] == new][0]["done"] is True
    assert c.patch("/api/projects/items/99999", json={"done": True}, headers=h).status_code == 404
    assert c.delete(f"/api/projects/items/{new}", headers=h).status_code == 200 and c.delete(f"/api/projects/items/{new}", headers=h).status_code == 404
    assert c.patch("/api/projects/alef", json={"status": "متوقف"}, headers=h).json()["status"] == "متوقف"
    assert c.patch("/api/projects/nope", json={"status": "x"}, headers=h).status_code == 404
    pid = c.post("/api/projects", json={"name": "My New Project", "subtitle": "x"}, headers=h).json()["id"]
    assert pid == "my-new-project" and c.post("/api/projects", json={"name": "My New Project"}, headers=h).json()["id"] == "my-new-project-2"
