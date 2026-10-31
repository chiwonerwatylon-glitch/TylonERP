"""Forgiving parsers for form and JSON input."""
from decimal import Decimal, InvalidOperation


def money(value, default=None):
    """A non-negative Decimal from user input, or `default` if it is missing, malformed or negative."""
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return default
    if not amount.is_finite():
        return default
    return amount if amount >= 0 else default


def integer(value, default=None):
    """A non-negative int from user input, or `default`."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default
