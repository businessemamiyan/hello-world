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
    sms_token: str = ""
    app_key: str = ""
    public_url: str = ""
    telegram_proxy: str = ""
    telegram_api: str = "https://api.telegram.org"
    data_dir: str = "/data"
    web_file: str = ""
    host: str = "0.0.0.0"
    port: int = 8080
    morning: str = "07:30"
    midday: str = "13:00"
    evening: str = "21:00"
    weekly_time: str = "19:00"
    weekly_weekday: int = 4  # پایتون: دوشنبه=۰ … جمعه=۴

    @classmethod
    def from_env(cls):
        e = os.environ.get
        here = os.path.dirname(os.path.abspath(__file__))
        default_web = os.path.join(here, "..", "web", "index.html")
        if not os.path.exists(default_web):
            default_web = os.path.join(here, "..", "..", "index.html")
        return cls(
            bot_token=e("BOT_TOKEN", ""),
            owner_id=_int(e("OWNER_ID")),
            setup_code=e("SETUP_CODE", ""),
            sms_token=e("SMS_TOKEN", ""),
            app_key=e("APP_KEY", ""),
            public_url=e("PUBLIC_URL", ""),
            telegram_proxy=e("TELEGRAM_PROXY", ""),
            telegram_api=e("TELEGRAM_API_BASE", "https://api.telegram.org"),
            data_dir=e("DATA_DIR", "/data"),
            web_file=e("WEB_FILE", os.path.abspath(default_web)),
            port=_int(e("PORT")) or 8080,
            morning=e("MORNING", "07:30"),
            midday=e("MIDDAY", "13:00"),
            evening=e("EVENING", "21:00"),
            weekly_time=e("WEEKLY_TIME", "19:00"),
            weekly_weekday=_int(e("WEEKLY_WEEKDAY")) if e("WEEKLY_WEEKDAY") else 4,
        )

    def problems(self):
        p = []
        if not self.bot_token:
            p.append("BOT_TOKEN خالی است")
        if not self.owner_id and not self.setup_code:
            p.append("یکی از OWNER_ID یا SETUP_CODE لازم است")
        if len(self.sms_token) < 16:
            p.append("SMS_TOKEN باید حداقل ۱۶ کاراکتر تصادفی باشد")
        if len(self.app_key) < 16:
            p.append("APP_KEY باید حداقل ۱۶ کاراکتر تصادفی باشد")
        return p
