"""
Structured logging configuration with JSON and text format support.

Provides enterprise-grade logging with:
- JSON format for log aggregation (ELK, Splunk, etc.)
- Text format for local development
- Correlation IDs for request tracing
- Audit logging for compliance
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# Context variable for request correlation ID
correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add correlation ID if present
        corr_id = correlation_id.get()
        if corr_id:
            log_data["correlation_id"] = corr_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter for local development."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

    def format(self, record: logging.LogRecord) -> str:
        # Add correlation ID to message if present
        corr_id = correlation_id.get()
        if corr_id:
            record.msg = f"[{corr_id}] {record.msg}"
        return super().format(record)


class StructuredLogger(logging.Logger):
    """Extended logger with structured logging support."""

    def _log_with_extra(
        self,
        level: int,
        msg: str,
        args: tuple,
        exc_info: Any = None,
        extra: Optional[dict] = None,
        **kwargs
    ) -> None:
        """Log with extra structured fields."""
        if extra is None:
            extra = {}
        extra["extra_fields"] = kwargs
        super()._log(level, msg, args, exc_info=exc_info, extra=extra)

    def info_structured(self, msg: str, **kwargs) -> None:
        """Log info with structured fields."""
        self._log_with_extra(logging.INFO, msg, (), **kwargs)

    def warning_structured(self, msg: str, **kwargs) -> None:
        """Log warning with structured fields."""
        self._log_with_extra(logging.WARNING, msg, (), **kwargs)

    def error_structured(self, msg: str, **kwargs) -> None:
        """Log error with structured fields."""
        self._log_with_extra(logging.ERROR, msg, (), **kwargs)

    def audit(self, action: str, user_id: int, user_name: str, **kwargs) -> None:
        """
        Log audit event for compliance.

        Args:
            action: Action being performed (e.g., "request_movie")
            user_id: Discord user ID
            user_name: Discord user display name
            **kwargs: Additional audit data
        """
        self._log_with_extra(
            logging.INFO,
            f"AUDIT: {action}",
            (),
            audit=True,
            action=action,
            user_id=user_id,
            user_name=user_name,
            **kwargs
        )


def setup_logging(
    level: str = "INFO",
    log_format: str = "json",
    file_path: Optional[str] = None
) -> None:
    """
    Configure application logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Output format ("json" or "text")
        file_path: Optional file path for log output
    """
    # Set custom logger class
    logging.setLoggerClass(StructuredLogger)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Select formatter
    if log_format.lower() == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Add file handler if specified
    if file_path:
        file_handler = logging.FileHandler(file_path)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def get_logger(name: str) -> StructuredLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        StructuredLogger instance
    """
    # Ensure logger class is set
    logging.setLoggerClass(StructuredLogger)
    logger = logging.getLogger(name)

    # Add structured methods if not present (for compatibility)
    if not hasattr(logger, 'info_structured'):
        def info_structured(msg: str, **kwargs):
            logger.info(msg, extra={"extra_fields": kwargs})
        logger.info_structured = info_structured

    if not hasattr(logger, 'warning_structured'):
        def warning_structured(msg: str, **kwargs):
            logger.warning(msg, extra={"extra_fields": kwargs})
        logger.warning_structured = warning_structured

    if not hasattr(logger, 'error_structured'):
        def error_structured(msg: str, **kwargs):
            logger.error(msg, extra={"extra_fields": kwargs})
        logger.error_structured = error_structured

    if not hasattr(logger, 'audit'):
        def audit(action: str, user_id: int, user_name: str, **kwargs):
            logger.info(f"AUDIT: {action}", extra={
                "extra_fields": {"audit": True, "action": action, "user_id": user_id, "user_name": user_name, **kwargs}
            })
        logger.audit = audit

    return logger  # type: ignore


def set_correlation_id(corr_id: str) -> None:
    """Set correlation ID for request tracing."""
    correlation_id.set(corr_id)


def clear_correlation_id() -> None:
    """Clear correlation ID."""
    correlation_id.set(None)
