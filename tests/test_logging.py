"""
Tests for logging configuration.

Tests:
- JSON formatter
- Text formatter
- Structured logging
- Correlation IDs
- Audit logging
"""

import json
import logging
from io import StringIO
from unittest.mock import patch

import pytest

from src.logging_config import (
    JSONFormatter,
    TextFormatter,
    setup_logging,
    get_logger,
    set_correlation_id,
    clear_correlation_id,
    correlation_id,
)


class TestJSONFormatter:
    """Tests for JSON log formatter."""

    @pytest.fixture
    def json_formatter(self):
        """Create JSON formatter."""
        return JSONFormatter()

    def test_formats_as_json(self, json_formatter):
        """Test that output is valid JSON."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"

    def test_includes_timestamp(self, json_formatter):
        """Test that timestamp is included."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None
        )

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert "timestamp" in parsed

    def test_includes_correlation_id(self, json_formatter):
        """Test that correlation ID is included when set."""
        set_correlation_id("abc123")

        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg="Test",
                args=(),
                exc_info=None
            )

            output = json_formatter.format(record)
            parsed = json.loads(output)

            assert parsed["correlation_id"] == "abc123"
        finally:
            clear_correlation_id()

    def test_excludes_correlation_id_when_not_set(self, json_formatter):
        """Test that correlation ID is excluded when not set."""
        clear_correlation_id()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None
        )

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert "correlation_id" not in parsed


class TestTextFormatter:
    """Tests for text log formatter."""

    @pytest.fixture
    def text_formatter(self):
        """Create text formatter."""
        return TextFormatter()

    def test_readable_format(self, text_formatter):
        """Test that output is human-readable."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        output = text_formatter.format(record)

        assert "INFO" in output
        assert "Test message" in output
        assert "test" in output

    def test_includes_correlation_id_in_message(self, text_formatter):
        """Test that correlation ID is prepended to message."""
        set_correlation_id("xyz789")

        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg="Test message",
                args=(),
                exc_info=None
            )

            output = text_formatter.format(record)

            assert "[xyz789]" in output
        finally:
            clear_correlation_id()


class TestSetupLogging:
    """Tests for logging setup."""

    def test_json_format_setup(self):
        """Test setting up JSON logging."""
        setup_logging(level="DEBUG", log_format="json")

        root = logging.getLogger()
        assert root.level == logging.DEBUG

        # Check handler has JSON formatter
        assert len(root.handlers) > 0
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_text_format_setup(self):
        """Test setting up text logging."""
        setup_logging(level="INFO", log_format="text")

        root = logging.getLogger()
        assert root.level == logging.INFO

        # Check handler has text formatter
        assert len(root.handlers) > 0
        assert isinstance(root.handlers[0].formatter, TextFormatter)

    def test_reduces_third_party_logging(self):
        """Test that third-party loggers are quieted."""
        setup_logging()

        discord_logger = logging.getLogger("discord")
        aiohttp_logger = logging.getLogger("aiohttp")

        assert discord_logger.level >= logging.WARNING
        assert aiohttp_logger.level >= logging.WARNING


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger(self):
        """Test that get_logger returns a logger."""
        logger = get_logger("test_module")

        assert logger is not None
        assert logger.name == "test_module"


class TestCorrelationId:
    """Tests for correlation ID context variable."""

    def test_set_and_get(self):
        """Test setting and getting correlation ID."""
        set_correlation_id("test123")

        assert correlation_id.get() == "test123"

        clear_correlation_id()

    def test_clear(self):
        """Test clearing correlation ID."""
        set_correlation_id("test123")
        clear_correlation_id()

        assert correlation_id.get() is None

    def test_default_value(self):
        """Test default value is None."""
        clear_correlation_id()
        assert correlation_id.get() is None
