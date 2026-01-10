"""
Tests for configuration module.

Tests:
- YAML config loading
- Environment variable overrides
- Configuration validation
- Default values
- Error handling
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from src.config import (
    AppConfig,
    BotConfig,
    RadarrConfig,
    SonarrConfig,
    ConfigurationError,
    load_config,
    validate_config,
    normalize_url,
    save_config,
    _is_valid_url,
)


class TestNormalizeUrl:
    """Tests for URL normalization."""

    def test_removes_trailing_slash(self):
        assert normalize_url("http://localhost:8989/") == "http://localhost:8989"

    def test_removes_multiple_trailing_slashes(self):
        assert normalize_url("http://localhost:8989///") == "http://localhost:8989"

    def test_handles_empty_string(self):
        assert normalize_url("") == ""

    def test_handles_none(self):
        assert normalize_url(None) == ""

    def test_preserves_path(self):
        assert normalize_url("http://localhost:8989/api/v3") == "http://localhost:8989/api/v3"


class TestIsValidUrl:
    """Tests for URL validation."""

    def test_valid_http_url(self):
        assert _is_valid_url("http://localhost:8989") is True

    def test_valid_https_url(self):
        assert _is_valid_url("https://example.com") is True

    def test_valid_ip_url(self):
        assert _is_valid_url("http://192.168.1.100:8989") is True

    def test_valid_url_with_path(self):
        assert _is_valid_url("http://localhost:8989/api/v3") is True

    def test_invalid_url_no_protocol(self):
        assert _is_valid_url("localhost:8989") is False

    def test_invalid_url_empty(self):
        assert _is_valid_url("") is False


class TestLoadConfig:
    """Tests for configuration loading."""

    def test_load_from_yaml_file(self, temp_config_file, clean_environment):
        """Test loading config from YAML file."""
        config = load_config(str(temp_config_file))

        assert config.bot.token == "test_token_123"
        assert config.bot.request_movie_command == "movie"
        assert config.radarr.api_key == "radarr_key_123"
        assert config.radarr.url == "http://localhost:7878/api/v3"
        assert config.sonarr.api_key == "sonarr_key_456"

    def test_environment_variables_override_yaml(self, temp_config_file):
        """Test that environment variables take precedence."""
        os.environ["GRABARR_BOT_TOKEN"] = "env_token"
        os.environ["GRABARR_RADARR_API_KEY"] = "env_radarr_key"

        try:
            config = load_config(str(temp_config_file))
            assert config.bot.token == "env_token"
            assert config.radarr.api_key == "env_radarr_key"
        finally:
            del os.environ["GRABARR_BOT_TOKEN"]
            del os.environ["GRABARR_RADARR_API_KEY"]

    def test_default_values_when_file_missing(self, clean_environment):
        """Test default values when config file doesn't exist."""
        config = load_config("/nonexistent/config.yml")

        assert config.bot.request_movie_command == "request_movie"
        assert config.bot.request_show_command == "request_show"
        assert config.bot.rate_limit_requests == 10
        assert config.http_timeout == 15

    def test_invalid_yaml_raises_error(self):
        """Test that invalid YAML raises ConfigurationError."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yml",
            delete=False
        ) as f:
            f.write("invalid: yaml: content: [")
            temp_path = f.name

        try:
            with pytest.raises(ConfigurationError):
                load_config(temp_path)
        finally:
            os.unlink(temp_path)

    def test_allowed_role_ids_from_env(self, clean_environment):
        """Test parsing allowed role IDs from environment."""
        os.environ["GRABARR_ALLOWED_ROLE_IDS"] = "123,456,789"

        try:
            config = load_config("/nonexistent/config.yml")
            assert config.bot.allowed_role_ids == [123, 456, 789]
        finally:
            del os.environ["GRABARR_ALLOWED_ROLE_IDS"]


class TestValidateConfig:
    """Tests for configuration validation."""

    def test_valid_config_returns_empty_errors(self, sample_config):
        """Test that valid config produces no errors."""
        errors = validate_config(sample_config)
        assert errors == []

    def test_missing_bot_token_error(self, sample_config):
        """Test error when bot token is missing."""
        sample_config.bot.token = ""
        errors = validate_config(sample_config)
        assert any("Bot token" in e for e in errors)

    def test_missing_radarr_api_key_error(self, sample_config):
        """Test error when Radarr API key is missing."""
        sample_config.radarr.api_key = ""
        errors = validate_config(sample_config)
        assert any("Radarr API key" in e for e in errors)

    def test_missing_sonarr_url_error(self, sample_config):
        """Test error when Sonarr URL is missing."""
        sample_config.sonarr.url = ""
        errors = validate_config(sample_config)
        assert any("Sonarr URL" in e for e in errors)

    def test_invalid_url_format_error(self, sample_config):
        """Test error when URL format is invalid."""
        sample_config.radarr.url = "not-a-valid-url"
        errors = validate_config(sample_config)
        assert any("invalid" in e.lower() for e in errors)

    def test_invalid_rate_limit_error(self, sample_config):
        """Test error when rate limit is invalid."""
        sample_config.bot.rate_limit_requests = 0
        errors = validate_config(sample_config)
        assert any("Rate limit" in e for e in errors)

    def test_invalid_timeout_error(self, sample_config):
        """Test error when timeout is invalid."""
        sample_config.http_timeout = 0
        errors = validate_config(sample_config)
        assert any("timeout" in e.lower() for e in errors)


class TestSaveConfig:
    """Tests for configuration saving."""

    def test_save_and_reload_config(self, sample_config):
        """Test saving config and reloading it."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yml",
            delete=False
        ) as f:
            temp_path = f.name

        try:
            save_config(sample_config, temp_path)

            # Reload and verify
            with open(temp_path) as f:
                saved_data = yaml.safe_load(f)

            assert saved_data["bot"]["token"] == sample_config.bot.token
            assert saved_data["radarr"]["api_key"] == sample_config.radarr.api_key
            assert saved_data["sonarr"]["url"] == sample_config.sonarr.url
        finally:
            os.unlink(temp_path)
