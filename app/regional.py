"""Countries, currencies, number and date formats, tax and time zones.

A business picks its country once; that suggests its currency, time zone, number format and sales tax, and the
admin can change any of them under Business settings. Money is formatted with Babel (CLDR data), so amounts
look the way people in that country write them: 1,234.50 in Harare, 1 234,50 in Maputo, 1.234,50 in Lisbon.
"""
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from babel import Locale, UnknownLocaleError
from babel.dates import format_date, format_datetime, format_time
from babel.numbers import format_currency, format_decimal, get_currency_precision, get_currency_symbol

# Symbols people actually use where CLDR has none yet or a different one.
SYMBOL_OVERRIDES = {"ZWG": "ZiG"}

# Currencies offered in the picker, roughly by how often our businesses use them; any ISO 4217 code also works.
CURRENCIES = [
    "USD", "ZWG", "ZAR", "BWP", "ZMW", "MZN", "MWK", "NAD", "LSL", "SZL", "AOA", "CDF",
    "KES", "TZS", "UGX", "RWF", "BIF", "ETB", "SOS", "SSP", "SDG",
    "NGN", "GHS", "XOF", "XAF", "GMD", "SLE", "LRD", "GNF", "CVE",
    "EGP", "MAD", "DZD", "TND", "LYD", "MUR", "SCR", "MGA",
    "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "TRY", "RUB", "UAH",
    "AED", "SAR", "QAR", "KWD", "BHD", "OMR", "JOD", "ILS",
    "INR", "PKR", "BDT", "LKR", "NPR", "CNY", "HKD", "JPY", "KRW", "SGD", "MYR", "IDR", "THB", "VND", "PHP",
    "CAD", "MXN", "BRL", "ARS", "CLP", "COP", "PEN", "JMD", "TTD",
    "AUD", "NZD", "FJD",
]

# country: (name, currency, time zone, number locale, tax name, suggested tax rate %)
# Tax rates are starting suggestions only. Every business must check and set its own rate.
COUNTRIES = {
    "ZW": ("Zimbabwe", "USD", "Africa/Harare", "en_ZW", "VAT", "15.5"),
    "ZA": ("South Africa", "ZAR", "Africa/Johannesburg", "en_ZA", "VAT", "15"),
    "BW": ("Botswana", "BWP", "Africa/Gaborone", "en_BW", "VAT", "14"),
    "ZM": ("Zambia", "ZMW", "Africa/Lusaka", "en_ZM", "VAT", "16"),
    "MZ": ("Mozambique", "MZN", "Africa/Maputo", "pt_MZ", "IVA", "16"),
    "MW": ("Malawi", "MWK", "Africa/Blantyre", "en_MW", "VAT", "16.5"),
    "NA": ("Namibia", "NAD", "Africa/Windhoek", "en_NA", "VAT", "15"),
    "LS": ("Lesotho", "LSL", "Africa/Maseru", "en_LS", "VAT", "15"),
    "SZ": ("Eswatini", "SZL", "Africa/Mbabane", "en_SZ", "VAT", "15"),
    "AO": ("Angola", "AOA", "Africa/Luanda", "pt_AO", "IVA", "14"),
    "CD": ("DR Congo", "CDF", "Africa/Lubumbashi", "fr_CD", "TVA", "16"),
    "KE": ("Kenya", "KES", "Africa/Nairobi", "en_KE", "VAT", "16"),
    "TZ": ("Tanzania", "TZS", "Africa/Dar_es_Salaam", "en_TZ", "VAT", "18"),
    "UG": ("Uganda", "UGX", "Africa/Kampala", "en_UG", "VAT", "18"),
    "RW": ("Rwanda", "RWF", "Africa/Kigali", "en_RW", "VAT", "18"),
    "ET": ("Ethiopia", "ETB", "Africa/Addis_Ababa", "en_ET", "VAT", "15"),
    "NG": ("Nigeria", "NGN", "Africa/Lagos", "en_NG", "VAT", "7.5"),
    "GH": ("Ghana", "GHS", "Africa/Accra", "en_GH", "VAT", "15"),
    "SN": ("Senegal", "XOF", "Africa/Dakar", "fr_SN", "TVA", "18"),
    "CI": ("Côte d'Ivoire", "XOF", "Africa/Abidjan", "fr_CI", "TVA", "18"),
    "CM": ("Cameroon", "XAF", "Africa/Douala", "fr_CM", "TVA", "19.25"),
    "EG": ("Egypt", "EGP", "Africa/Cairo", "ar_EG", "VAT", "14"),
    "MA": ("Morocco", "MAD", "Africa/Casablanca", "fr_MA", "TVA", "20"),
    "MU": ("Mauritius", "MUR", "Indian/Mauritius", "en_MU", "VAT", "15"),
    "US": ("United States", "USD", "America/New_York", "en_US", "Sales tax", "0"),
    "CA": ("Canada", "CAD", "America/Toronto", "en_CA", "GST", "5"),
    "MX": ("Mexico", "MXN", "America/Mexico_City", "es_MX", "IVA", "16"),
    "BR": ("Brazil", "BRL", "America/Sao_Paulo", "pt_BR", "Tax", "0"),
    "GB": ("United Kingdom", "GBP", "Europe/London", "en_GB", "VAT", "20"),
    "IE": ("Ireland", "EUR", "Europe/Dublin", "en_IE", "VAT", "23"),
    "FR": ("France", "EUR", "Europe/Paris", "fr_FR", "TVA", "20"),
    "DE": ("Germany", "EUR", "Europe/Berlin", "de_DE", "MwSt", "19"),
    "ES": ("Spain", "EUR", "Europe/Madrid", "es_ES", "IVA", "21"),
    "PT": ("Portugal", "EUR", "Europe/Lisbon", "pt_PT", "IVA", "23"),
    "IT": ("Italy", "EUR", "Europe/Rome", "it_IT", "IVA", "22"),
    "NL": ("Netherlands", "EUR", "Europe/Amsterdam", "nl_NL", "BTW", "21"),
    "AE": ("United Arab Emirates", "AED", "Asia/Dubai", "ar_AE", "VAT", "5"),
    "SA": ("Saudi Arabia", "SAR", "Asia/Riyadh", "ar_SA", "VAT", "15"),
    "IN": ("India", "INR", "Asia/Kolkata", "en_IN", "GST", "18"),
    "CN": ("China", "CNY", "Asia/Shanghai", "zh_Hans_CN", "VAT", "13"),
    "SG": ("Singapore", "SGD", "Asia/Singapore", "en_SG", "GST", "9"),
    "AU": ("Australia", "AUD", "Australia/Sydney", "en_AU", "GST", "10"),
    "NZ": ("New Zealand", "NZD", "Pacific/Auckland", "en_NZ", "GST", "15"),
}

