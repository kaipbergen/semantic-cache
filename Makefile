.PHONY: run consumer test lint fmt audit docker-up docker-down install install-dev

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

# Ignored IDs are known vulnerabilities in transitive deps (starlette via
# fastapi==0.115.0, transformers via sentence-transformers==3.0.1) that only
# close via a coordinated major-version upgrade of the top-level package -
# see the CI workflow and ROADMAP.md's Notes section.
audit:
	venv/bin/pip-audit -r requirements.txt \
		--ignore-vuln PYSEC-2026-161 \
		--ignore-vuln PYSEC-2026-248 \
		--ignore-vuln PYSEC-2026-249 \
		--ignore-vuln PYSEC-2026-1943 \
		--ignore-vuln PYSEC-2026-1941 \
		--ignore-vuln PYSEC-2026-2281 \
		--ignore-vuln PYSEC-2026-2280 \
		--ignore-vuln PYSEC-2025-217 \
		--ignore-vuln PYSEC-2026-2290 \
		--ignore-vuln PYSEC-2026-2288 \
		--ignore-vuln PYSEC-2026-2289 \
		--ignore-vuln CVE-2026-9856

docker-up:
	docker compose up -d

docker-down:
	docker compose down
