import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
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
        if request.url.path.startswith(("/app", "/download", "/api")):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"   # نه مرورگر، نه Cloudflare نسخهٔ قدیمی نگه ندارد
        return resp

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
