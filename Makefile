.PHONY: run consumer test lint fmt docker-up docker-down install install-dev

install:
	venv/bin/pip install -r requirements.txt

install-dev:
	venv/bin/pip install -r requirements-dev.txt

run:
	venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

consumer:
	venv/bin/python -m app.consumer

test:
	venv/bin/python -m pytest

lint:
	venv/bin/ruff check .

fmt:
	venv/bin/ruff check --fix .

docker-up:
	docker compose up -d

docker-down:
	docker compose down
