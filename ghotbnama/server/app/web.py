"""وب‌سرور: API داده اپ، ورودی پیامک، و سرو کردن خود اپ (Mini App).

امنیت:
- /api/*: یا initData معتبر تلگرام (فقط صاحب اپ) یا هدر X-App-Key.
- /sms/<SMS_TOKEN>: توکن طولانی و تصادفی در مسیر؛ بدون آن 404.
"""
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .store import Conflict

MAX_BODY = 8 * 1024 * 1024
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
FONT_CSS = ('<style>@font-face{font-family:Vazirmatn;src:url(static/fonts/Vazirmatn-Variable.woff2) format("woff2");'
            'font-weight:100 900;font-display:swap}</style>')
INJECT_AT = "<script>\n(function(){"


def check_init_data(init_data, token, max_age=7 * 86400):
    """اعتبارسنجی initData مینی‌اپ طبق مستندات تلگرام. خروجی: شناسه کاربر یا None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    h = pairs.pop("hash", None)
    if not h:
        return None
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, h):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return int(json.loads(pairs.get("user", "{}")).get("id"))
    except (ValueError, TypeError):
        return None


def render_app(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    if INJECT_AT not in html:
        raise RuntimeError("index.html: نقطه تزریق پیدا نشد")
    html = re.sub(r'<link rel="preconnect"[^>]*>\s*', "", html)
    html = re.sub(r'<link rel="stylesheet" href="https://fonts\.googleapis\.com[^>]*>', FONT_CSS, html)
    return html.replace(INJECT_AT, '<script>window.GHOTB_API={base:"api"};</script>\n' + INJECT_AT, 1)


def create_app(store, bot, cfg):
    app = FastAPI(title="Ghotbnama", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    page = {"html": None, "mtime": 0}

    def html():
        m = os.path.getmtime(cfg.web_file)
        if m != page["mtime"]:
            page["html"], page["mtime"] = render_app(cfg.web_file), m
        return page["html"]

    def authorized(req: Request):
        key = req.headers.get("x-app-key", "")
        if cfg.app_key and key and hmac.compare_digest(key, cfg.app_key):
            return True
        init = req.headers.get("x-telegram-init-data", "")
        if init:
            uid = check_init_data(init, cfg.bot_token)
            return uid is not None and uid == bot.owner()
        return False

    nocache = {"Cache-Control": "no-store"}

    @app.get("/", response_class=HTMLResponse)
    @app.get("/app", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(html(), headers=nocache)

    @app.get("/app/")
    async def app_slash():
        return RedirectResponse("/app")

    @app.get("/health")
    async def health():
        ok = store.kget("tg_ok") or 0
        return {"ok": True, "telegram_last_ok_seconds_ago": int(time.time() - ok) if ok else None, "owner_bound": bool(bot.owner())}

    @app.get("/api/state")
    async def get_state(req: Request):
        if not authorized(req):
            return JSONResponse({"error": "unauthorized"}, 401)
        v, st = store.get()
        return JSONResponse({"version": v, "state": st}, headers=nocache)

    @app.put("/api/state")
    async def put_state(req: Request):
        if not authorized(req):
            return JSONResponse({"error": "unauthorized"}, 401)
        body = await req.body()
        if len(body) > MAX_BODY:
            return JSONResponse({"error": "too large"}, 413)
        try:
            data = json.loads(body)
            st, ver = data["state"], int(data["version"])
            if not (isinstance(st, dict) and st.get("v") == 2 and isinstance(st.get("real"), dict)):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "bad state"}, 400)
        try:
            nv = await store.put(st, ver)
        except Conflict as c:
            return JSONResponse({"version": c.version, "state": c.state}, 409)
        return {"version": nv}

    @app.post("/sms/{token}")
    async def sms(token: str, req: Request):
        if not cfg.sms_token or not hmac.compare_digest(token, cfg.sms_token):
            return JSONResponse({"error": "not found"}, 404)
        raw = await req.body()
        if len(raw) > 20000:
            return JSONResponse({"error": "too large"}, 413)
        sender, text = "", ""
        ctype = req.headers.get("content-type", "")
        try:
            if "json" in ctype or raw[:1] in (b"{", b"["):
                d = json.loads(raw)
            elif "form" in ctype:
                d = dict(parse_qsl(raw.decode("utf-8", "replace")))
            else:
                d = {"text": raw.decode("utf-8", "replace")}
        except ValueError:
            d = {"text": raw.decode("utf-8", "replace")}
        if isinstance(d, list):
            d = d[0] if d else {}
        for k in ("text", "message", "msg", "body", "content", "sms"):
            if d.get(k):
                text = str(d[k])
                break
        for k in ("from", "sender", "phone", "number", "address"):
            if d.get(k):
                sender = str(d[k])
                break
        if not text.strip():
            return {"status": "empty"}
        status = await bot.on_sms(sender, text)
        return {"status": status}

    return app
