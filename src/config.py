"""
Configuration management with environment variable support and validation.

Supports loading from:
1. Environment variables (highest priority)
2. YAML configuration file
3. Default values (lowest priority)
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing required values."""
    pass


@dataclass
class BotConfig:
    """Discord bot configuration."""
    token: str = ""
    request_movie_command: str = "request_movie"
    request_show_command: str = "request_show"
    allowed_role_ids: list[int] = field(default_factory=list)
    rate_limit_requests: int = 10  # requests per window
    rate_limit_window_seconds: int = 60


@dataclass
class RadarrConfig:
    """Radarr API configuration."""
    api_key: str = ""
    url: str = ""
    quality_profile_id: Optional[int] = None
    root_folder_path: Optional[str] = None


@dataclass
class SonarrConfig:
    """Sonarr API configuration."""
    api_key: str = ""
    url: str = ""
    quality_profile_id: Optional[int] = None
    root_folder_path: Optional[str] = None


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "json"  # "json" or "text"
    file_path: Optional[str] = None


@dataclass
class AppConfig:
    """Main application configuration."""
    bot: BotConfig = field(default_factory=BotConfig)
    radarr: RadarrConfig = field(default_factory=RadarrConfig)
    sonarr: SonarrConfig = field(default_factory=SonarrConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    http_timeout: int = 15
    http_max_retries: int = 3
    http_retry_delay: float = 1.0


def normalize_url(url: str) -> str:
    """Normalize URL by removing trailing slashes."""
    return (url or "").rstrip("/")


def _get_env(key: str, default: str = "") -> str:
    """Get environment variable with optional default."""
    return os.environ.get(key, default)


def _get_env_int(key: str, default: int) -> int:
    """Get environment variable as integer."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_list(key: str, default: list) -> list:
    """Get environment variable as comma-separated list of integers."""
    value = os.environ.get(key)
    if not value:
        return default
    try:
        return [int(x.strip()) for x in value.split(",") if x.strip()]
    except ValueError:
        return default


def _parse_bot_config(yaml_config: dict) -> BotConfig:
    """Parse bot configuration from YAML and environment."""
    bot_yaml = yaml_config.get("bot", {}) or {}

    return BotConfig(
        token=_get_env("GRABARR_BOT_TOKEN", bot_yaml.get("token", "")),
        request_movie_command=_get_env(
            "GRABARR_REQUEST_MOVIE_COMMAND",
            bot_yaml.get("request_movie", "request_movie")
        ),
        request_show_command=_get_env(
            "GRABARR_REQUEST_SHOW_COMMAND",
            bot_yaml.get("request_show", "request_show")
        ),
        allowed_role_ids=_get_env_list(
            "GRABARR_ALLOWED_ROLE_IDS",
            bot_yaml.get("allowed_role_ids", [])
        ),
        rate_limit_requests=_get_env_int(
            "GRABARR_RATE_LIMIT_REQUESTS",
            bot_yaml.get("rate_limit_requests", 10)
        ),
        rate_limit_window_seconds=_get_env_int(
            "GRABARR_RATE_LIMIT_WINDOW",
            bot_yaml.get("rate_limit_window_seconds", 60)
        ),
    )


def _parse_radarr_config(yaml_config: dict) -> RadarrConfig:
    """Parse Radarr configuration from YAML and environment."""
    radarr_yaml = yaml_config.get("radarr", {}) or {}

    quality_profile = _get_env("GRABARR_RADARR_QUALITY_PROFILE")
    if not quality_profile:
        quality_profile = radarr_yaml.get("qualityprofileid") or radarr_yaml.get("profile")

    return RadarrConfig(
        api_key=_get_env("GRABARR_RADARR_API_KEY", radarr_yaml.get("api_key", "")),
        url=normalize_url(_get_env("GRABARR_RADARR_URL", radarr_yaml.get("url", ""))),
        quality_profile_id=int(quality_profile) if quality_profile else None,
        root_folder_path=_get_env("GRABARR_RADARR_ROOT_PATH", radarr_yaml.get("root_path")),
    )


def _parse_sonarr_config(yaml_config: dict) -> SonarrConfig:
    """Parse Sonarr configuration from YAML and environment."""
    sonarr_yaml = yaml_config.get("sonarr", {}) or {}

    quality_profile = _get_env("GRABARR_SONARR_QUALITY_PROFILE")
    if not quality_profile:
        quality_profile = sonarr_yaml.get("qualityprofileid") or sonarr_yaml.get("profile")

    return SonarrConfig(
        api_key=_get_env("GRABARR_SONARR_API_KEY", sonarr_yaml.get("api_key", "")),
        url=normalize_url(_get_env("GRABARR_SONARR_URL", sonarr_yaml.get("url", ""))),
        quality_profile_id=int(quality_profile) if quality_profile else None,
        root_folder_path=_get_env("GRABARR_SONARR_ROOT_PATH", sonarr_yaml.get("root_path")),
    )


def _parse_logging_config(yaml_config: dict) -> LoggingConfig:
    """Parse logging configuration from YAML and environment."""
    logging_yaml = yaml_config.get("logging", {}) or {}

    return LoggingConfig(
        level=_get_env("GRABARR_LOG_LEVEL", logging_yaml.get("level", "INFO")).upper(),
        format=_get_env("GRABARR_LOG_FORMAT", logging_yaml.get("format", "json")),
        file_path=_get_env("GRABARR_LOG_FILE", logging_yaml.get("file_path")),
    )


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from file and environment variables.

    Environment variables take precedence over file values.

    Args:
        config_path: Path to YAML config file. If None, uses GRABARR_CONFIG_PATH
                    env var or defaults to /config/config.yml

    Returns:
        AppConfig instance with validated configuration

    Raises:
        ConfigurationError: If configuration is invalid or missing required values
    """
    # Determine config file path
    if config_path is None:
        config_path = _get_env("GRABARR_CONFIG_PATH", "/config/config.yml")

    # Load YAML config if file exists
    yaml_config = {}
    config_file = Path(config_path)
    if config_file.exists():
        try:
            with open(config_file, "r") as f:
                yaml_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in config file: {e}")
        except IOError as e:
            raise ConfigurationError(f"Cannot read config file: {e}")

    # Parse all sections
    config = AppConfig(
        bot=_parse_bot_config(yaml_config),
        radarr=_parse_radarr_config(yaml_config),
        sonarr=_parse_sonarr_config(yaml_config),
        logging=_parse_logging_config(yaml_config),
        http_timeout=_get_env_int("GRABARR_HTTP_TIMEOUT", yaml_config.get("http_timeout", 15)),
        http_max_retries=_get_env_int("GRABARR_HTTP_MAX_RETRIES", yaml_config.get("http_max_retries", 3)),
        http_retry_delay=float(_get_env("GRABARR_HTTP_RETRY_DELAY", str(yaml_config.get("http_retry_delay", 1.0)))),
    )

    return config


def validate_config(config: AppConfig) -> list[str]:
    """
    Validate configuration and return list of errors.

    Args:
        config: AppConfig instance to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Bot token is required
    if not config.bot.token:
        errors.append("Bot token is required (set GRABARR_BOT_TOKEN or bot.token in config)")

    # Radarr configuration
    if not config.radarr.api_key:
        errors.append("Radarr API key is required (set GRABARR_RADARR_API_KEY or radarr.api_key)")
    if not config.radarr.url:
        errors.append("Radarr URL is required (set GRABARR_RADARR_URL or radarr.url)")
    elif not _is_valid_url(config.radarr.url):
        errors.append(f"Radarr URL is invalid: {config.radarr.url}")

    # Sonarr configuration
    if not config.sonarr.api_key:
        errors.append("Sonarr API key is required (set GRABARR_SONARR_API_KEY or sonarr.api_key)")
    if not config.sonarr.url:
        errors.append("Sonarr URL is required (set GRABARR_SONARR_URL or sonarr.url)")
    elif not _is_valid_url(config.sonarr.url):
        errors.append(f"Sonarr URL is invalid: {config.sonarr.url}")

    # Validate rate limiting
    if config.bot.rate_limit_requests < 1:
        errors.append("Rate limit requests must be at least 1")
    if config.bot.rate_limit_window_seconds < 1:
        errors.append("Rate limit window must be at least 1 second")

    # Validate HTTP settings
    if config.http_timeout < 1:
        errors.append("HTTP timeout must be at least 1 second")
    if config.http_max_retries < 0:
        errors.append("HTTP max retries cannot be negative")

    return errors


def _is_valid_url(url: str) -> bool:
    """Check if URL is valid."""
    pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP address
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return bool(pattern.match(url))


def save_config(config: AppConfig, config_path: str) -> None:
    """
    Save configuration to YAML file.

    Args:
        config: AppConfig instance to save
        config_path: Path to save configuration file
    """
    data = {
        "bot": {
            "token": config.bot.token,
            "request_movie": config.bot.request_movie_command,
            "request_show": config.bot.request_show_command,
            "allowed_role_ids": config.bot.allowed_role_ids,
            "rate_limit_requests": config.bot.rate_limit_requests,
            "rate_limit_window_seconds": config.bot.rate_limit_window_seconds,
        },
        "radarr": {
            "api_key": config.radarr.api_key,
            "url": config.radarr.url,
            "qualityprofileid": config.radarr.quality_profile_id,
            "root_path": config.radarr.root_folder_path,
        },
        "sonarr": {
            "api_key": config.sonarr.api_key,
            "url": config.sonarr.url,
            "qualityprofileid": config.sonarr.quality_profile_id,
            "root_path": config.sonarr.root_folder_path,
        },
        "logging": {
            "level": config.logging.level,
            "format": config.logging.format,
            "file_path": config.logging.file_path,
        },
        "http_timeout": config.http_timeout,
        "http_max_retries": config.http_max_retries,
        "http_retry_delay": config.http_retry_delay,
    }

    with open(config_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
