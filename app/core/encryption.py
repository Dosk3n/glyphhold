from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretStorageDisabled(RuntimeError):
    pass


class SecretDecryptionError(RuntimeError):
    pass


def _private_descriptor(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise SecretDecryptionError("Key material must be a regular file owned by the service user")
    os.fchmod(fd, 0o600)


def persistent_private_key(path: Path, *, allow_create: bool = True) -> str:
    """Read/create private key material without following links or replacing lost keys."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        lock_fd = os.open(
            path.with_name("." + path.name + ".lock"), os.O_CREAT | os.O_RDWR | flags, 0o600
        )
        with os.fdopen(lock_fd, "a+") as lock:
            _private_descriptor(lock.fileno())
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                fd = os.open(path, os.O_RDONLY | flags)
            except FileNotFoundError:
                if not allow_create:
                    raise SecretDecryptionError(
                        "Encryption key is missing; restore the original key"
                    ) from None
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | flags, 0o600)
                with os.fdopen(fd, "w") as stream:
                    _private_descriptor(stream.fileno())
                    stream.write(secrets.token_urlsafe(48) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                fd = os.open(path, os.O_RDONLY | flags)
            with os.fdopen(fd, "r") as stream:
                _private_descriptor(stream.fileno())
                key = stream.read(4097).strip()
            if not key or len(key) > 4096:
                raise SecretDecryptionError("Installation key is invalid; restore the original key")
            return key
    except OSError as exc:
        raise SecretDecryptionError(
            "Cannot securely read key material; check ownership and permissions"
        ) from exc


def derive_key(purpose: str) -> str:
    return hmac.new(
        _require_key().encode(), ("glyphhold:v2:" + purpose).encode(), hashlib.sha256
    ).hexdigest()


def _require_key() -> str:
    if settings.encryption_key:
        return settings.encryption_key
    if settings.auto_encryption_key:
        return ensure_installation_key()
    else:
        raise SecretStorageDisabled(
            "Secret storage is disabled: GLYPHHOLD_ENCRYPTION_KEY is not set"
        )


def ensure_installation_key() -> str:
    """Create once, independently of SQLite, and never replace a lost encryption key."""
    path = Path(settings.db_path).parent / "encryption.key"
    key = settings.encryption_key
    existing_ids: set[str] = set()
    encrypted_sample = None
    if settings.db_path.exists():
        with sqlite3.connect(settings.db_path) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='secrets'").fetchone():
                row = conn.execute(
                    "SELECT encrypted_value FROM secrets WHERE encrypted_value != X'' LIMIT 1"
                ).fetchone()
                encrypted_sample = row[0] if row else None
                existing_ids = {
                    r[0]
                    for r in conn.execute(
                        "SELECT DISTINCT encryption_key_id FROM secrets WHERE encrypted_value != X''"
                    )
                    if r[0]
                }
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='gh2_encryption_marker'"
            ).fetchone():
                existing_ids.update(
                    r[0] for r in conn.execute("SELECT key_id FROM gh2_encryption_marker")
                )
    if key is None:
        key = persistent_private_key(path, allow_create=not (existing_ids or encrypted_sample))
    if not key:
        raise SecretDecryptionError("Installation encryption key is invalid")
    key_id = hashlib.sha256(key.encode()).hexdigest()[:16]
    if existing_ids and existing_ids != {key_id}:
        raise SecretDecryptionError(
            "Configured encryption key does not match encrypted data; restore the original key"
        )
    if encrypted_sample:
        try:
            Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())).decrypt(
                encrypted_sample
            )
        except InvalidToken as exc:
            raise SecretDecryptionError(
                "Installation key does not decrypt legacy encrypted data"
            ) from exc
    return key


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
        raise SecretDecryptionError(
            "Secret could not be decrypted with the configured key"
        ) from exc
