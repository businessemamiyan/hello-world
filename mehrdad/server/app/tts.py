"""تبدیل متن به گفتار فارسی روی سرور (Edge TTS؛ بدون کلید و بدون هزینه).

گوشی‌ها اغلب صدای فارسی ندارند، پس صدا را سرور می‌سازد و اپ فقط MP3 را پخش می‌کند.
خروجی کوچک است (چند ده کیلوبایت) و برای متن‌های تکراری در حافظه کش می‌شود.
"""
import asyncio
import collections
import logging
import re

log = logging.getLogger("tts")

VOICES = {"male": "fa-IR-FaridNeural", "female": "fa-IR-DilaraNeural"}
DEFAULT_VOICE = "male"
MAX_CHARS = 1400

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍←-⇿]+")
_URL = re.compile(r"https?://\S+")
_MD = re.compile(r"[*_`#>~|]+")
_BULLET = re.compile(r"^\s*(?:[-•●▪]|\d+[.)])\s+", re.M)


class TTSError(Exception):
    pass


def clean_for_speech(text, limit=MAX_CHARS):
    """متن چت را برای خواندن آماده می‌کند: بدون ایموجی، لینک، علامت‌های مارک‌داون؛ در پایان یک جمله بریده می‌شود."""
    t = str(text or "")
    t = _URL.sub(" ", t)
    t = _EMOJI.sub(" ", t)
    t = _BULLET.sub("", t)
    t = _MD.sub(" ", t)
    t = t.replace("‌", " ").replace("…", "،")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    if len(t) > limit:
        cut = t[:limit]
        end = max(cut.rfind("."), cut.rfind("؟"), cut.rfind("!"), cut.rfind("\n"))
        t = cut[:end + 1] if end > limit // 2 else cut
    return t.strip()


class TTS:
    def __init__(self, cache_size=48, timeout=30):
        self.timeout = timeout
        self._cache = collections.OrderedDict()
        self._cache_size = cache_size
        self._sem = asyncio.Semaphore(2)

    @property
    def enabled(self):
        return True

    async def _stream(self, text, voice, rate):
        import edge_tts                                   # import فقط موقع نیاز
        out = bytearray()
        async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
            if chunk.get("type") == "audio":
                out += chunk["data"]
        return bytes(out)

    async def synth(self, text, voice=None, rate="+0%"):
        """MP3 برای متن؛ TTSError اگر متنی برای خواندن نماند یا سرویس جواب نداد."""
        clean = clean_for_speech(text)
        if not clean:
            raise TTSError("متنی برای خواندن نیست")
        name = VOICES.get(voice or DEFAULT_VOICE, VOICES[DEFAULT_VOICE])
        key = (clean, name, rate)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        async with self._sem:
            try:
                data = await asyncio.wait_for(self._stream(clean, name, rate), self.timeout)
            except asyncio.TimeoutError:
                raise TTSError("سرویس صدا دیر جواب داد")
            except Exception as e:
                log.warning("tts ناموفق: %s", e)
                raise TTSError("سرویس صدا جواب نداد")
        if len(data) < 200:
            raise TTSError("صدایی ساخته نشد")
        self._cache[key] = data
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return data
