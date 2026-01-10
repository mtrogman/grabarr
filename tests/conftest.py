"""
Pytest configuration and fixtures.

Provides common fixtures for testing:
- Mock configurations
- Mock API responses
- Test utilities
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from src.config import AppConfig, BotConfig, RadarrConfig, SonarrConfig, LoggingConfig
from src.logging_config import setup_logging

# Setup logging for tests
setup_logging(level="WARNING", log_format="text")


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_config_file() -> Generator[Path, None, None]:
    """Create a temporary config file."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yml",
        delete=False
    ) as f:
        config = {
            "bot": {
                "token": "test_token_123",
                "request_movie": "movie",
                "request_show": "show",
                "allowed_role_ids": [123, 456],
                "rate_limit_requests": 5,
                "rate_limit_window_seconds": 30,
            },
            "radarr": {
                "api_key": "radarr_key_123",
                "url": "http://localhost:7878/api/v3",
                "qualityprofileid": 1,
                "root_path": "/movies",
            },
            "sonarr": {
                "api_key": "sonarr_key_456",
                "url": "http://localhost:8989/api/v3",
                "qualityprofileid": 2,
                "root_path": "/tv",
            },
            "logging": {
                "level": "DEBUG",
                "format": "text",
            },
        }
        yaml.safe_dump(config, f)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def sample_config() -> AppConfig:
    """Create a sample configuration."""
    return AppConfig(
        bot=BotConfig(
            token="test_token",
            request_movie_command="request_movie",
            request_show_command="request_show",
            allowed_role_ids=[123, 456],
            rate_limit_requests=10,
            rate_limit_window_seconds=60,
        ),
        radarr=RadarrConfig(
            api_key="radarr_api_key",
            url="http://localhost:7878/api/v3",
            quality_profile_id=1,
            root_folder_path="/movies",
        ),
        sonarr=SonarrConfig(
            api_key="sonarr_api_key",
            url="http://localhost:8989/api/v3",
            quality_profile_id=1,
            root_folder_path="/tv",
        ),
        logging=LoggingConfig(
            level="INFO",
            format="json",
        ),
        http_timeout=15,
        http_max_retries=3,
        http_retry_delay=1.0,
    )


@pytest.fixture
def mock_radarr_movie_response() -> list[dict]:
    """Sample Radarr movie lookup response."""
    return [
        {
            "tmdbId": 27205,
            "title": "Inception",
            "year": 2010,
            "overview": "A thief who steals corporate secrets...",
            "titleSlug": "inception-27205",
            "images": [{"coverType": "poster", "url": "http://example.com/poster.jpg"}],
        },
        {
            "tmdbId": 157336,
            "title": "Interstellar",
            "year": 2014,
            "overview": "A team of explorers travel through a wormhole...",
            "titleSlug": "interstellar-157336",
            "images": [],
        },
    ]


@pytest.fixture
def mock_sonarr_show_response() -> list[dict]:
    """Sample Sonarr show lookup response."""
    return [
        {
            "tvdbId": 81189,
            "title": "Breaking Bad",
            "year": 2008,
            "overview": "A high school chemistry teacher diagnosed with cancer...",
            "titleSlug": "breaking-bad",
            "images": [],
        },
        {
            "tvdbId": 153021,
            "title": "Better Call Saul",
            "year": 2015,
            "overview": "Before Saul Goodman, he was Jimmy McGill...",
            "titleSlug": "better-call-saul",
            "images": [],
        },
    ]


@pytest.fixture
def mock_quality_profiles() -> list[dict]:
    """Sample quality profiles response."""
    return [
        {"id": 1, "name": "HD-1080p"},
        {"id": 2, "name": "HD-720p"},
        {"id": 3, "name": "SD"},
    ]


@pytest.fixture
def mock_root_folders() -> list[dict]:
    """Sample root folders response."""
    return [
        {"path": "/movies", "freeSpace": 1000000000000},
        {"path": "/movies2", "freeSpace": 500000000000},
    ]


@pytest.fixture
def clean_environment() -> Generator[None, None, None]:
    """Remove Grabarr environment variables for clean testing."""
    env_vars = [key for key in os.environ if key.startswith("GRABARR_")]
    original_values = {key: os.environ.pop(key) for key in env_vars}

    yield

    # Restore original values
    os.environ.update(original_values)
