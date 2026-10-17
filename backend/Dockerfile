# Two targets from one file:
#   dev      (compose): all dependency groups, code bind-mounted, runserver
#   runtime  (default): production dependencies only, code owned by root and
#            read-only for the app user, static files collected, gunicorn.
# Run the runtime image with --read-only and a tmpfs on /tmp.
# uv is pinned by version and digest; bump both together.
ARG PYTHON_IMAGE=python:3.14-slim

FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/venv/bin:$PATH"
WORKDIR /app

FROM base AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/venv UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
# --locked fails when uv.lock does not match pyproject.toml instead of re-resolving.
RUN uv sync --locked --no-dev --no-install-project

FROM build AS dev
# The app user must own what it writes in the ./backend bind mount (ruff, mypy and pytest
# caches, generated files): give it the host user's uid (compose passes APP_UID).
ARG APP_UID=1000
RUN uv sync --locked --no-install-project \
    && useradd --create-home --uid "$APP_UID" app \
    && chown -R app:app /venv
USER app
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM base AS runtime
COPY --from=build /venv /venv
# Code stays owned by root: the app user can read it but not change it.
COPY . .
RUN python -m compileall -q /app \
    && DJANGO_SETTINGS_MODULE=config.settings.production \
       DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
       DJANGO_ALLOWED_HOSTS=build.invalid DJANGO_ADMIN_PATH=build-only/ \
       DATABASE_URL=sqlite:////tmp/build.sqlite3 \
       python manage.py collectstatic --noinput -v0 \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER app
EXPOSE 8000
CMD ["gunicorn", "--config", "gunicorn.conf.py", "config.wsgi:application"]
