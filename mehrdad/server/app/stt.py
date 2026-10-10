"""تبدیل صدا به متن روی خود سرور (faster-whisper، بدون API پولی).

مدل فقط وقتی لازم است در حافظه می‌ماند (بعد از ۱۰ دقیقه بی‌کاری آزاد می‌شود)؛ فایل مدل روی ولوم /data/models
می‌ماند تا با هر ساخت دوبارهٔ ایمیج دوباره دانلود نشود. یک رونویسی در هر لحظه (۲ هستهٔ سرور).
"""
import asyncio
import gc
import logging
import os
import tempfile

log = logging.getLogger("stt")

PROMPT = ("این یک پیام صوتی فارسی دربارهٔ زندگی روزمره است: پول، خرج و درآمد، تومان، میلیون، هزار تومان، حساب بانکی، قسط، "
          "قلیان، غذا، ایساتیس، کار، برنامه و هدف.")


class STTError(Exception):
    pass


class STT:
    def __init__(self, model="large-v3-turbo", cache_dir="/data/models", idle_seconds=600, threads=2):
        self.model_name = model
        self.cache_dir = cache_dir
        self.idle_seconds = idle_seconds
        self.threads = threads
        self._model = None
        self._lock = asyncio.Lock()
        self._unload = None

    @property
    def enabled(self):
        return bool(self.model_name)

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel          # import سنگین فقط موقع نیاز
            os.makedirs(self.cache_dir, exist_ok=True)
            log.info("بارگذاری مدل گفتار %s …", self.model_name)
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8", cpu_threads=self.threads, download_root=self.cache_dir)
            log.info("مدل گفتار آماده شد")
        return self._model

    def _run(self, data, suffix, language):
        model = self._load()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            path = f.name
        try:
            segments, info = model.transcribe(path, language=language, beam_size=1, vad_filter=True, condition_on_previous_text=False,
                                              initial_prompt=PROMPT if language == "fa" else None)
            return " ".join(s.text.strip() for s in segments).strip()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _schedule_unload(self):
        loop = asyncio.get_running_loop()
        if self._unload:
            self._unload.cancel()

        def drop():
            self._model = None
            gc.collect()
            log.info("مدل گفتار از حافظه آزاد شد")
        self._unload = loop.call_later(self.idle_seconds, drop)

    async def warmup(self):
        """دانلود/بارگذاری اولیه در پس‌زمینه تا اولین ویس معطل نشود."""
        if not self.enabled:
            return
        try:
            async with self._lock:
                await asyncio.to_thread(self._load)
            self._schedule_unload()
        except Exception:
            log.exception("آماده‌سازی مدل گفتار ناموفق")

    async def transcribe(self, data, suffix=".ogg", language="fa", timeout=900):
        if not self.enabled:
            raise STTError("تبدیل گفتار خاموش است")
        async with self._lock:
            try:
                text = await asyncio.wait_for(asyncio.to_thread(self._run, data, suffix, language), timeout)
            except asyncio.TimeoutError:
                raise STTError("رونویسی بیش از حد طول کشید")
            except Exception as e:
                log.exception("رونویسی ناموفق")
                raise STTError(str(e)[:200] or "خطا")
            finally:
                self._schedule_unload()
        return text
