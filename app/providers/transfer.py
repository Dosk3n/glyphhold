"""Password-encrypted, explicit secret migration. Never part of memory exports."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.encryption import decrypt_secret, derive_key, encrypt_secret, encryption_key_id
from app.core.ids import new_id
from app.storage.db import connection
from app.utils.time import utc_now
from app.v2 import core


def _protect_legacy_fingerprints(conn: sqlite3.Connection) -> None:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='gh2_secret_imports'").fetchone()
    if not exists:
        return
    for row in conn.execute(
        "SELECT namespace,source_id,source_hash FROM gh2_secret_imports"
    ).fetchall():
        fingerprint = row["source_hash"]
        if len(fingerprint) == 64 and all(c in "0123456789abcdef" for c in fingerprint):
            conn.execute(
                "UPDATE gh2_secret_imports SET source_hash=? WHERE namespace=? AND source_id=?",
                (
                    "legacy-fernet:" + encrypt_secret(fingerprint).decode(),
                    row["namespace"],
                    row["source_id"],
                ),
            )


def migrate_legacy_fingerprints() -> None:
    """Protect old offline guessing oracles without changing imported secret values."""
    with connection() as conn:
        conn.execute("PRAGMA secure_delete=ON")
        _protect_legacy_fingerprints(conn)
    # Startup normally has exclusive access. Checkpoint replaces the original
    # pages and removes older WAL frames; existing external backups stay private.
    with connection() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _fingerprint(item: dict) -> str:
    return (
        "hmac-sha256-v1:"
        + hmac.new(
            bytes.fromhex(derive_key("secret-transfer-fingerprint")),
            json.dumps(item, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()
    )


def transfer_cipher(password: str, salt: bytes) -> Fernet:
    if len(password) < 12:
        raise ValueError("Transfer passphrase must contain at least 12 characters")
    return Fernet(
        base64.urlsafe_b64encode(
            PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(
                password.encode()
            )
        )
    )


def export_secrets(source: Path, source_key: str, password: str) -> dict:
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(source_key.encode()).digest()))
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        table = "gh2_secret_handles" if "gh2_secret_handles" in tables else "secrets"
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    items = []
    for row in rows:
        if row.get("provider", "builtin") != "builtin":
            raise ValueError(
                "External handles must be deliberately relinked at the destination; this transfer only exports built-in values"
            )
        try:
            value = cipher.decrypt(row.pop("encrypted_value")).decode()
        except InvalidToken as exc:
            raise ValueError("Source key does not decrypt this installation") from exc
        items.append(
            {
                "source_id": row["id"],
                "name": row["name"],
                "value": value,
                "description": row.get("description"),
                "value_type": row.get("value_type", "text"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "legacy_metadata": {
                    k: v for k, v in row.items() if k not in {"account_id", "encryption_key_id"}
                },
            }
        )
    salt = secrets.token_bytes(16)
    encrypted = (
        transfer_cipher(password, salt).encrypt(json.dumps({"secrets": items}).encode()).decode()
    )
    return {
        "format": "glyphhold-encrypted-secret-transfer-v1",
        "salt": base64.b64encode(salt).decode(),
        "ciphertext": encrypted,
        "count": len(items),
    }


def decrypt_package(package: dict, password: str) -> list[dict]:
    if package.get("format") != "glyphhold-encrypted-secret-transfer-v1":
        raise ValueError("Unsupported secret transfer format")
    try:
        salt = base64.b64decode(package["salt"], validate=True)
        if len(salt) != 16:
            raise ValueError("Invalid salt")
        items = json.loads(transfer_cipher(password, salt).decrypt(package["ciphertext"].encode()))[
            "secrets"
        ]
    except (ValueError, KeyError, TypeError, InvalidToken) as exc:
        raise ValueError("Transfer cannot be decrypted; check its passphrase and format") from exc
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError("Invalid transfer records")
    for item in items:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) and item[k] for k in ("source_id", "name", "value")
        ):
            raise ValueError("Invalid transfer record")
    if len({i["source_id"] for i in items}) != len(items) or len({i["name"] for i in items}) != len(
        items
    ):
        raise ValueError("Duplicate transfer identities or names; split the source by space")
    return items


def import_package(
    package: dict, password: str, namespace: str, space_id: str, *, apply: bool = False
) -> dict:
    if not namespace or len(namespace) > 200:
        raise ValueError("A stable source namespace is required")
    core.require_space(core.ADMIN, space_id, write=True)
    items = decrypt_package(package, password)
    report = {"new": 0, "existing": 0, "conflicts": [], "items": [], "space_id": space_id}
    now = utc_now()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS gh2_secret_imports(namespace TEXT NOT NULL,source_id TEXT NOT NULL,handle_id TEXT NOT NULL,source_hash TEXT NOT NULL,PRIMARY KEY(namespace,source_id))"
        )
        _protect_legacy_fingerprints(conn)
        pending = []
        for item in items:
            digest = _fingerprint(item)
            previous = conn.execute(
                "SELECT * FROM gh2_secret_imports WHERE namespace=? AND source_id=?",
                (namespace, item["source_id"]),
            ).fetchone()
            if previous:
                report["existing"] += 1
                previous_hash = previous["source_hash"]
                if previous_hash.startswith("legacy-fernet:"):
                    old_digest = decrypt_secret(
                        previous_hash.removeprefix("legacy-fernet:").encode()
                    )
                    matched = hmac.compare_digest(
                        old_digest,
                        hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest(),
                    )
                    if matched and apply:
                        conn.execute(
                            "UPDATE gh2_secret_imports SET source_hash=? WHERE namespace=? AND source_id=?",
                            (digest, namespace, item["source_id"]),
                        )
                else:
                    matched = hmac.compare_digest(previous_hash, digest)
                if not matched:
                    report["conflicts"].append(
                        {"name": item["name"], "reason": "Source changed after an earlier import"}
                    )
                continue
            if conn.execute(
                "SELECT 1 FROM gh2_secret_handles WHERE name=? AND space_id=?",
                (item["name"], space_id),
            ).fetchone():
                report["conflicts"].append(
                    {"name": item["name"], "reason": "Destination name already exists"}
                )
                continue
            report["new"] += 1
            report["items"].append(
                {"name": item["name"], "value_type": item.get("value_type", "text")}
            )
            pending.append((item, digest))
        if apply:
            if report["conflicts"]:
                raise ValueError("Resolve transfer conflicts before importing any values")
            for item, digest in pending:
                sid = new_id("sec")
                conn.execute(
                    "INSERT INTO gh2_secret_handles(id,name,space_id,description,value_type,provider,encrypted_value,version,created_at,updated_at) VALUES (?,?,?,?,?,'builtin',?,1,?,?)",
                    (
                        sid,
                        item["name"],
                        space_id,
                        item.get("description"),
                        item.get("value_type", "text"),
                        encrypt_secret(item["value"]),
                        item.get("created_at", now),
                        item.get("updated_at", now),
                    ),
                )
                conn.execute(
                    "INSERT INTO gh2_secret_imports VALUES (?,?,?,?)",
                    (namespace, item["source_id"], sid, digest),
                )
                conn.execute(
                    "INSERT INTO gh2_secret_provenance VALUES (?,?)",
                    (
                        sid,
                        json.dumps(
                            {
                                "source_namespace": namespace,
                                "source_id": item["source_id"],
                                "legacy_metadata": item.get("legacy_metadata", {}),
                            }
                        ),
                    ),
                )
            conn.execute(
                "INSERT OR IGNORE INTO gh2_encryption_marker VALUES (?)", (encryption_key_id(),)
            )
    return report
