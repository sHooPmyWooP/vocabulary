"""FastAPI application: server-rendered Jinja + HTMX home page over SQLite."""
from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import dictionary_client, scheduler, stats as stats_mod, vocab_store
from app.db import connect, init_db

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Zero-state-safe home counts: total words and cards due today."""
    total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    due = vocab_store.due_count(conn, today=date.today())
    return {"total_words": total, "due_today": due}


def _card_context(entry: vocab_store.Entry) -> dict:
    """Build the render context for a review card from its stored payload.

    Stored payloads come in two shapes: the legacy dictapi raw JSON array,
    and the current canonical object. Detect by type and route accordingly.
    """
    payload = json.loads(entry.payload)
    if isinstance(payload, list):
        senses = dictionary_client._parse(entry.word, payload).senses
    else:
        senses = dictionary_client.senses_from_canonical(payload)
    return {"entry": entry, "senses": senses}


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

    @app.get("/lookup", response_class=HTMLResponse)
    def lookup_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "lookup.html", {})

    @app.post("/lookup", response_class=HTMLResponse)
    def lookup(request: Request, word: str = Form(...)) -> HTMLResponse:
        conn = app.state.conn
        result = dictionary_client.lookup(word)
        if isinstance(result, dictionary_client.LookupError):
            return templates.TemplateResponse(
                request,
                "_lookup_result.html",
                {"lookup_error": True, "word": result.word},
            )
        if isinstance(result, dictionary_client.NotFound):
            return templates.TemplateResponse(
                request,
                "_lookup_result.html",
                {"not_found": True, "word": result.word},
            )
        existed = vocab_store.get_by_word(conn, result.word) is not None
        entry = vocab_store.add_entry(
            conn, result.word, dictionary_client.to_canonical(result)
        )
        return templates.TemplateResponse(
            request,
            "_lookup_result.html",
            {
                "result": result,
                "entry": entry,
                "already_known": existed,
            },
        )

    @app.delete("/entry/{entry_id}", response_class=HTMLResponse)
    def remove_entry(request: Request, entry_id: int) -> HTMLResponse:
        vocab_store.delete_entry(app.state.conn, entry_id)
        return HTMLResponse('<p class="muted">Removed.</p>')

    @app.get("/stats", response_class=HTMLResponse)
    def stats_page(request: Request) -> HTMLResponse:
        conn = app.state.conn
        entries = vocab_store.list_entries(conn)
        reviews = vocab_store.all_reviews(conn)
        result = stats_mod.compute(entries, reviews, today=date.today())
        max_count = max((d.count for d in result.reviews_per_day), default=0)
        return templates.TemplateResponse(
            request,
            "stats.html",
            {"stats": result, "max_count": max_count},
        )

    @app.get("/browse", response_class=HTMLResponse)
    def browse_page(
        request: Request, q: str = "", sort: str = "added"
    ) -> HTMLResponse:
        entries = vocab_store.list_entries(app.state.conn, search=q or None, sort=sort)
        ctx = {"entries": entries, "q": q, "sort": sort}
        template = "_browse_list.html" if request.headers.get("HX-Request") else "browse.html"
        return templates.TemplateResponse(request, template, ctx)

    def _row_response(request: Request, entry_id: int) -> HTMLResponse:
        entry = vocab_store.get_by_id(app.state.conn, entry_id)
        return templates.TemplateResponse(request, "_browse_row.html", {"entry": entry})

    @app.get("/entry/{entry_id}/row", response_class=HTMLResponse)
    def entry_row(request: Request, entry_id: int) -> HTMLResponse:
        entry = vocab_store.get_by_id(app.state.conn, entry_id)
        if entry is None:
            return HTMLResponse("not found", status_code=404)
        return templates.TemplateResponse(request, "_browse_row.html", {"entry": entry})

    @app.get("/entry/{entry_id}/edit", response_class=HTMLResponse)
    def edit_form(request: Request, entry_id: int) -> HTMLResponse:
        entry = vocab_store.get_by_id(app.state.conn, entry_id)
        if entry is None:
            return HTMLResponse("not found", status_code=404)
        return templates.TemplateResponse(request, "_browse_edit.html", {"entry": entry})

    @app.post("/entry/{entry_id}/edit", response_class=HTMLResponse)
    def edit_entry(
        request: Request,
        entry_id: int,
        word: str = Form(...),
        note: str = Form(""),
    ) -> HTMLResponse:
        try:
            vocab_store.update_entry(app.state.conn, entry_id, word=word, note=note)
        except ValueError:
            return HTMLResponse("invalid edit", status_code=400)
        return _row_response(request, entry_id)

    def _next_card_response(request: Request) -> HTMLResponse:
        due = vocab_store.due_cards(app.state.conn, today=date.today())
        if not due:
            return templates.TemplateResponse(request, "_review_done.html", {})
        ctx = _card_context(due[0])
        ctx["remaining"] = len(due)
        return templates.TemplateResponse(request, "_review_card.html", ctx)

    @app.get("/review", response_class=HTMLResponse)
    def review_page(request: Request) -> HTMLResponse:
        due = vocab_store.due_cards(app.state.conn, today=date.today())
        ctx: dict = {"remaining": len(due)}
        if due:
            ctx.update(_card_context(due[0]))
        return templates.TemplateResponse(request, "review.html", ctx)

    @app.post("/review/{entry_id}/grade", response_class=HTMLResponse)
    def grade_card(
        request: Request, entry_id: int, grade: str = Form(...)
    ) -> HTMLResponse:
        if grade not in scheduler.GRADE_QUALITY:
            return HTMLResponse("unknown grade", status_code=400)
        vocab_store.record_review(app.state.conn, entry_id, grade)
        return _next_card_response(request)

    return app


app = create_app()
