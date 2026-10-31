from decimal import Decimal

import pytest

from app.models import Sale
from app.routes import EMAIL_RE, SLUG_RE, _safe_next
from app.services.images import sniff_image as _sniff
from app.services.matching import signature_score
from app.services.parsing import integer, money
from app.services.theme import luminance as _lum
from app.services.theme import mix as _mix

SIG = "0" * 16 + "80" * 27


def test_signature_identical_is_zero():
    assert signature_score(SIG, SIG) == 0


def test_signature_bad_input_is_no_match():
    assert signature_score(None, SIG) == 1.0
    assert signature_score("abc", SIG) == 1.0


def test_signature_different_scores_higher():
    other = "f" * 16 + "00" * 27
    assert signature_score(SIG, other) > 0.4


@pytest.mark.parametrize("data,mime", [
    (b"\x89PNG\r\n\x1a\n....", "image/png"),
    (b"\xff\xd8\xff\xe0....", "image/jpeg"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", None),
    (b"GIF89a", None),
    (b"", None),
])
def test_sniff(data, mime):
    assert _sniff(data) == mime


def test_money():
    assert money("12.50") == Decimal("12.50")
    assert money("-1") is None
    assert money("abc", default=Decimal(0)) == Decimal(0)
    assert money(None) is None


def test_integer():
    assert integer("3") == 3
    assert integer("-3") is None
    assert integer("x", 7) == 7


def test_sale_kind_and_balance():
    s = Sale(quantity=2, unit_price=Decimal("10"), paid=Decimal("20"))
    assert (s.total, s.balance, s.kind) == (20, 0, "Cash")
    s.paid = Decimal("0")
    assert s.kind == "Credit"
    s.paid = Decimal("5")
    assert (s.kind, s.balance) == ("Part-paid", 15)


def test_safe_next_blocks_open_redirects():
    assert _safe_next("/t/a/app/") == "/t/a/app/"
    assert _safe_next("//evil.com") is None
    assert _safe_next("https://evil.com") is None
    assert _safe_next(None) is None


def test_validators():
    assert EMAIL_RE.match("a@b.co") and not EMAIL_RE.match("a@b")
    assert SLUG_RE.match("acme-shop") and not SLUG_RE.match("-bad-") and not SLUG_RE.match("Ab")


def test_colour_helpers():
    assert _mix("#000000", "#ffffff", 0.5) == "#808080"
    assert _lum("#ffffff") > 0.99 and _lum("#000000") == 0
