from __future__ import annotations

import secrets


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(16).replace('-', '').replace('_', '')[:22]}"


def new_request_id() -> str:
    return new_id("req")

