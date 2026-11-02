"""Encrypt tenants' stored payment secrets with a key derived from SECRET_KEY."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret_key: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))


def encrypt(value: str, secret_key: str) -> str | None:
    return _fernet(secret_key).encrypt(value.encode()).decode() if value else None


def decrypt(token: str | None, secret_key: str) -> str:
    if not token:
        return ""
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except InvalidToken:  # SECRET_KEY changed: treat as not set rather than crash
        return ""
