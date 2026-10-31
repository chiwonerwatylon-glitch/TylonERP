"""Matching a photographed product against registered ones.

A product's signature is 70 hex characters: a 64-bit difference hash of its shape (16 hex), then a 3x3 grid
of average RGB colours (54 hex). Scores run from 0 (identical look) to 1 (completely different).
"""
import re

SIGNATURE_RE = re.compile(r"^[0-9a-f]{70}$")
DUPLICATE_SCORE = 0.12  # below this a new photo counts as an already registered product
MATCH_CUTOFF = 0.45  # above this a candidate is not worth showing
SHAPE_WEIGHT = 0.4
COLOUR_WEIGHT = 0.6
COLOUR_GAIN = 3  # colour differences are small, so they are boosted before weighing


def is_valid_signature(sig):
    return bool(sig) and bool(SIGNATURE_RE.match(sig))


def signature_score(a, b):
    """0 = identical look, 1 = completely different. Mixes shape (dHash) and colour."""
    if not a or not b or len(a) != 70 or len(b) != 70:
        return 1.0
    shape = bin(int(a[:16], 16) ^ int(b[:16], 16)).count("1") / 64
    ca = [int(a[16 + i:18 + i], 16) for i in range(0, 54, 2)]
    cb = [int(b[16 + i:18 + i], 16) for i in range(0, 54, 2)]
    colour = sum(abs(x - y) for x, y in zip(ca, cb)) / (54 * 255)
    return SHAPE_WEIGHT * shape + COLOUR_WEIGHT * min(1.0, colour * COLOUR_GAIN)


def rank_matches(sig, products, limit=5, cutoff=MATCH_CUTOFF):
    """The closest `limit` products to `sig` as (score, product), best first, dropping poor matches.

    `products` is any iterable of objects with a `.signature` attribute.
    """
    scored = sorted(((signature_score(sig, p.signature), p) for p in products), key=lambda t: t[0])
    return [(score, p) for score, p in scored[:limit] if score < cutoff]
