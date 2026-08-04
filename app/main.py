"""FastAPI application: server-rendered Jinja + HTMX home page over SQLite."""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import connect, init_db

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Zero-state-safe home counts: total words and cards due today."""
    total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    due = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE due_date <= ?",
        (date.today().isoformat(),),
    ).fetchone()[0]
    return {"total_words": total, "due_today": due}


def create_app(conn: sqlite3.Connection | None = None) -> FastAPI:
    """Build the app. A connection may be injected for tests."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not hasattr(app.state, "conn"):
            app.state.conn = connect()
        init_db(app.state.conn)
        yield

    app = FastAPI(title="Vocabulary", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    if conn is not None:
        app.state.conn = conn

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        ctx = _counts(app.state.conn)
        return templates.TemplateResponse(request, "home.html", ctx)

    return app


app = create_app()
