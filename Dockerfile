# CountingCarbon: Django + Gunicorn image.
# Build:  docker compose build
# Static files are collected at build time and served by WhiteNoise.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# collectstatic needs settings to import; this throwaway key is never used at runtime
RUN DJANGO_SETTINGS_MODULE=countingcarbon.settings.prod \
    SECRET_KEY=collectstatic-build-only \
    python manage.py collectstatic --no-input

# Gunicorn's control server needs a writable $HOME
RUN useradd --system --uid 1000 --create-home app && chown -R app /app/staticfiles
USER app

ENV DJANGO_SETTINGS_MODULE=countingcarbon.settings.prod

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "countingcarbon.wsgi", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--threads", "2", \
     "--access-logfile", "-", "--error-logfile", "-"]
