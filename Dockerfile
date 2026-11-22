# syntax=docker/dockerfile:1

# Stage 1: frontend build, producing web/dist.
# Runs on $BUILDPLATFORM: the output is architecture-neutral, so building under
# QEMU for arm64 would only slow multi-arch builds down.
# Manifest-list digest (amd64 and arm64), from
# `docker buildx imagetools inspect node:22-slim` on 2026-06-12.
FROM --platform=$BUILDPLATFORM node:22-slim@sha256:e21fc383b50d5347dc7a9f1cae45b8f4e2f0d39f7ade28e4eef7d2934522b752 AS frontend-builder

WORKDIR /web

# Manifests first so the npm layer stays cached when only source changes.
COPY web/package.json web/package-lock.json web/.npmrc ./

RUN npm ci

COPY web/ ./

RUN npm run build

# Stage 2: build the wheelhouse and run the tests.
# Runs on the target platform so native wheels match the runtime image. Wheels
# are built here, where a compiler exists, so the final stage never needs one,
# even for an arm64 dependency with no prebuilt wheel.
# Manifest-list digest (amd64 and arm64), from
# `docker buildx imagetools inspect python:3.11-slim` on 2026-06-12.
FROM python:3.11-slim@sha256:f9fa7f851e38bfb19c9de3afbc4b86ae7176ea7aaf94535c31df5458d5849457 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml requirements-dev.txt ./

# tests/ is copied later so test-only edits do not bust the wheelhouse cache.
COPY src/ ./src/

# Production wheelhouse: the project and its runtime deps, not the dev deps.
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

COPY tests/ ./tests/

# The dev toolchain exists only to run the suite, so the whole step is gated.
# CI passes RUN_TESTS=0 because its `tests` job already runs pytest natively;
# re-running it here, emulated per architecture, would be slow and redundant.
ARG RUN_TESTS=1
RUN if [ "$RUN_TESTS" = "1" ]; then \
        pip install --no-cache-dir -r requirements-dev.txt \
        && pip install --no-cache-dir --no-index --find-links=/wheels paperless-ai \
        && pytest -n auto; \
    fi

# Stage 3: runtime image with no build toolchain; dependencies are installed
# offline from the wheelhouse.
FROM python:3.11-slim@sha256:f9fa7f851e38bfb19c9de3afbc4b86ae7176ea7aaf94535c31df5458d5849457

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# No libgl1/libglib2.0-0: Pillow and pdf2image (poppler) do not link libGL.
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Venv and code are installed as root and stay read-only to appuser, so the
# running app cannot rewrite its own code. Only /data is writable by it.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /app

RUN python3 -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir --upgrade pip

# --no-index: nothing comes from PyPI and no source build can run.
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index --find-links=/wheels paperless-ai

# Where INDEX_DB_PATH and APP_DB_PATH point by default; a new volume mounted
# here inherits this ownership.
RUN mkdir /data && chown appuser:appgroup /data

# Installed as a package, the server's relative-path fallback would resolve
# inside site-packages, not /app.
ENV FRONTEND_DIST=/app/web/dist

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# glibc defaults to 8 x NCPU malloc arenas, each retaining freed heap across the
# long-lived threaded daemons; two keeps steady-state RSS down.
ENV MALLOC_ARENA_MAX=2

COPY --from=frontend-builder /web/dist ./web/dist

USER appuser

# The OCR daemon by default; the same image runs the other daemons by command.
CMD ["paperless-ai"]
