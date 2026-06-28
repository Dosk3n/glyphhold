from __future__ import annotations

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.core import auth
from app.core.request_context import get_request_id
from app.storage.db import database_ok
from app.storage.migrations import current_schema_version
from app.storage.repositories import auth as auth_repo
from app.storage.repositories import categories, memories
from app.storage.repositories import events as events_repo
from app.storage.repositories import secrets as secrets_repo
from app.storage.repositories.events import record_event
from app.storage.repositories.secrets import VALUE_TYPES

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


def _render(
    request: Request,
    template_name: str,
    *,
    status_code: int = 200,
    **extra: object,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template_name,
        _dashboard_context(request, **extra),
        status_code=status_code,
    )


@router.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request) -> Response:
    if auth_repo.has_admin_user():
        return _redirect("/login")
    return _render(request, "setup.html", error=None)


@router.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    if auth_repo.has_admin_user():
        return _redirect("/login")

    username = username.strip()
    if not username:
        return _render(request, "setup.html", error="Username is required.", status_code=400)
    if len(password) < 12:
        return _render(
            request,
            "setup.html",
            error="Password must be at least 12 characters.",
            status_code=400,
        )
    if password != confirm_password:
        return _render(request, "setup.html", error="Passwords do not match.", status_code=400)

    auth_repo.create_dashboard_user(username, auth.hash_password(password))
    return _redirect("/login")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    if not auth_repo.has_admin_user():
        return _redirect("/setup")
    if auth.get_current_dashboard_user(request):
        return _redirect("/dashboard")
    return _render(request, "login.html", error=None)


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    if not auth_repo.has_admin_user():
        return _redirect("/setup")

    user = auth_repo.get_dashboard_user_by_username(username.strip())
    if user is None or not auth.verify_password(password, user["password_hash"]):
        return _render(
            request,
            "login.html",
            error="Invalid username or password.",
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
def dashboard_home(request: Request) -> Response:
    if not auth_repo.has_admin_user():
        return _redirect("/setup")
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")

    api_key_count = len(auth_repo.list_api_keys())
    return _render(
        request,
        "home.html",
        user=user,
        database_status="ok" if database_ok() else "error",
        schema_version=current_schema_version(),
        api_key_count=api_key_count,
    )


@router.get("/dashboard/api-keys", response_class=HTMLResponse)
def api_keys_page(request: Request) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    return _render(
        request,
        "api_keys.html",
        user=user,
        api_keys=auth_repo.list_api_keys(),
        default_scopes=DEFAULT_SCOPES,
        created_key=None,
        error=None,
    )


@router.post("/dashboard/api-keys", response_class=HTMLResponse)
def create_api_key(
    request: Request,
    name: str = Form(...),
    actor: str = Form(...),
    description: str = Form(""),
    scopes: list[str] = Form(default=[]),
) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")

    name = name.strip()
    actor = actor.strip()
    if not name or not actor:
        return _render(
            request,
            "api_keys.html",
            user=user,
            api_keys=auth_repo.list_api_keys(),
            default_scopes=DEFAULT_SCOPES,
            created_key=None,
            error="Name and actor are required.",
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
    return _render(
        request,
        "api_keys.html",
        user=user,
        api_keys=auth_repo.list_api_keys(),
        default_scopes=DEFAULT_SCOPES,
        created_key=created_key,
        error=None,
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


@router.get("/dashboard/categories", response_class=HTMLResponse)
def categories_page(request: Request) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    return _render(request, "categories.html", user=user, categories=categories.list_categories(), error=None)


@router.post("/dashboard/categories", response_class=HTMLResponse)
def create_category_from_dashboard(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    allow_auto_prefetch: str | None = Form(None),
    agent_can_create: str | None = Form(None),
    agent_can_write: str | None = Form(None),
) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    try:
        categories.create_category(
            name=name.strip(),
            description=description.strip() or None,
            allow_auto_prefetch=allow_auto_prefetch == "on",
            agent_can_create=agent_can_create == "on",
            agent_can_write=agent_can_write == "on",
        )
    except Exception as exc:
        return _render(
            request,
            "categories.html",
            user=user,
            categories=categories.list_categories(),
            error=str(exc),
            status_code=400,
        )
    return _redirect("/dashboard/categories")


@router.get("/dashboard/memories", response_class=HTMLResponse)
def memories_page(
    request: Request,
    q: str = "",
    category: str | None = None,
) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    if q.strip():
        memory_rows = memories.search_memories(query=q, category=category, limit=50)
    else:
        memory_rows = memories.list_memories(category=category, limit=100)
    return _render(
        request,
        "memories.html",
        user=user,
        memories=memory_rows,
        categories=categories.list_categories(),
        selected_category=category or "",
        q=q,
        error=None,
    )


@router.post("/dashboard/memories", response_class=HTMLResponse)
def create_memory_from_dashboard(
    request: Request,
    category_id: str = Form(...),
    title: str = Form(...),
    summary: str = Form(""),
    body: str = Form(...),
    tags: str = Form(""),
    confidence: int = Form(3),
    auto_prefetch_level: str = Form("normal"),
) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    tag_list = [item.strip() for item in tags.split(",") if item.strip()]
    memories.create_memory(
        category_id=category_id,
        title=title.strip(),
        summary=summary.strip() or None,
        body=body.strip(),
        tags=tag_list,
        source="dashboard",
        confidence=confidence,
        auto_prefetch_level=auto_prefetch_level,
    )
    return _redirect("/dashboard/memories")


@router.get("/dashboard/memories/{memory_id}", response_class=HTMLResponse)
def memory_detail(request: Request, memory_id: str) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    memory = memories.get_memory(memory_id)
    if memory is None:
        return _redirect("/dashboard/memories")
    return _render(
        request,
        "memory_detail.html",
        user=user,
        memory=memory,
        revisions=memories.list_revisions(memory_id),
    )


@router.post("/dashboard/memories/{memory_id}/archive")
def archive_memory_from_dashboard(request: Request, memory_id: str) -> RedirectResponse:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    memories.archive_memory(memory_id, changed_by=user["username"])
    return _redirect("/dashboard/memories")


@router.get("/dashboard/activity", response_class=HTMLResponse)
def activity_page(
    request: Request,
    actor: str | None = None,
    event_type: str | None = None,
) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    return _render(
        request,
        "activity.html",
        user=user,
        events=events_repo.list_events(actor=actor, event_type=event_type, limit=100),
        actor=actor or "",
        event_type=event_type or "",
    )


@router.get("/dashboard/secrets", response_class=HTMLResponse)
def secrets_page(
    request: Request,
    query: str | None = None,
    service: str | None = None,
    host: str | None = None,
    scope: str | None = None,
) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    return _render(
        request,
        "secrets.html",
        user=user,
        secrets=secrets_repo.list_secrets(query=query, service=service, host=host, scope=scope),
        query=query or "",
        service=service or "",
        host=host or "",
        scope=scope or "",
        value_types=VALUE_TYPES,
        revealed=None,
        error=None,
    )


@router.post("/dashboard/secrets", response_class=HTMLResponse)
def create_secret_from_dashboard(
    request: Request,
    name: str = Form(...),
    value: str = Form(...),
    description: str = Form(""),
    value_type: str = Form("text"),
    service: str = Form(""),
    host: str = Form(""),
    scope: str = Form(""),
    tags: str = Form(""),
) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    tag_list = [item.strip() for item in tags.split(",") if item.strip()]
    try:
        secret = secrets_repo.create_secret(
            name=name.strip(),
            value=value,
            description=description.strip() or None,
            value_type=value_type.strip() or "text",
            service=service.strip() or None,
            host=host.strip() or None,
            scope=scope.strip() or None,
            tags=tag_list,
        )
    except Exception as exc:
        return _render(
            request,
            "secrets.html",
            user=user,
            secrets=secrets_repo.list_secrets(),
            query="",
            service="",
            host="",
            scope="",
            value_types=VALUE_TYPES,
            revealed=None,
            error=str(exc),
            status_code=400,
        )
    record_event(
        request_id=get_request_id(request),
        event_type="secret.create",
        actor=user["username"],
        target_type="secret",
        target_id=secret["name"],
        action="create",
        success=True,
        message=secret["name"],
    )
    return _redirect("/dashboard/secrets")


@router.post("/dashboard/secrets/{id_or_name}/reveal", response_class=HTMLResponse)
def reveal_secret_from_dashboard(request: Request, id_or_name: str) -> Response:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        return _redirect("/login")
    try:
        secret, value = secrets_repo.reveal_secret(id_or_name)
    except Exception as exc:
        return _render(
            request,
            "secrets.html",
            user=user,
            secrets=secrets_repo.list_secrets(),
            query="",
            service="",
            host="",
            scope="",
            value_types=VALUE_TYPES,
            revealed=None,
            error=str(exc),
            status_code=400,
        )
    if secret is None:
        return _redirect("/dashboard/secrets")
    record_event(
        request_id=get_request_id(request),
        event_type="secret.reveal",
        actor=user["username"],
        target_type="secret",
        target_id=secret["name"],
        action="reveal",
        success=True,
        purpose="dashboard reveal",
    )
    return _render(
        request,
        "secrets.html",
        user=user,
        secrets=secrets_repo.list_secrets(),
        query="",
        service="",
        host="",
        scope="",
        value_types=VALUE_TYPES,
        revealed={"name": secret["name"], "value": value},
        error=None,
    )
