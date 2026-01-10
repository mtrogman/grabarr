# Migration Guide: v2.x to v3.0

This guide covers migrating from Grabarr v2.x to the new enterprise-ready v3.0.

## Overview of Changes

### Architecture Changes
- **Modular structure**: Code split into separate modules (`src/config.py`, `src/api/`, `src/discord_bot/`, etc.)
- **Async HTTP**: Replaced synchronous `requests` with async `aiohttp`
- **Dataclasses**: Proper data models for movies and shows

### Security Improvements
- API keys now passed via headers instead of query parameters
- Input validation and sanitization for all user inputs
- Role-based access control for commands
- Rate limiting per user
- Minimal Discord intents (principle of least privilege)

### New Features
- Environment variable support for all configuration
- Health check HTTP endpoints (`/health`, `/ready`, `/metrics`)
- Structured JSON logging
- Graceful shutdown handling
- Retry logic with exponential backoff

## Migration Steps

### 1. Configuration Changes

The configuration file format has been enhanced but remains backward compatible.

**Old format (still works):**
```yaml
bot:
  token: YOUR_TOKEN
  request_movie: request_movie
  request_series: request_show

radarr:
  api_key: YOUR_KEY
  url: http://localhost:7878/api/v3
  profile: 1
  root_path: /movies

sonarr:
  api_key: YOUR_KEY
  url: http://localhost:8989/api/v3
  profile: 1
  root_path: /tv
```

**New format (recommended):**
```yaml
bot:
  token: YOUR_TOKEN
  request_movie: request_movie
  request_show: request_show
  allowed_role_ids: []  # NEW: Role-based access
  rate_limit_requests: 10  # NEW: Rate limiting
  rate_limit_window_seconds: 60

radarr:
  api_key: YOUR_KEY
  url: http://localhost:7878/api/v3
  qualityprofileid: 1  # Renamed from 'profile'
  root_path: /movies

sonarr:
  api_key: YOUR_KEY
  url: http://localhost:8989/api/v3
  qualityprofileid: 1  # Renamed from 'profile'
  root_path: /tv

logging:  # NEW section
  level: INFO
  format: json
```

### 2. Environment Variables (Optional)

You can now configure Grabarr entirely via environment variables:

```bash
# Required
GRABARR_BOT_TOKEN=your_discord_token
GRABARR_RADARR_API_KEY=your_radarr_key
GRABARR_RADARR_URL=http://localhost:7878/api/v3
GRABARR_SONARR_API_KEY=your_sonarr_key
GRABARR_SONARR_URL=http://localhost:8989/api/v3

# Optional
GRABARR_ALLOWED_ROLE_IDS=123456789,987654321
GRABARR_RATE_LIMIT_REQUESTS=10
GRABARR_RATE_LIMIT_WINDOW=60
GRABARR_LOG_LEVEL=INFO
GRABARR_LOG_FORMAT=json
```

### 3. Docker Changes

The new Dockerfile:
- Uses Python 3.12-slim (smaller image)
- Runs as non-root user `grabarr`
- Includes health check
- Exposes port 8080 for health endpoints

**Docker Compose update:**
```yaml
version: '3.8'
services:
  grabarr:
    image: mtrogman/grabarr:3.0.0
    container_name: grabarr
    volumes:
      - /path/to/config:/config
    ports:
      - "8080:8080"  # NEW: Health check port
    environment:
      - GRABARR_LOG_FORMAT=json
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
```

### 4. Role-Based Access Control

To restrict who can use commands, add Discord role IDs:

```yaml
bot:
  allowed_role_ids:
    - 123456789012345678  # Media Requesters role
    - 987654321098765432  # Admin role
```

Leave empty `[]` to allow all users.

### 5. Health Endpoints

New HTTP endpoints available on port 8080:

- `GET /health` - Liveness probe (always returns 200 if process alive)
- `GET /ready` - Readiness probe (returns 503 if dependencies down)
- `GET /metrics` - Basic metrics (guild count, latency, etc.)

### 6. Logging Changes

Logs are now JSON-formatted by default for log aggregation:

```json
{"timestamp": "2024-01-15T10:30:00Z", "level": "INFO", "message": "Movie added", "movie": "Inception"}
```

For human-readable logs, set:
```yaml
logging:
  format: text
```

## Breaking Changes

1. **Python 3.11+ required** (was 3.9)
2. **New file structure** - `grabarr.py` replaced by `src/` module
3. **Entry point changed** - Now run with `python -m src.main`

## Rollback

If you need to rollback, the old `grabarr.py` file is preserved. Simply:
1. Use the old Dockerfile
2. Remove the `src/` directory
3. Use your existing config file

## Getting Help

If you encounter issues during migration:
1. Check the logs (now more detailed)
2. Visit `/health` endpoint to check component status
3. Open an issue at https://github.com/mtrogman/grabarr/issues
