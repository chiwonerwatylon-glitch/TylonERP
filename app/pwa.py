"""Install TylonERP like an app: a web app manifest and a small service worker.

On iPhone (Safari: Share > Add to Home Screen) and Android (Chrome: Install app) the workspace then opens full
screen from its own icon. The service worker only caches the app's static files (styles, scripts, fonts, icons)
so the app starts fast on a slow connection; pages and data always come from the server, because signed-in pages
are never stored (Cache-Control: no-store). With no connection at all it shows a short offline page.
"""
from flask import Blueprint, Response, current_app, render_template, url_for

from . import VERSION
from .models import Tenant

pwa_bp = Blueprint("pwa", __name__)


def _manifest(name, start, scope, colour):
    icons = [
        {"src": url_for("static", filename="icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
        {"src": url_for("static", filename="icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
        {"src": url_for("static", filename="icons/maskable-512.png"), "sizes": "512x512", "type": "image/png",
         "purpose": "maskable"},
    ]
    return current_app.response_class(
        current_app.json.dumps({
            "name": name, "short_name": name[:12], "start_url": start, "scope": scope, "id": start,
            "display": "standalone", "orientation": "any", "background_color": "#eef1ef", "theme_color": colour,
            "description": "Point of sale, stock and debtors.", "icons": icons,
            "shortcuts": [{"name": "Register", "url": start}],
        }),
        mimetype="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"})


@pwa_bp.get("/manifest.webmanifest")
def manifest():
    return _manifest("TylonERP", "/", "/", "#0f5c4a")


@pwa_bp.get("/t/<slug>/manifest.webmanifest")
def tenant_manifest(slug):
    t = Tenant.query.filter_by(slug=slug).first_or_404()
    colour = (t.branding.accent if t.branding and t.branding.accent else None) or "#0f5c4a"
    return _manifest(t.name, f"/t/{slug}/app/register", f"/t/{slug}/", colour)


@pwa_bp.get("/sw.js")
def service_worker():
    body = render_template("sw.js", version=VERSION)
    return Response(body, mimetype="text/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@pwa_bp.get("/offline")
def offline():
    return render_template("offline.html"), 200, {"Cache-Control": "public, max-age=86400"}
