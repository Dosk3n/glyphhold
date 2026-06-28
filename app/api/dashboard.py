from __future__ import annotations

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.core import auth
from app.storage.db import database_ok
from app.storage.migrations import current_schema_version
from app.storage.repositories import auth as auth_repo

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/dashboard/templates")

DEFAULT_SCOPES = [
    "memories:read",
    "memories:write",
    "secrets:read",
    "secrets:write",
    "secrets:reveal",
    "events:read",
]


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=status.HTTP_303_SEE_OTHER)


def _dashboard_context(request: Request, **extra: object) -> dict[str, object]:
    context = {
        "request": request,
        "settings": settings,
        "user": auth.get_current_dashboard_user(request),
    }
    context.update(extra)
    return context


@router.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request) -> HTMLResponse | RedirectResponse:
    if auth_repo.has_admin_user():
        return _redirect("/login")
    return templates.TemplateResponse(
        "setup.html",
        _dashboard_context(request, error=None),
    )


@router.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    if auth_repo.has_admin_user():
        return _redirect("/login")

    username = username.strip()
    if not username:
        return templates.TemplateResponse(
            "setup.html",
            _dashboard_context(request, error="Username is required."),
            status_code=400,
        )
    if len(password) < 12:
        return templates.TemplateResponse(
            "setup.html",
            _dashboard_context(request, error="Password must be at least 12 characters."),
            status_code=400,
        )
    if password != confirm_password:
        return templates.TemplateResponse(
            "setup.html",
            _dashboard_context(request, error="Passwords do not match."),
            status_code=400,
        )

    auth_repo.create_dashboard_user(username, auth.hash_password(password))
    return _redirect("/login")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse | RedirectResponse:
    if not auth_repo.has_admin_user():
        return _redirect("/setup")
    if auth.get_current_dashboard_user(request):
        return _redirect("/dashboard")
    return templates.TemplateResponse(
        "login.html",
        _dashboard_context(request, error=None),
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    if not auth_repo.has_admin_user():
        return _redirect("/setup")

    user = auth_repo.get_dashboard_user_by_username(username.strip())
    if user is None or not auth.verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            "login.html",
            _dashboard_context(request, error="Invalid username or password."),
            status_code=401,
        )

    auth_repo.mark_dashboard_login(user["id"])
    response = _redirect("/dashboard")
    response.set_cookie(
        settings.session_cookie_name,
        auth.create_session_value(user["id"]),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    return response


@router.post("/logout")
def logout() -> RedirectResponse:
    response = _redirect("/login")
    response.delete_cookie(settings.session_cookie_name)
    return response


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_home(request: Request) -> HTMLResponse | RedirectResponse:
    if not auth_repo.has_admin_user():
        return _redirect("/setup")
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")

    api_key_count = len(auth_repo.list_api_keys())
    return templates.TemplateResponse(
        "home.html",
        _dashboard_context(
            request,
            user=user,
            database_status="ok" if database_ok() else "error",
            schema_version=current_schema_version(),
            api_key_count=api_key_count,
        ),
    )


@router.get("/dashboard/api-keys", response_class=HTMLResponse)
def api_keys_page(request: Request) -> HTMLResponse | RedirectResponse:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    return templates.TemplateResponse(
        "api_keys.html",
        _dashboard_context(
            request,
            user=user,
            api_keys=auth_repo.list_api_keys(),
            default_scopes=DEFAULT_SCOPES,
            created_key=None,
            error=None,
        ),
    )


@router.post("/dashboard/api-keys", response_class=HTMLResponse)
def create_api_key(
    request: Request,
    name: str = Form(...),
    actor: str = Form(...),
    description: str = Form(""),
    scopes: list[str] = Form(default=[]),
) -> HTMLResponse | RedirectResponse:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")

    name = name.strip()
    actor = actor.strip()
    if not name or not actor:
        return templates.TemplateResponse(
            "api_keys.html",
            _dashboard_context(
                request,
                user=user,
                api_keys=auth_repo.list_api_keys(),
                default_scopes=DEFAULT_SCOPES,
                created_key=None,
                error="Name and actor are required.",
            ),
            status_code=400,
        )

    selected_scopes = scopes or DEFAULT_SCOPES
    key_id, api_key = auth.create_api_key(
        name=name,
        actor=actor,
        description=description.strip() or None,
        scopes=selected_scopes,
    )
    created_key = {"id": key_id, "value": api_key}
    return templates.TemplateResponse(
        "api_keys.html",
        _dashboard_context(
            request,
            user=user,
            api_keys=auth_repo.list_api_keys(),
            default_scopes=DEFAULT_SCOPES,
            created_key=created_key,
            error=None,
        ),
    )


@router.post("/dashboard/api-keys/{key_id}/disable")
def disable_api_key(request: Request, key_id: str) -> RedirectResponse:
    if auth.get_current_dashboard_user(request) is None:
        return _redirect("/login")
    auth_repo.set_api_key_enabled(key_id, False)
    return _redirect("/dashboard/api-keys")


@router.post("/dashboard/api-keys/{key_id}/enable")
def enable_api_key(request: Request, key_id: str) -> RedirectResponse:
    if auth.get_current_dashboard_user(request) is None:
        return _redirect("/login")
    auth_repo.set_api_key_enabled(key_id, True)
    return _redirect("/dashboard/api-keys")
