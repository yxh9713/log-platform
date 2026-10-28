FROM ghcr.io/astral-sh/uv:0.9.5 AS uv
FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project && useradd --uid 10001 --create-home app
COPY app ./app
COPY tests ./tests
COPY alembic.ini ./
COPY alembic ./alembic
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app/app", "--timeout-graceful-shutdown", "5", "--no-proxy-headers"]
