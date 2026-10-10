import time

from fastapi import FastAPI


def create_app(mem, started_at):
    app = FastAPI()

    @app.get("/health")
    async def health():
        owner = await mem.get_owner()
        return {"ok": True, "owner_set": owner is not None, "uptime_seconds": round(time.time() - started_at)}

    return app
