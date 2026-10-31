"""Security headers and rate limiting."""
from flask import request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Behind Railway's proxy, ProxyFix (see create_app) makes remote_addr the real client address.
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# The app uses inline scripts and styles (receipt print, tenant theme colours), so those stay allowed.
# Everything else is locked to this origin. The camera needs blob: for video frames and data: for images.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # The stock and quick-sell screens scan barcodes and photos with the camera.
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
}

HSTS = "max-age=31536000; includeSubDomains"


def init_security(app):
    @app.after_request
    def add_headers(response):
        for name, value in BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        if app.config.get("SESSION_COOKIE_SECURE") and request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        if request.endpoint and request.endpoint != "static" and request.method == "GET" and not response.cache_control.public:
            # Signed-in pages must not be stored by shared caches or shown again after sign-out
            response.headers.setdefault("Cache-Control", "no-store")
        return response
