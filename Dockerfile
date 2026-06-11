# syntax=docker/dockerfile:1

# Stage 1: Frontend Builder
# Runs npm ci + vite build in a Node environment, producing web/dist.
# Pinned to the BUILD host's native architecture ($BUILDPLATFORM) rather than the
# target platform: the frontend build emits architecture-neutral static assets,
# so running the Node toolchain under QEMU emulation when cross-building the
# linux/arm64 image would needlessly slow every multi-arch build for an
# identical output.
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend-builder

WORKDIR /web

# Copy dependency manifests first so the npm layer is cached when only
# source files change.
COPY web/package.json web/package-lock.json web/.npmrc ./

RUN npm ci

# Copy the rest of the frontend source and build.
COPY web/ ./

RUN npm run build

# ---------------------------------------------------------------------

# Stage 2: Builder, tester and wheel factory
# Runs on the TARGET platform so any native wheels it builds match the runtime
# image's architecture. Installs the full dev toolchain, runs the test suite,
# then builds a wheelhouse for the production dependency closure. Building wheels
# HERE — where a C/Rust toolchain exists — means the final stage never needs a
# compiler, even on linux/arm64 where a dependency might lack a prebuilt
# manylinux aarch64 wheel and would otherwise have to compile from an sdist.
FROM python:3.11-slim AS builder

# Install system dependencies required for building Python packages and running tests
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create a virtual environment to isolate dependencies
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Upgrade pip to the latest version
RUN pip install --no-cache-dir --upgrade pip

# Copy dependency definitions
COPY pyproject.toml requirements-dev.txt ./

# Copy only the application source first — tests/ is kept separate so that
# test-only edits do not bust the wheelhouse build cache.
COPY src/ ./src/

# Build the production wheelhouse (the project plus its runtime deps from
# pyproject — NOT the dev deps). Any dependency lacking a prebuilt wheel for this
# platform is compiled into a wheel here, where the toolchain exists, so the
# final stage never needs a compiler on any architecture. Placed before the
# COPY tests/ and RUN_TESTS arg so this layer caches identically whether or
# not tests change or run.
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

# Copy tests only after the wheelhouse is built; tests/ is not part of the
# installed package (pyproject packages.find where=['src']), so it must not
# sit above the pip wheel step or any test edit would bust the wheel cache.
COPY tests/ ./tests/

# Test gate. The dev toolchain and the app install exist solely to run the suite,
# so the entire step — not just `pytest` — is gated behind RUN_TESTS. CI passes
# RUN_TESTS=0 because the dedicated `tests` job already runs pytest once,
# natively; re-running it here (emulated, once per target architecture) would be
# slow and redundant. A plain `docker build` defaults to RUN_TESTS=1 and keeps
# the gate. The app is installed from the wheelhouse (offline) rather than
# resolving the dependency tree a second time.
ARG RUN_TESTS=1
RUN if [ "$RUN_TESTS" = "1" ]; then \
        pip install --no-cache-dir -r requirements-dev.txt \
        && pip install --no-cache-dir --no-index --find-links=/wheels paperless-ai \
        && pytest -n auto; \
    fi

# ---------------------------------------------------------------------

# Stage 3: Final Production Image
# Lean runtime image with NO build toolchain. Production dependencies are
# installed from the prebuilt wheelhouse (offline, --no-index), so this stage
# needs neither a compiler nor network access to PyPI on any architecture.
FROM python:3.11-slim

# Create a non-root user and group for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Install only essential runtime system dependencies.
# libgl1 and libglib2.0-0 are omitted: the image path is Pillow +
# pdf2image→poppler (pdftoppm), none of which link libGL; nothing in src/
# imports cv2/opencv/Qt/OpenGL.
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Working directory and venv path. Pre-create BOTH directories owned by appuser
# (two empty dirs — an O(1) chown, not a recursive pass) and drop to the non-root
# user BEFORE creating the venv and installing, so every file the install writes
# is owned by appuser from the start. This replaces a final `chown -R` over the
# whole venv + app — a metadata-bound pass over thousands of tiny package files
# that cost ~40s on the native arm64 CI runner — with zero extra work, for the
# same end-state ownership.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN mkdir -p /app "$VIRTUAL_ENV" \
    && chown appuser:appgroup /app "$VIRTUAL_ENV"
WORKDIR /app
USER appuser

# Create a clean virtual environment for the production image (as appuser).
RUN python3 -m venv "$VIRTUAL_ENV"

# Upgrade pip to the latest version
RUN pip install --no-cache-dir --upgrade pip

# Install the application and its production dependencies from the wheelhouse
# built in the previous stage. --no-index guarantees nothing is pulled from PyPI
# and no source build can be triggered: every requirement must already exist as
# a wheel in the wheelhouse. It is copied under the appuser-owned /app (so it can
# be removed without root) and deleted afterwards to keep the layer lean.
COPY --from=builder --chown=appuser:appgroup /wheels /app/wheels
RUN pip install --no-cache-dir --no-index --find-links=/app/wheels paperless-ai \
    && rm -rf /app/wheels

# Tell api.py where to find the built frontend.  When installed as a Python
# package, Path(__file__).parent.parent.parent resolves to the venv site-packages
# root, not /app.  The env var takes precedence over the relative-path fallback.
ENV FRONTEND_DIST=/app/web/dist

# Flush daemon logs immediately to docker logs (no line-buffering surprises).
ENV PYTHONUNBUFFERED=1
# Skip .pyc write churn in the ephemeral container filesystem.
ENV PYTHONDONTWRITEBYTECODE=1
# Cap glibc malloc arenas. glibc defaults to 8×NCPU arenas; across four long-lived
# daemons with thread pools each arena retains freed heap, inflating steady-state
# RSS. Two arenas is the standard cap for containerised Python workloads.
ENV MALLOC_ARENA_MAX=2

# Copy the built frontend from the Node stage so the StaticFiles mount is live.
# --chown keeps it appuser-owned in the same pass — no follow-up chown needed.
COPY --from=frontend-builder --chown=appuser:appgroup /web/dist ./web/dist

# Set the default command to run the OCR daemon.
# (The same image can run the classifier via: `paperless-classifier-daemon`
# or `python3 -m classifier.daemon`.)
CMD ["paperless-ai"]
