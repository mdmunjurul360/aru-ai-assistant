# Multi-stage production build for Aru AI Personal OS
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# Production runtime
FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python packages from builder
COPY --from=builder /install /usr/local

# Install Playwright browser dependencies and chromium
RUN playwright install --with-deps chromium || true

# Create non-root system user
RUN useradd -m -u 1000 aruuser && \
    mkdir -p /app/database /app/logs /app/sessions /app/plugins /app/knowledge && \
    chown -R aruuser:aruuser /app /ms-playwright

COPY --chown=aruuser:aruuser . /app

USER aruuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python scripts/healthcheck.py || exit 1

ENTRYPOINT ["python", "main.py"]
