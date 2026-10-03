# CapForge — Production Docker Image
# Multi-stage build for minimal production footprint

# --- Stage 1: Builder ---
FROM python:3.11-slim AS builder

WORKDIR /build

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY . .
RUN pip install --no-cache-dir --prefix=/install .

# --- Stage 2: Production Runtime ---
FROM python:3.11-slim AS runtime

# Security: Run as non-root user
RUN groupadd -r capforge && useradd -r -g capforge -m capforge

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --from=builder /build/capforge /app/capforge
COPY --from=builder /build/pyproject.toml /app/

# Create data directories
RUN mkdir -p /app/data /app/capabilities && \
    chown -R capforge:capforge /app

USER capforge

# Environment configuration
ENV CAPFORGE_BASE_DIR=/app \
    CAPFORGE_DATA_DIR=/app/data \
    CAPFORGE_DB_PATH=/app/data/capforge.db \
    CAPFORGE_CAPABILITIES_DIR=/app/capabilities \
    CAPFORGE_API_HOST=0.0.0.0 \
    CAPFORGE_API_PORT=8000 \
    CAPFORGE_LOG_LEVEL=INFO \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/health'); r.raise_for_status()"

ENTRYPOINT ["python", "-m", "uvicorn", "capforge.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
