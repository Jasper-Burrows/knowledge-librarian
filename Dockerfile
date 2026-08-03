# syntax=docker/dockerfile:1.7
FROM node:26.5.1-alpine AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

FROM python:3.13.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    LIBRARIAN_DATABASE_PATH=/app/data/librarian.db \
    LIBRARIAN_FRONTEND_DIST=/app/frontend/dist
WORKDIR /app
RUN addgroup --system librarian && adduser --system --ingroup librarian librarian
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY backend/ ./backend/
RUN uv sync --frozen --no-dev --no-editable
COPY --from=web /build/frontend/dist ./frontend/dist
RUN mkdir -p /app/data && chown -R librarian:librarian /app
USER librarian
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2)"]
CMD ["uvicorn", "knowledge_librarian.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
