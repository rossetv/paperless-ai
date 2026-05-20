# Stage 1: Frontend Builder
# Runs npm ci + vite build in a Node environment, producing web/dist.
FROM node:22-slim AS frontend-builder

WORKDIR /web

# Copy dependency manifests first so the npm layer is cached when only
# source files change.
COPY web/package.json web/package-lock.json web/.npmrc ./

RUN npm ci

# Copy the rest of the frontend source and build.
COPY web/ ./

RUN npm run build

# ---------------------------------------------------------------------

# Stage 2: Builder and Tester
# This stage installs all dependencies (including dev), runs tests, and builds the application.
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

# Install development and testing dependencies
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy the application source and tests
COPY src/ ./src/
COPY tests/ ./tests/

# Install the application itself (which also installs production dependencies)
RUN pip install --no-cache-dir .

# Run the test suite to validate the application
RUN pytest

# ---------------------------------------------------------------------

# Stage 2: Final Production Image
# This stage creates a lean, secure image with only runtime dependencies.
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

# Copy the application source code from the builder stage
COPY --from=builder /app/src ./src
# Copy the project definition to install production dependencies
COPY --from=builder /app/pyproject.toml ./

# Create a new, clean virtual environment for the production image
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Upgrade pip to the latest version
RUN pip install --no-cache-dir --upgrade pip

# Install only the production dependencies defined in pyproject.toml
# The '.' tells pip to install the project in the current directory.
RUN pip install --no-cache-dir .

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
# or `python3 -m src.classifier.daemon`.)
CMD ["paperless-ai"]
