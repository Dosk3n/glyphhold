from __future__ import annotations

import hashlib
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
from app.storage.repositories import auth as auth_repo
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
    return f"tw_live_{secrets.token_urlsafe(36)}"


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
    return URLSafeTimedSerializer(get_session_secret(), salt="tomewarden-dashboard-session")


def create_session_value(user_id: str) -> str:
    return _session_serializer().dumps({"user_id": user_id})


def load_session_user_id(session_value: str | None, *, max_age_seconds: int = 60 * 60 * 24 * 14) -> str | None:
    if not session_value:
        return None
    try:
        payload = _session_serializer().loads(session_value, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return str(payload.get("user_id") or "") or None


def get_current_dashboard_user(request: Request) -> dict | None:
    user_id = load_session_user_id(request.cookies.get(settings.session_cookie_name))
    if not user_id:
        return None
    return auth_repo.get_dashboard_user_by_id(user_id)


def require_dashboard_user(request: Request) -> dict:
    user = get_current_dashboard_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def get_api_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> ApiPrincipal:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer API key")

    record = auth_repo.get_api_key_by_hash(hash_api_key(credentials.credentials))
    if record is None:
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

