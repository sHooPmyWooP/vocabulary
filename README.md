# Vocabulary Memorization Webapp

Single-user, self-hosted webapp to look up English words while reading and drill
them back into long-term memory with SM-2 spaced repetition. FastAPI + Uvicorn,
SQLite, server-rendered Jinja + HTMX. Runs as one Docker container.

See [PRD.md](PRD.md) for the full product and architecture spec.

## Stack

- Python 3.12, [uv](https://docs.astral.sh/uv/) for env/deps
- FastAPI + Uvicorn
- SQLite (on a mounted volume)
- Jinja templates + HTMX, plain responsive CSS (no JS build step, no SPA)

## Local development

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000. The home page shows "due today" and "total words"
counts (zero-state until words are captured).

The database path defaults to `data/vocab.db` and can be overridden with the
`VOCAB_DB_PATH` environment variable.

## Tests

```bash
uv run pytest
```

## Docker

Build the image:

```bash
docker build -t vocabulary .
```

Run with a mounted volume so the SQLite database persists across restarts:

```bash
docker run -d --name vocabulary \
  -p 8000:8000 \
  -v vocab-data:/data \
  vocabulary
```

The app listens on port 8000. The SQLite database lives at `/data/vocab.db`
inside the container, backed by the `vocab-data` volume, so data survives
container restarts and rebuilds. Schema bootstrapping runs automatically on
startup.
