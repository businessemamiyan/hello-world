import os
import time

from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import create_router, save_wife_answers

_THANKS = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>%s</title><link rel="stylesheet" href="/app/theme.css"></head>
<body><div class="wrap"><main class="pane"><div class="card" style="text-align:center;padding:36px 12px"><h2>%s</h2><p>%s</p></div></main></div></body></html>"""


def _page(title, text, code=200):
    return HTMLResponse(_THANKS % (title, title, text), status_code=code, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def create_app(mem, started_at, svc=None):
    # مستندات خودکار خاموش: سطح حمله کمتر (API فقط برای اپ خودمان است)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if svc is not None:
        app.include_router(create_router(mem, svc))

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    @app.middleware("http")
    async def no_cache_for_app(request, call_next):
        resp = await call_next(request)
        if request.url.path.startswith(("/app", "/download", "/api")):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"   # نه مرورگر، نه Cloudflare نسخهٔ قدیمی نگه ندارد
        return resp

    @app.get("/who/{token}", include_in_schema=False)
    async def who_page(token: str):
        path = os.path.join(static_dir, "who.html")
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path, media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"})

    if svc is not None:
        @app.post("/who/{token}/submit", include_in_schema=False)
        async def who_submit(token: str, request: Request):
            """مسیر کمکی بدون جاوااسکریپت: همان فرمِ صفحه را ساده (urlencoded) می‌فرستد؛ برای مرورگرهایی که fetch/JSON‌شان نمی‌رسد."""
            raw = b""
            async for chunk in request.stream():
                raw += chunk
                if len(raw) > 200_000:
                    return _page("زیادی بزرگ شد", "جواب‌ها رو یه کم کوتاه‌تر بنویس و دوباره بفرست.", 413)
            form = parse_qs(raw.decode("utf-8", "replace"))
            who = (form.pop("__who", [""])[0] or "")
            answers = {k: v[0] for k, v in form.items() if v}
            try:
                n = await save_wife_answers(mem, svc, token, answers, who)
            except LookupError:
                return _page("این لینک دیگه کار نمی‌کنه", "شاید مهلتش تموم شده یا باطل شده. از مهرداد بخواه یه لینک تازه برات بفرسته.", 404)
            except ValueError:
                return _page("جواب‌ها خالی بود", "برگرد و حداقل یه سؤال رو جواب بده، بعد بفرست 🙏", 422)
            return _page("مرسی 💛", "جواب‌هات رسید؛ خیلی کمک می‌کنه. می‌تونی صفحه رو ببندی.")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/app/")

    cfg = getattr(svc, "cfg", None)
    if cfg is not None:
        apk_path = os.path.join(cfg.data_dir, "apk", "mehrdad.apk")

        @app.get("/download/mehrdad.apk", include_in_schema=False)
        async def download_apk():
            if not os.path.isfile(apk_path):
                raise HTTPException(status_code=404, detail="no apk published")
            return FileResponse(apk_path, media_type="application/vnd.android.package-archive", filename="mehrdad.apk")

    if os.path.isdir(static_dir):   # فقط فایل‌های ثابت (بدون داده)؛ داده فقط با توکن دستگاه از /api می‌آید
        app.mount("/app", StaticFiles(directory=static_dir, html=True), name="app")

    @app.get("/health")
    async def health():
        owner = await mem.get_owner()
        return {"ok": True, "owner_set": owner is not None, "uptime_seconds": round(time.time() - started_at)}

    return app
