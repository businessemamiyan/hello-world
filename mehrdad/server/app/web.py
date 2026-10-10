import time

from fastapi import FastAPI

from .api import create_router


def create_app(mem, started_at, svc=None):
    # مستندات خودکار خاموش: سطح حمله کمتر (API فقط برای اپ خودمان است)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if svc is not None:
        app.include_router(create_router(mem, svc))

    @app.get("/health")
    async def health():
        owner = await mem.get_owner()
        return {"ok": True, "owner_set": owner is not None, "uptime_seconds": round(time.time() - started_at)}

    return app
