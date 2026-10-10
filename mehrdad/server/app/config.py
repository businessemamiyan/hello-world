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
    anthropic_model: str = "claude-sonnet-5-5"
    telegram_proxy: str = ""
    telegram_api: str = "https://api.telegram.org"
    anthropic_proxy: str = ""
    claude_oauth_token: str = ""
    brain_provider: str = "auto"
    cli_model: str = "sonnet"
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
            anthropic_model=e("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
            telegram_proxy=e("TELEGRAM_PROXY", ""),
            telegram_api=e("TELEGRAM_API_BASE", "https://api.telegram.org"),
            anthropic_proxy=e("ANTHROPIC_PROXY", ""),
            claude_oauth_token=e("CLAUDE_CODE_OAUTH_TOKEN", ""),
            brain_provider=e("BRAIN_PROVIDER", "auto").strip().lower(),
            cli_model=e("CLAUDE_CLI_MODEL", "sonnet"),
            data_dir=e("DATA_DIR", "/data"),
            port=_int(e("PORT")) or 8081,
            habit_checkin_time=e("HABIT_CHECKIN_TIME", "21:00"),
        )

    def provider(self):
        """auto: کلید API هست → api؛ وگرنه cli (اشتراک Claude خود کاربر)."""
        if self.brain_provider in ("api", "cli"):
            return self.brain_provider
        return "api" if self.anthropic_api_key else "cli"

    def problems(self):
        p = []
        if not self.bot_token:
            p.append("BOT_TOKEN خالی است")
        if not self.owner_id and not self.setup_code:
            p.append("یکی از OWNER_ID یا SETUP_CODE لازم است")
        if self.provider() == "api" and not self.anthropic_api_key:
            p.append("ANTHROPIC_API_KEY خالی است (یا BRAIN_PROVIDER=cli و CLAUDE_CODE_OAUTH_TOKEN بگذار)")
        if self.provider() == "cli" and not self.claude_oauth_token:
            p.append("CLAUDE_CODE_OAUTH_TOKEN خالی است — با `claude setup-token` روی سیستم خودت بساز")
        return p
