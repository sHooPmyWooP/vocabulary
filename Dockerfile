FROM python:3.12-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# App source
COPY app ./app

ENV PATH="/app/.venv/bin:$PATH"
# SQLite DB lives on a mounted volume
ENV VOCAB_DB_PATH=/data/vocab.db
VOLUME ["/data"]

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
