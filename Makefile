.PHONY: help install dev test run docker-build docker-run docker-stop clean

IMAGE ?= vocabulary
PORT ?= 8000
VOLUME ?= vocab-data

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Sync all dependencies (incl. dev) into .venv
	uv sync

dev: ## Run the app locally with autoreload
	uv run uvicorn app.main:app --reload --port $(PORT)

run: ## Run the app locally without autoreload
	uv run uvicorn app.main:app --host 0.0.0.0 --port $(PORT)

test: ## Run the test suite
	uv run pytest

docker-build: ## Build the Docker image
	docker build -t $(IMAGE) .

docker-run: ## Run the container with a persistent volume
	docker run -d --name $(IMAGE) -p $(PORT):8000 -v $(VOLUME):/data $(IMAGE)

docker-stop: ## Stop and remove the running container
	-docker rm -f $(IMAGE)

clean: ## Remove caches and local DB
	rm -rf .pytest_cache **/__pycache__ data/vocab.db