# Languages the workspace screens are translated into: code -> (own name, right to left)
LANGUAGES = {
    "en": ("English", False),
    "fr": ("Français", False),
    "pt": ("Português", False),
    "es": ("Español", False),
    "sw": ("Kiswahili", False),
    "sn": ("chiShona", False),
    "ar": ("العربية", True),
    "zh": ("中文", False),
}

DEFAULTS = {"country": "ZW", "currency": "USD", "timezone": "Africa/Harare", "locale": "en_ZW"}


@lru_cache(maxsize=1)
def timezones():
    return sorted(z for z in available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/", "posix/", "right/")))


def valid_timezone(name):
    try:
        ZoneInfo(name)
        return bool(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False


def valid_locale(code):
    try:
        Locale.parse(code)
        return True
    except (UnknownLocaleError, ValueError, TypeError):
        return False


def valid_currency(code):
    code = str(code or "").upper()
    if len(code) != 3 or not code.isalpha():
        return False
    try:
        return get_currency_symbol(code, "en") != code or code in CURRENCIES
    except Exception:
        return code in CURRENCIES


@lru_cache(maxsize=256)
def currency_label(code, locale="en"):
    from babel.numbers import get_currency_name

    try:
        return f"{code} · {get_currency_name(code, locale=locale)}"
    except Exception:
        return code


@lru_cache(maxsize=256)
def symbol(code, locale="en"):
    if code in SYMBOL_OVERRIDES:
        return SYMBOL_OVERRIDES[code]
    try:
        return get_currency_symbol(code, locale=locale)
    except Exception:
        return code


@lru_cache(maxsize=256)
def precision(code):
    try:
        return get_currency_precision(code)
    except Exception:
        return 2


def quantize(amount, code):
    """Round an amount to the number of decimals the currency uses (none for UGX or JPY, two for most)."""
    places = precision(code)
    return Decimal(amount).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def fmt_money(amount, code="USD", locale="en_ZW", symbol_on=True):
    """Format an amount the local way, with the currency's symbol and decimals."""
    if amount is None:
        return ""
    code = (code or "USD").upper()
    locale = locale or DEFAULTS["locale"]
    value = Decimal(amount)
    try:
        if not symbol_on:
            places = precision(code)
            return format_decimal(value, format=f"#,##0.{'0' * places}" if places else "#,##0", locale=locale)
        out = format_currency(value, code, locale=locale)
    except Exception:
        out = f"{code} {value:,.2f}"
    if code in SYMBOL_OVERRIDES:
        out = out.replace(get_currency_symbol(code, locale=locale), SYMBOL_OVERRIDES[code])
    return out


def fmt_number(value, locale="en_ZW"):
    try:
        return format_decimal(value, locale=locale)
    except Exception:
        return str(value)


def to_local(dt, tz):
    """Stored datetimes are naive UTC; give the same moment in the business's time zone."""
    if dt is None:
        return None
    try:
        zone = ZoneInfo(tz or DEFAULTS["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(DEFAULTS["timezone"])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(zone)


def local_now(tz):
    return to_local(datetime.now(UTC), tz)


def fmt_datetime(dt, tz, locale, style="medium"):
    if dt is None:
        return ""
    local = to_local(dt, tz)
    try:
        if style == "date":
            return format_date(local, format="medium", locale=locale)
        if style == "time":
            return format_time(local, format="short", locale=locale)
        if style == "short":
            return format_datetime(local, format="d MMM, HH:mm", locale=locale)
        return format_datetime(local, format="medium", locale=locale)
    except Exception:
        return local.strftime("%d %b %Y %H:%M")


def js_config(tenant):
    """What the browser needs to show money the same way the server does."""
    return {
        "currency": tenant.currency_code, "locale": tenant.number_locale.replace("_", "-"),
        "symbol": symbol(tenant.currency_code, tenant.number_locale), "decimals": precision(tenant.currency_code),
        "alt": ({"currency": tenant.alt_currency, "rate": str(tenant.alt_rate), "decimals": precision(tenant.alt_currency),
                 "symbol": symbol(tenant.alt_currency, tenant.number_locale)}
                if tenant.alt_currency and tenant.alt_rate else None),
        "tax": {"name": tenant.tax_label, "rate": str(tenant.tax_percent), "inclusive": tenant.tax_is_inclusive},
        "timezone": tenant.tz,
    }
