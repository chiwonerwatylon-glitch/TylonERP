"""One barcode, one product: clean up what scanners send and match codes however they were read.

The same printed code reaches us in different shapes:
- camera decoders read a 12-digit UPC-A as a 13-digit EAN-13 with a leading 0 (or the other way round);
- spreadsheets drop leading zeros;
- hardware scanners add symbology prefixes such as "]E0", tabs, carriage returns or spaces.
Every code is cleaned with `clean()` before it is stored, and looked up with `variants()` so codes stored before this
existed still match.
"""
import re

_PREFIX = re.compile(r"^\][A-Za-z][0-9A-Za-z]")  # AIM symbology identifier, e.g. ]E0, ]C1, ]Q3
_CONTROL = re.compile(r"[\x00-\x1f\x7f\s]+")
MAX_LEN = 64


def clean(raw) -> str | None:
    """Return the canonical form of a scanned or typed barcode, or None if nothing is left."""
    code = _CONTROL.sub("", str(raw or ""))
    code = _PREFIX.sub("", code)
    code = code[:MAX_LEN]
    if not code:
        return None
    if code.isdigit() and len(code) == 12:  # UPC-A is EAN-13 with a leading zero
        code = "0" + code
    return code


def variants(code: str | None) -> list[str]:
    """Every stored form that means the same numeric code (UPC-A, EAN-13, GTIN-14, zeros dropped)."""
    if not code:
        return []
    if not code.isdigit():
        return [code]
    core = code.lstrip("0") or "0"
    return sorted({code, core, *(core.zfill(n) for n in range(len(core), 15))})


def key(code: str | None) -> str | None:
    """A comparison key: numeric codes padded to GTIN-14, anything else as is."""
    if not code:
        return None
    c = clean(code) or ""
    return c.lstrip("0").zfill(14) if c.isdigit() else c
