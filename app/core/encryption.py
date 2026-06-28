from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretStorageDisabled(RuntimeError):
    pass


class SecretDecryptionError(RuntimeError):
    pass


def _require_key() -> str:
    if not settings.encryption_key:
        raise SecretStorageDisabled("Secret storage is disabled: TOMEWARDEN_ENCRYPTION_KEY is not set")
    return settings.encryption_key


def _fernet() -> Fernet:
    raw_key = _require_key().encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest())
    return Fernet(key)


def encryption_key_id() -> str:
    raw_key = _require_key().encode("utf-8")
    return hashlib.sha256(raw_key).hexdigest()[:16]


def encrypt_secret(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt_secret(encrypted_value: bytes) -> str:
    try:
        return _fernet().decrypt(encrypted_value).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError("Secret could not be decrypted with the configured key") from exc

