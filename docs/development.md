# Development

## Local Setup

```bash
# Clone the repository
git clone https://github.com/rossetv/paperless-ai.git
cd paperless-ai

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the project and dev dependencies
pip install -e . -r requirements-dev.txt

# Run the test suite
pytest

# Run a daemon locally (requires env vars to be set)
export PAPERLESS_URL="http://localhost:8000"
export PAPERLESS_TOKEN="your-token"
export OPENAI_API_KEY="sk-your-key"
python3 -m src.ocr.daemon         # OCR daemon
python3 -m src.classifier.daemon  # Classification daemon
```

### Runtime Dependencies

Outside Docker, you need:
- **Python 3.11+**
- **Poppler** (`poppler-utils`) — required for PDF to image conversion

On macOS: `brew install poppler`
On Ubuntu/Debian: `apt-get install poppler-utils`

### Python Dependencies

Production dependencies (from `pyproject.toml`):

| Package | Version | Purpose |
|:---|:---|:---|
| `httpx` | ~0.28 | HTTP client for Paperless API |
| `openai` | ~1.35 | OpenAI SDK (also used for Ollama via compatible API) |
| `Pillow` | ~10.4 | Image processing (PIL) |
| `pdf2image` | ~1.17 | PDF to image conversion (wraps Poppler) |
| `structlog` | ~24.2 | Structured logging |

---

## Running Tests

The test suite is organized into three categories: unit, integration, and end-to-end.

```bash
# Run all tests
pytest

# Run by category
pytest tests/unit/                    # Unit tests only (~750 tests, <5s)
pytest tests/integration/             # Integration tests (~30 tests)
pytest tests/e2e/                     # End-to-end tests (~20 tests)

# Run by module
pytest tests/unit/common/             # All common module tests
pytest tests/unit/classifier/         # All classifier module tests
pytest tests/unit/ocr/                # All OCR module tests

# Run a single file or test
pytest tests/unit/common/test_config.py
pytest tests/unit/common/test_config.py::TestDefaultValues::test_default_paperless_url

# Generate coverage report
pytest --cov=src --cov-report=term-missing --cov-branch

# Generate HTML coverage report
pytest --cov=src --cov-report=html --cov-branch
open htmlcov/index.html
```

### Coverage Requirements

CI enforces a minimum of **70% branch coverage**. The coverage report is generated automatically in the GitHub Actions pipeline.

---

## Test Organization

Tests mirror the source layout:

```
tests/
├── conftest.py             Root fixtures, markers, path setup
├── helpers/
│   ├── factories.py        Test data factories
│   └── mocks.py            Mock builders
├── unit/                   Unit tests (mirrors src/ layout)
│   ├── common/             Tests for src/common/
│   ├── classifier/         Tests for src/classifier/
│   └── ocr/                Tests for src/ocr/
├── integration/            Cross-module integration tests
└── e2e/                    Full workflow end-to-end tests
```

### Test Markers

Tests are auto-marked by directory:
- `@pytest.mark.unit` — Fast, no I/O, module-level isolation
- `@pytest.mark.integration` — Pipeline validation with real image/text processing
- `@pytest.mark.e2e` — Full workflow simulation with mocked APIs

### Adding New Tests

- **Directory structure**: Tests mirror the source layout. For `src/classifier/foo.py`, create `tests/unit/classifier/test_foo.py`.
- **Naming**: Use `test_<function>_<scenario>_<expected>` (e.g. `test_parse_date_empty_string_returns_none`).
- **Factories**: Use `make_settings_obj()`, `make_document()`, `make_classification_result()` from `tests/helpers/factories.py`.
- **Mocks**: Use `make_mock_paperless()`, `make_mock_ocr_provider()` from `tests/helpers/mocks.py`.

---

## CI/CD Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull request:

### Tests Job

1. Sets up Python 3.11 with pip caching
2. Installs project + dev dependencies
3. Runs `pytest` with 70% coverage requirement
4. Fails the build if coverage is below threshold

### Docker Job (runs after tests pass)

- **Pull requests**: Builds the Docker image for validation only (no push)
- **Main branch**: Builds a multi-platform image (`linux/amd64`, `linux/arm64`) and pushes to Docker Hub as `rossetv/paperless-ai:latest`

### Docker Image

The Dockerfile uses a multi-stage build:

1. **Builder stage**: Installs all dependencies, runs the full test suite, builds the wheel
2. **Production stage**: Lean image with only runtime dependencies, non-root user (`appuser`), minimal attack surface

System dependencies in the production image:
- `poppler-utils` — PDF to image conversion
- `libgl1`, `libglib2.0-0` — Image processing libraries
