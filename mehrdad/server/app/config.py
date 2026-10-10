import os
from dataclasses import dataclass


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass
class Config:
    bot_token: str = ""
    owner_id: int | None = None
    setup_code: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    telegram_proxy: str = ""
    telegram_api: str = "https://api.telegram.org"
    anthropic_proxy: str = ""
    data_dir: str = "/data"
    host: str = "0.0.0.0"
    port: int = 8081
    habit_checkin_time: str = "21:00"

    @classmethod
    def from_env(cls):
        e = os.environ.get
        return cls(
            bot_token=e("BOT_TOKEN", ""),
            owner_id=_int(e("OWNER_ID")),
            setup_code=e("SETUP_CODE", ""),
            anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
            anthropic_model=e("ANTHROPIC_MODEL", "claude-sonnet-5"),
            telegram_proxy=e("TELEGRAM_PROXY", ""),
            telegram_api=e("TELEGRAM_API_BASE", "https://api.telegram.org"),
            anthropic_proxy=e("ANTHROPIC_PROXY", ""),
            data_dir=e("DATA_DIR", "/data"),
            port=_int(e("PORT")) or 8081,
            habit_checkin_time=e("HABIT_CHECKIN_TIME", "21:00"),
        )

    def problems(self):
        p = []
        if not self.bot_token:
            p.append("BOT_TOKEN خالی است")
        if not self.owner_id and not self.setup_code:
            p.append("یکی از OWNER_ID یا SETUP_CODE لازم است")
        if not self.anthropic_api_key:
            p.append("ANTHROPIC_API_KEY خالی است — مغز بدون این کار نمی‌کند")
        return p
