# Contributing

Thanks for your interest in improving semantic-cache.

## Getting started

```bash
git clone https://github.com/kaipbergen/semantic-cache
cd semantic-cache
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
cp .env.example .env
```

`pre-commit install` wires up a git hook that runs `ruff check --fix` on changed files before
each commit, the same check CI's lint job runs - catching lint issues locally instead of in CI.
Run it on everything at once with `pre-commit run --all-files`.

## Running tests

```bash
pytest
```

## Troubleshooting

- **Redis connection refused**: make sure `docker-compose up` includes the `redis` service and it's healthy before starting the API.
- **FAISS index not found**: run `docker-compose down -v` once to reset volumes if the index was built with a different embedding model.

## Submitting changes

1. Fork the repo and create a branch from `main`.
2. Make your change, keeping it focused and covered by tests.
3. Open a pull request describing what changed and why.
