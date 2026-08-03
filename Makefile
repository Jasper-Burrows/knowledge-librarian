.PHONY: install dev api web format lint typecheck test test-e2e test-live build check security live-estimate clean

install:
	uv sync --all-extras
	cd frontend && npm ci

dev:
	@set -eu; \
	uv run librarian serve --reload & api_pid=$$!; \
	(cd frontend && npm run dev) & web_pid=$$!; \
	cleanup() { kill "$$api_pid" "$$web_pid" 2>/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	wait "$$api_pid" "$$web_pid"

api:
	uv run librarian serve --reload

web:
	cd frontend && npm run dev

format:
	uv run ruff format backend
	uv run ruff check --fix backend

lint:
	uv run ruff format --check backend
	uv run ruff check backend
	cd frontend && npm run lint

typecheck:
	uv run mypy
	cd frontend && npm run typecheck

test:
	uv run pytest
	cd frontend && npm test

test-e2e:
	cd frontend && npm run test:e2e

test-live:
	uv run pytest -m live -vv --no-cov

build:
	cd frontend && npm run build
	docker build -t knowledge-librarian:local .

check: lint typecheck test
	cd frontend && npm run build

security:
	uv export --frozen --all-extras --no-hashes --no-emit-project --output-file /tmp/knowledge-librarian-audit.txt
	uvx pip-audit --requirement /tmp/knowledge-librarian-audit.txt
	cd frontend && npm audit --audit-level=high
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks dir --no-banner --redact .; \
	else \
		echo "gitleaks is not installed locally; the required Gitleaks CI job remains authoritative."; \
	fi

live-estimate:
	uv run librarian live-estimate

clean:
	uv cache clean
	cd frontend && npm run build -- --emptyOutDir
