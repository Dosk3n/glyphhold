from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])

INDEX_PATH = Path("app/dashboard/static/dashboard/index.html")


def _spa_index() -> HTMLResponse:
    if INDEX_PATH.exists():
        return HTMLResponse(INDEX_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
          <head><meta charset="utf-8"><title>Glyph Hold</title></head>
          <body>
            <div id="root">Dashboard assets have not been built yet.</div>
          </body>
        </html>
        """.strip()
    )


@router.get("/", include_in_schema=False)
def root() -> HTMLResponse:
    return _spa_index()


@router.get("/setup", include_in_schema=False)
def setup() -> HTMLResponse:
    return _spa_index()


@router.get("/login", include_in_schema=False)
def login() -> HTMLResponse:
    return _spa_index()


@router.get("/dashboard", include_in_schema=False)
def dashboard() -> HTMLResponse:
    return _spa_index()


@router.get("/dashboard/{path:path}", include_in_schema=False)
def dashboard_catchall(path: str) -> HTMLResponse:
    return _spa_index()
