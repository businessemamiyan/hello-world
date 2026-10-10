import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.bot import Bot
from app.config import Config
from app.memory import Memory
from app.web import create_app


class NoBrain:
    context_provider = None

    async def think(self, *a, **k):
        return "ok", []


class FakeTG:
    async def send(self, *a, **k):
        pass

    async def send_chat_action(self, *a, **k):
        pass


def make(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    cfg = Config(bot_token="x", setup_code="S", anthropic_api_key="k", data_dir=str(tmp_path))
    return TestClient(create_app(mem, time.time(), Bot(mem, FakeTG(), NoBrain(), cfg))), tmp_path


def test_version_is_zero_until_an_apk_is_published(tmp_path):
    c, _ = make(tmp_path)
    r = c.get("/api/app/version")
    assert r.status_code == 200 and r.json() == {"versionCode": 0}
    assert "no-store" in r.headers["cache-control"]


def test_published_apk_is_served_and_described(tmp_path):
    c, d = make(tmp_path)
    apk = d / "apk"
    apk.mkdir(exist_ok=True)
    (apk / "mehrdad.apk").write_bytes(b"PK\x03\x04fake-apk")
    (apk / "version.json").write_text(json.dumps({"versionCode": 7, "versionName": "1.2", "sha256": "ab" * 32,
                                                  "size": 14, "notes": "داشبورد مالی"}), encoding="utf-8")
    v = c.get("/api/app/version").json()
    assert v["versionCode"] == 7 and v["versionName"] == "1.2" and v["url"] == "/download/mehrdad.apk" and v["notes"] == "داشبورد مالی"
    r = c.get("/download/mehrdad.apk")
    assert r.status_code == 200 and r.content.startswith(b"PK") and "android.package-archive" in r.headers["content-type"]
    assert "no-store" in r.headers["cache-control"]


def test_corrupt_version_file_degrades_to_zero(tmp_path):
    c, d = make(tmp_path)
    (d / "apk").mkdir(exist_ok=True)
    (d / "apk" / "version.json").write_text("{not json", encoding="utf-8")
    assert c.get("/api/app/version").json() == {"versionCode": 0}
    (d / "apk" / "version.json").write_text(json.dumps({"versionName": "x"}), encoding="utf-8")   # بدون versionCode/sha256
    assert c.get("/api/app/version").json() == {"versionCode": 0}


def test_apk_dir_does_not_expose_other_files_or_traversal(tmp_path):
    c, d = make(tmp_path)
    (d / "secret.txt").write_text("nope", encoding="utf-8")
    assert c.get("/download/../secret.txt").status_code in (404, 400)
    assert c.get("/download/secret.txt").status_code == 404
