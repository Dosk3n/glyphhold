from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings
from app.core.request_context import get_request_id
from app.storage.repositories import auth as auth_repo
from app.storage.repositories.events import record_event
from app.storage.repositories.settings import get_session_secret

password_hasher = PasswordHasher()
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ApiPrincipal:
    key_id: str
    actor: str
    scopes: set[str]


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def generate_api_key() -> str:
    return f"gh_live_{secrets.token_urlsafe(36)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def api_key_prefix(api_key: str) -> str:
    return f"{api_key[:15]}..."


def create_api_key(
    *, name: str, actor: str, description: str | None, scopes: list[str]
) -> tuple[str, str]:
    api_key = generate_api_key()
    key_id = auth_repo.create_api_key_record(
        name=name,
        actor=actor,
        description=description,
        key_prefix=api_key_prefix(api_key),
        key_hash=hash_api_key(api_key),
        scopes=scopes,
    )
    return key_id, api_key


def _session_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_session_secret(), salt="glyphhold-dashboard-session")


def _csrf_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_session_secret(), salt="glyphhold-dashboard-csrf")


def create_session_value(user_id: str, session_version: int = 1) -> str:
    return _session_serializer().dumps(
        {"user_id": user_id, "session_version": session_version}
    )


def create_csrf_value() -> str:
    return _csrf_serializer().dumps({"nonce": secrets.token_urlsafe(32)})


def validate_csrf_value(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value or not hmac.compare_digest(cookie_value, header_value):
        return False
    try:
        _csrf_serializer().loads(cookie_value, max_age=60 * 60 * 24 * 14)
    except (BadSignature, SignatureExpired):
        return False
    return True


def load_session_payload(
    session_value: str | None, *, max_age_seconds: int = 60 * 60 * 24 * 14
) -> dict | None:
    if not session_value:
        return None
    try:
        payload = _session_serializer().loads(session_value, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return payload if isinstance(payload, dict) else None


def load_session_user_id(
    session_value: str | None, *, max_age_seconds: int = 60 * 60 * 24 * 14
) -> str | None:
    payload = load_session_payload(session_value, max_age_seconds=max_age_seconds)
    if not payload:
        return None
    return str(payload.get("user_id") or "") or None


def get_current_dashboard_user(request: Request) -> dict | None:
    payload = load_session_payload(request.cookies.get(settings.session_cookie_name))
    user_id = str(payload.get("user_id") or "") if payload else ""
    if not user_id:
        return None
    user = auth_repo.get_dashboard_user_by_id(user_id)
    if user is None:
        return None
    session_version = int(payload.get("session_version", 1))
    return user if session_version == int(user.get("session_version", 1)) else None


def require_dashboard_user(request: Request) -> dict:
    user = get_current_dashboard_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def get_api_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> ApiPrincipal:
    limiter = request.app.state.failure_rate_limiter
    limiter_key = f"invalid-api:{request.client.host if request.client else 'unknown'}"

    def register_invalid_attempt() -> None:
        retry_after = limiter.retry_after(
            limiter_key,
            limit=settings.invalid_api_key_attempts,
            window_seconds=settings.invalid_api_key_window_seconds,
        )
        if retry_after:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many invalid API authentication attempts. Wait and retry.",
                headers={"Retry-After": str(retry_after)},
            )
        limiter.add_failure(
            limiter_key, window_seconds=settings.invalid_api_key_window_seconds
        )

    if credentials is None:
        register_invalid_attempt()
        record_event(
            request_id=get_request_id(request),
            event_type="api_key.auth_failed",
            action="authenticate",
            success=False,
            message="Missing bearer API key",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer API key")

    record = auth_repo.get_api_key_by_hash(hash_api_key(credentials.credentials))
    if record is None:
        register_invalid_attempt()
        record_event(
            request_id=get_request_id(request),
            event_type="api_key.auth_failed",
            action="authenticate",
            success=False,
            message="Invalid bearer API key",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    auth_repo.touch_api_key(record["id"])
    scopes = set(json.loads(record["scopes_json"] or "[]"))
    return ApiPrincipal(key_id=record["id"], actor=record["actor"], scopes=scopes)


def require_scope(scope: str):
    def dependency(principal: Annotated[ApiPrincipal, Depends(get_api_principal)]) -> ApiPrincipal:
        if "admin" not in principal.scopes and scope not in principal.scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient API key scope")
        return principal

    return dependency
