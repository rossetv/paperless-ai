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
RUN apt-get update && apt-get install -y \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
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

# Copy the application source and tests
COPY src/ ./src/
COPY tests/ ./tests/

# Build the production wheelhouse (the project plus its runtime deps from
# pyproject — NOT the dev deps). Any dependency lacking a prebuilt wheel for this
# platform is compiled into a wheel here, where the toolchain exists, so the
# final stage never needs a compiler on any architecture. Placed before the
# RUN_TESTS arg so this layer caches identically whether or not tests run.
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

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
        && pytest; \
    fi

# ---------------------------------------------------------------------

# Stage 3: Final Production Image
# Lean runtime image with NO build toolchain. Production dependencies are
# installed from the prebuilt wheelhouse (offline, --no-index), so this stage
# needs neither a compiler nor network access to PyPI on any architecture.
FROM python:3.11-slim

# Create a non-root user and group for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Install only essential runtime system dependencies
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Create a clean virtual environment for the production image
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Upgrade pip to the latest version
RUN pip install --no-cache-dir --upgrade pip

# Install the application and its production dependencies from the wheelhouse
# built in the previous stage. --no-index guarantees nothing is pulled from PyPI
# and no source build can be triggered: every requirement must already exist as
# a wheel under /wheels. The wheelhouse is removed afterwards to keep the layer
# lean.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels paperless-ai \
    && rm -rf /wheels

# Tell api.py where to find the built frontend.  When installed as a Python
# package, Path(__file__).parent.parent.parent resolves to the venv site-packages
# root, not /app.  The env var takes precedence over the relative-path fallback.
ENV FRONTEND_DIST=/app/web/dist

# Copy the built frontend from the Node stage so the StaticFiles mount is live.
COPY --from=frontend-builder /web/dist ./web/dist

# Transfer ownership of the application files and venv to the non-root user
RUN chown -R appuser:appgroup /app /opt/venv

# Switch to the non-root user
USER appuser

# Set the default command to run the OCR daemon.
# (The same image can run the classifier via: `paperless-classifier-daemon`
# or `python3 -m classifier.daemon`.)
CMD ["paperless-ai"]
