"""EcoCash Online Payments client: charge, transaction lookup, refund/reversal.

Docs: https://developers.ecocash.co.zw/docs/online-payments
Authentication is HTTP Basic. Match on responseCode, not message text.
"""
import re
import time
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from decimal import Decimal

import requests

ECOCASH_RE = re.compile(r"^7[78]\d{7}$")
ONEMONEY_RE = re.compile(r"^71\d{7}$")


def normalise_msisdn(raw: str | None) -> str:
    """'+263 77 304 7653', '0773047653' and '773047653' all become '773047653'."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("263"):
        digits = digits[3:]
    return digits[1:] if digits.startswith("0") else digits


class EcoCashError(Exception):
    """The charge was definitively not taken (declined, bad request, bad credentials)."""

    def __init__(self, message, code=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class EcoCashUnknown(Exception):
    """Network failure or timeout: the charge may or may not have gone through. Look it up."""


@dataclass
class Result:
    status: str          # "Charged", "Refunded", ... as returned by EcoCash
    ecocash_reference: str | None
    response_code: str | None
    ok: bool


def new_correlator(tenant_id: int, sale_id: int) -> str:
    return f"T{tenant_id}S{sale_id}-{uuid.uuid4().hex[:10]}"


def client_for_tenant(settings, tenant, session=None):
    """Build a client from platform endpoint settings plus the tenant's own merchant account.

    Returns a disabled client when the tenant has not set EcoCash up; there is deliberately no fallback to
    platform credentials, so one tenant's customers can never pay into another account.
    """
    from .secrets import decrypt

    tp = tenant.payment if tenant else None
    on = bool(tp and tp.ecocash_enabled and tp.complete)
    merged = SimpleNamespace(
        ecocash_base_url=settings.ecocash_base_url, ecocash_charge_path=settings.ecocash_charge_path,
        ecocash_currency=settings.ecocash_currency, ecocash_notify_url=settings.ecocash_notify_url,
        ecocash_timeout=settings.ecocash_timeout, ecocash_super_merchant_name=settings.ecocash_super_merchant_name,
        ecocash_username=tp.username if on else None,
        ecocash_password=decrypt(tp.password_enc, settings.secret_key) if on else None,
        ecocash_merchant_code=tp.merchant_code if on else None,
        ecocash_merchant_pin=decrypt(tp.merchant_pin_enc, settings.secret_key) if on else "",
        ecocash_merchant_number=normalise_msisdn(tp.merchant_number) if on else None,
        ecocash_merchant_name=(tp.merchant_name or tenant.name) if on else "",
        ecocash_terminal_id=(tp.terminal_id or "WEB00001") if on else "",
        ecocash_location=(tp.location or "Harare") if on else "")
    return EcoCashClient(merged, session)


class EcoCashClient:
    def __init__(self, settings, session=None):
        self.s = settings
        self.http = session or requests

    @property
    def enabled(self) -> bool:
        s = self.s
        return bool(s.ecocash_username and s.ecocash_password and s.ecocash_merchant_code
                    and s.ecocash_merchant_number)

    def _auth(self):
        return (self.s.ecocash_username, self.s.ecocash_password)

    def _merchant(self, amount, description, correlator, reference, tran_type):
        s = self.s
        return {
            "clientCorrelator": correlator,
            "referenceCode": reference,
            "tranType": tran_type,
            "paymentAmount": {
                "charginginformation": {"amount": float(Decimal(amount).quantize(Decimal("0.01"))),
                                        "currency": s.ecocash_currency, "description": description[:100]},
                "chargeMetaData": {"channel": "WEB", "purchaseCategoryCode": "Online Payment",
                                   "onBeHalfOf": s.ecocash_super_merchant_name},
            },
            "merchantCode": s.ecocash_merchant_code,
            "merchantPin": s.ecocash_merchant_pin,
            "merchantNumber": s.ecocash_merchant_number,
            "countryCode": "ZW",
            "terminalID": s.ecocash_terminal_id,
            "location": s.ecocash_location,
            "superMerchantName": s.ecocash_super_merchant_name,
            "merchantName": s.ecocash_merchant_name,
        }

    def _call(self, method, url, body=None) -> Result:
        try:
            r = self.http.request(method, url, json=body, auth=self._auth(), timeout=self.s.ecocash_timeout)
        except requests.RequestException as e:
            raise EcoCashUnknown(str(e)) from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 500:
            raise EcoCashUnknown(f"EcoCash returned HTTP {r.status_code}")
        code = str(data.get("responseCode") or "") or None
        status = str(data.get("transactionOperationStatus") or "")
        if r.status_code == 401:
            raise EcoCashError("EcoCash rejected our credentials. Check the ECOCASH_* settings.", code, 401)
        if r.status_code >= 400 or (code and code != "00"):
            raise EcoCashError(data.get("message") or data.get("errorMessage")
                               or f"EcoCash declined the payment (code {code or r.status_code}).", code, r.status_code)
        return Result(status, data.get("ecocashReference"), code, ok=(code == "00" or bool(status)))

    def charge(self, msisdn, amount, correlator, reference, description="Sale") -> Result:
        body = self._merchant(amount, description, correlator, reference, "MER")
        body["endUserId"] = msisdn
        if self.s.ecocash_notify_url:
            body["notifyUrl"] = self.s.ecocash_notify_url
        res = self._call("POST", self.s.ecocash_base_url.rstrip("/") + self.s.ecocash_charge_path, body)
        res.ok = res.status.lower() == "charged"
        return res

    def lookup(self, msisdn, correlator) -> Result:
        url = f"{self.s.ecocash_base_url.rstrip('/')}/{msisdn}/transactions/amount/{correlator}"
        return self._call("GET", url)

    def refund(self, msisdn, amount, original_reference, tenant_id, sale_id, reverse=False) -> Result:
        correlator = new_correlator(tenant_id, sale_id)
        body = self._merchant(amount, "Refund", correlator, f"REF-{tenant_id}-{sale_id}-{int(time.time())}",
                              "REV" if reverse else "REF")
        body["endUserId"] = msisdn
        body["originalEcocashReference"] = original_reference
        res = self._call("POST", self.s.ecocash_base_url.rstrip("/") + "/transactions/refund/", body)
        res.ok = res.status.lower() in ("refunded", "reversed")
        return res
