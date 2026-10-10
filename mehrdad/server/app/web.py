import os
import time

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import create_router


def create_app(mem, started_at, svc=None):
    # مستندات خودکار خاموش: سطح حمله کمتر (API فقط برای اپ خودمان است)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if svc is not None:
        app.include_router(create_router(mem, svc))

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    @app.middleware("http")
    async def no_cache_for_app(request, call_next):
        resp = await call_next(request)
        if request.url.path.startswith("/app"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/app/")

    if os.path.isdir(static_dir):   # فقط فایل‌های ثابت (بدون داده)؛ داده فقط با توکن دستگاه از /api می‌آید
        app.mount("/app", StaticFiles(directory=static_dir, html=True), name="app")

    @app.get("/health")
    async def health():
        owner = await mem.get_owner()
        return {"ok": True, "owner_set": owner is not None, "uptime_seconds": round(time.time() - started_at)}

    return app
