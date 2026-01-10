"""
Tests for input validation utilities.

Tests:
- Search term sanitization
- Search term validation
- Security checks for injection attempts
"""

import pytest

from src.utils.validation import (
    sanitize_search_term,
    validate_search_term,
    validate_and_sanitize,
    ValidationError,
    is_valid_discord_id,
    escape_markdown,
    MAX_SEARCH_LENGTH,
)


class TestSanitizeSearchTerm:
    """Tests for search term sanitization."""

    def test_strips_whitespace(self):
        assert sanitize_search_term("  hello  ") == "hello"

    def test_collapses_multiple_spaces(self):
        assert sanitize_search_term("hello    world") == "hello world"

    def test_removes_null_bytes(self):
        assert sanitize_search_term("hello\x00world") == "helloworld"

    def test_removes_control_characters(self):
        assert sanitize_search_term("hello\x1fworld") == "helloworld"

    def test_truncates_long_input(self):
        long_input = "a" * 300
        result = sanitize_search_term(long_input)
        assert len(result) == MAX_SEARCH_LENGTH

    def test_handles_empty_string(self):
        assert sanitize_search_term("") == ""

    def test_handles_none(self):
        assert sanitize_search_term(None) == ""

    def test_preserves_valid_characters(self):
        valid = "The Matrix: Reloaded (2003)"
        assert sanitize_search_term(valid) == valid

    def test_preserves_unicode(self):
        unicode_term = "El Niño"
        assert sanitize_search_term(unicode_term) == unicode_term


class TestValidateSearchTerm:
    """Tests for search term validation."""

    def test_valid_term(self):
        is_valid, error = validate_search_term("Inception")
        assert is_valid is True
        assert error is None

    def test_empty_term_invalid(self):
        is_valid, error = validate_search_term("")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_whitespace_only_invalid(self):
        is_valid, error = validate_search_term("   ")
        assert is_valid is False

    def test_too_long_term_invalid(self):
        long_term = "a" * (MAX_SEARCH_LENGTH + 1)
        is_valid, error = validate_search_term(long_term)
        assert is_valid is False
        assert "maximum length" in error.lower()

    def test_script_tag_detected(self):
        """Test XSS attempt detection."""
        is_valid, error = validate_search_term("<script>alert('xss')</script>")
        assert is_valid is False
        assert "invalid" in error.lower()

    def test_javascript_protocol_detected(self):
        """Test JavaScript protocol injection detection."""
        is_valid, error = validate_search_term("javascript:alert(1)")
        assert is_valid is False

    def test_event_handler_detected(self):
        """Test event handler injection detection."""
        is_valid, error = validate_search_term("onclick=alert(1)")
        assert is_valid is False

    def test_valid_movie_titles(self):
        """Test common valid movie titles."""
        valid_titles = [
            "The Matrix",
            "Schindler's List",
            "The Lord of the Rings: The Fellowship of the Ring",
            "Spider-Man: No Way Home",
            "Mission: Impossible",
            "Se7en",
            "12 Angry Men",
            "Amélie",
        ]
        for title in valid_titles:
            is_valid, error = validate_search_term(title)
            assert is_valid is True, f"'{title}' should be valid"


class TestValidateAndSanitize:
    """Tests for combined validation and sanitization."""

    def test_sanitizes_and_validates(self):
        result = validate_and_sanitize("  The Matrix  ")
        assert result == "The Matrix"

    def test_raises_on_invalid_input(self):
        with pytest.raises(ValidationError):
            validate_and_sanitize("")

    def test_raises_on_suspicious_input(self):
        with pytest.raises(ValidationError):
            validate_and_sanitize("<script>bad</script>")


class TestIsValidDiscordId:
    """Tests for Discord ID validation."""

    def test_valid_discord_id(self):
        assert is_valid_discord_id(123456789012345678) is True

    def test_zero_invalid(self):
        assert is_valid_discord_id(0) is False

    def test_negative_invalid(self):
        assert is_valid_discord_id(-1) is False

    def test_too_large_invalid(self):
        assert is_valid_discord_id(2**64) is False


class TestEscapeMarkdown:
    """Tests for Discord markdown escaping."""

    def test_escapes_asterisks(self):
        assert escape_markdown("**bold**") == "\\*\\*bold\\*\\*"

    def test_escapes_underscores(self):
        assert escape_markdown("__underline__") == "\\_\\_underline\\_\\_"

    def test_escapes_backticks(self):
        assert escape_markdown("`code`") == "\\`code\\`"

    def test_escapes_multiple_characters(self):
        result = escape_markdown("*bold* and _italic_")
        assert "*" not in result or "\\*" in result
        assert "_" not in result or "\\_" in result

    def test_preserves_regular_text(self):
        text = "Hello World"
        # Should only have backslashes if there were special chars
        assert "Hello World" in escape_markdown(text)
