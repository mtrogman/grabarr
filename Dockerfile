# Build stage for dependency installation
FROM python:3.14-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# Production stage
FROM python:3.14-slim AS production

# Labels
LABEL org.opencontainers.image.title="grabarr"
LABEL org.opencontainers.image.description="Discord bot for media management with Sonarr and Radarr"
LABEL org.opencontainers.image.source="https://github.com/mtrogman/grabarr"
LABEL org.opencontainers.image.licenses="GPL-3.0"

# Create non-root user for security
RUN groupadd --gid 1000 grabarr && \
    useradd --uid 1000 --gid grabarr --shell /bin/bash --create-home grabarr

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=grabarr:grabarr src/ /app/src/
COPY --chown=grabarr:grabarr config.yml.example /config/config.yml.example

# Create config volume
VOLUME /config

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV GRABARR_CONFIG_PATH=/config/config.yml

# Expose health check port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Switch to non-root user
USER grabarr

# Run application
CMD ["python", "-m", "src.main"]
