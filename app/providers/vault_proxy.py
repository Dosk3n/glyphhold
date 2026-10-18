"""Live secret provider operations. Vault values never enter Glyph Hold's database."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

from fastapi import HTTPException

from app.core.encryption import derive_key
from app.providers import vault as provider


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,199}", value):
        raise HTTPException(400, "Invalid vault item or folder ID")
    return value


def available_fields(item: dict) -> list[str]:
    fields = ["notes"] if isinstance(item.get("notes"), str) else []
    for group, names in {
        "login": ["username", "password", "totp"],
        "sshKey": ["privateKey", "publicKey", "keyFingerprint"],
        "card": ["cardholderName", "number", "brand", "expMonth", "expYear", "code"],
        "identity": [
            "title",
            "firstName",
            "middleName",
            "lastName",
            "address1",
            "address2",
            "address3",
            "city",
            "state",
            "postalCode",
            "country",
            "company",
            "email",
            "phone",
            "ssn",
            "username",
            "passportNumber",
            "licenseNumber",
        ],
    }.items():
        fields.extend(
            f"{group}.{key}" for key in names if isinstance((item.get(group) or {}).get(key), str)
        )
    names = [f.get("name") for f in item.get("fields") or []]
    fields.extend(
        "custom:" + name for name in names if isinstance(name, str) and names.count(name) == 1
    )
    return fields


def default_field(item: dict) -> str | None:
    fields = available_fields(item)
    for preferred in ("login.password", "sshKey.privateKey"):
        if preferred in fields:
            return preferred
    if len(fields) == 1:
        return fields[0]
    return None


def version(item: dict) -> str:
    # Opaque keyed fingerprint detects concurrent changes without publishing a
    # hash of low-entropy secret values. Bitwarden edits have no conditional API.
    return hmac.new(
        derive_key("vault-item-version").encode(),
        json.dumps(item, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def reference(item_id: str) -> str:
    return (
        "vw:"
        + provider.account_id(provider.get_config(private=True))[:24]
        + ":"
        + identifier(item_id)
    )


def decode_reference(value: str) -> str:
    pieces = value.split(":")
    if (
        len(pieces) != 3
        or pieces[0] != "vw"
        or pieces[1] != provider.account_id(provider.get_config(private=True))[:24]
    ):
        raise HTTPException(409, "Secret belongs to a different vault account; search again")
    return identifier(pieces[2])


def website_origin(value: str) -> tuple[str, str] | None:
    """Safe discovery metadata: never return URL credentials, paths or tokens."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value if "://" in value or value.startswith("//") else "//" + value)
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode().casefold()
        if not host or not re.fullmatch(r"[a-z0-9_.:-]+", host):
            return None
        port = parsed.port
        if port == {"https": 443, "http": 80, "ssh": 22, "ftp": 21}.get(parsed.scheme.casefold()):
            port = None
        display = "[" + host + "]" if ":" in host else host
        origin = ((parsed.scheme.casefold() + "://") if parsed.scheme else "") + display
        if port is not None:
            origin += ":" + str(port)
        return origin, host
    except (ValueError, UnicodeError):
        return None


def websites(item: dict) -> dict:
    origins, hosts = [], []
    for entry in (item.get("login") or {}).get("uris") or []:
        parsed = website_origin(entry.get("uri")) if isinstance(entry, dict) else None
        if parsed:
            origin, host = parsed
            if origin not in origins:
                origins.append(origin)
            if host not in hosts:
                hosts.append(host)
    return {"websites": origins, "hostnames": hosts}


def matches(row: dict, query: str) -> bool:
    query = query.strip().casefold()
    text = " ".join(
        [
            row["name"],
            row.get("description") or "",
            row.get("folder_name") or "",
            *row.get("websites", []),
            *row.get("hostnames", []),
        ]
    ).casefold()
    if query in text:
        return True
    # A complete saved website URL can include a path/query that we deliberately
    # exclude from metadata. Match its safe origin; ambiguous matches stay distinct.
    parsed = website_origin(query)
    return bool(
        parsed
        and (
            parsed[0] in [w.casefold() for w in row.get("websites", [])]
            or ("://" not in query and parsed[1] in row.get("hostnames", []))
        )
    )


def metadata(item: dict, folder_names: dict | None = None) -> dict:
    return {
        "id": reference(item["id"]),
        "name": item.get("name") or "Untitled item",
        "provider": "vaultwarden",
        "space_id": None,
        "description": None,
        "folder_id": item.get("folderId"),
        "folder_name": (folder_names or {}).get(item.get("folderId")),
        "item_type": item.get("type"),
        "value_type": {1: "password", 2: "text", 3: "card", 4: "identity", 5: "ssh_key"}.get(
            item.get("type"), "text"
        ),
        "fields": available_fields(item),
        "default_field": default_field(item),
        "version": version(item),
        "created_at": item.get("creationDate"),
        "updated_at": item.get("revisionDate"),
        "direct": True,
        **websites(item),
    }


def list_items() -> list[dict]:
    rows = provider.vault.call(["list", "items"])
    if not isinstance(rows, list):
        raise provider.VaultError("Vault returned an invalid item list")
    return [r for r in rows if not r.get("deletedDate")]


def get_item(item_id: str) -> dict:
    item = provider.vault.call(["get", "item", identifier(item_id)])
    if not isinstance(item, dict) or item.get("id") != item_id or item.get("deletedDate"):
        raise HTTPException(404, "Vault item not found")
    return item


def folders() -> list[dict]:
    return [
        {"id": identifier(f["id"]), "name": f.get("name", "")}
        for f in provider.vault.call(["list", "folders"])
        if f.get("id")
    ]


def folder_destination(folder_id: str | None, explicit: bool = False) -> str | None:
    chosen = folder_id if explicit else provider.get_config(private=True).get("default_folder_id")
    if not chosen:
        return None
    identifier(chosen)
    if chosen not in {f["id"] for f in folders()}:
        raise HTTPException(409, "Folder no longer exists; list folders and choose again")
    return chosen


def ensure_unique(name: str, rows: list[dict]) -> None:
    if any((r.get("name") or "").strip().casefold() == name.strip().casefold() for r in rows):
        raise HTTPException(
            409,
            "A secret with this name already exists; search and use its ID instead of creating a duplicate",
        )


def create(fields: dict) -> dict:
    with provider.vault.lock:
        ensure_unique(fields["name"], list_items())
        folder = folder_destination(fields.get("folder_id"), "folder_id" in fields)
        item = {
            "type": 2,
            "name": fields["name"],
            "folderId": folder,
            "secureNote": {"type": 0},
            "notes": fields["value"],
        }
        # Password entries are native logins. Other single-value secrets are
        # secure notes; existing multi-field entries retain their native type.
        if fields.get("value_type") == "password":
            item.update(
                type=1,
                login={
                    "username": fields.get("username") or "",
                    "password": fields["value"],
                    "uris": [{"uri": fields["uri"], "match": None}] if fields.get("uri") else [],
                },
                notes=None,
            )
            item.pop("secureNote")
        return provider.vault.call(["create", "item"], payload=item, write=True)


def selected_field(item: dict, field: str | None) -> str:
    selected = field or default_field(item)
    if not selected or selected not in available_fields(item):
        raise HTTPException(400, "Choose one of the fields returned by secret metadata")
    return selected
