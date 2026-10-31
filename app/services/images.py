"""Uploaded image checks. The file's own bytes decide the type, never the file name the browser sends."""

MAX_IMAGE = 2 * 1024 * 1024  # branding pictures
MAX_PHOTO = 1024 * 1024  # product photos

_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"RIFF": "image/webp",  # RIFF is also used by WAV and AVI, so the WEBP tag is checked below
}


def sniff_image(data):
    """Return 'image/png', 'image/jpeg' or 'image/webp' for real images, else None."""
    mime = next((m for sig, m in _SIGNATURES.items() if data.startswith(sig)), None)
    if mime == "image/webp" and data[8:12] != b"WEBP":
        return None
    return mime
