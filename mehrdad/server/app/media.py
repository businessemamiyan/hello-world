"""اعتبارسنجی عکس ورودی (تلگرام/اپ) — فقط با بایت‌های اولیه، نه با نام یا نوع ادعاشده."""
import base64
import binascii

MAX_IMAGE_BYTES = 6 * 1024 * 1024


def sniff_image(data):
    """jpeg/png/webp/gif → media_type؛ غیر از این None."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 12:
        return None
    b = bytes(data[:12])
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def decode_image_b64(s):
    """base64 (با یا بدون data: پیشوند) → (media_type, bytes) یا None."""
    if not isinstance(s, str):
        return None
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    try:
        raw = base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        return None
    if len(raw) > MAX_IMAGE_BYTES:
        return None
    mt = sniff_image(raw)
    return (mt, raw) if mt else None
