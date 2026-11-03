"""Screen languages.

Templates write English and wrap it in `_()`: `{{ _("Sales") }}`, or with values `{{ _("{n} left", n=p.stock) }}`.
Each language has a catalog in app/translations/<code>.json mapping the English text to its translation; anything
missing falls back to English, so a new string never breaks a page.

Which language a page uses: the member's own choice, else their business's default, else the language picked on
the sign-in page (a cookie), else the browser's preferred language, else English.
"""
import json
from functools import cache
from pathlib import Path

from flask import g, request

from .regional import LANGUAGES

CATALOG_DIR = Path(__file__).parent / "translations"
COOKIE = "lang"


@cache
def catalog(lang):
    path = CATALOG_DIR / f"{lang}.json"
    if lang == "en" or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def translate(text, lang=None, **values):
    lang = lang or current_language()
    out = catalog(lang).get(text) or text
    if values:
        try:
            out = out.format(**values)
        except (KeyError, IndexError, ValueError):
            out = text.format(**values)
    return out


def current_language():
    return g.get("lang") or "en"


def is_rtl(lang=None):
    return LANGUAGES.get(lang or current_language(), ("", False))[1]


def pick_language(user=None, tenant=None):
    """The language for this request, in order of preference (see module docstring)."""
    for candidate in (getattr(user, "language", None), getattr(tenant, "language", None), request.cookies.get(COOKIE)):
        if candidate in LANGUAGES:
            return candidate
    best = request.accept_languages.best_match(list(LANGUAGES))
    return best or "en"


def js_catalog(keys, lang=None):
    """Translations for strings that scripts show (passed to the page as JSON)."""
    lang = lang or current_language()
    return {k: translate(k, lang) for k in keys}
