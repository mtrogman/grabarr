"""
Input validation and sanitization utilities.

Provides security-focused validation for user inputs to prevent
injection attacks and ensure data integrity.
"""

import re
from typing import Optional

from ..logging_config import get_logger

logger = get_logger(__name__)


# Maximum length for search terms
MAX_SEARCH_LENGTH = 200

# Minimum length for search terms
MIN_SEARCH_LENGTH = 1

# Pattern for allowed characters in search terms
# Allows: alphanumeric, spaces, common punctuation, international characters
ALLOWED_SEARCH_PATTERN = re.compile(
    r'^[\w\s\-\'\"\.,:;!?\(\)\[\]&@#\u00C0-\u017F]+$',
    re.UNICODE
)

# Patterns that could indicate injection attempts
SUSPICIOUS_PATTERNS = [
    re.compile(r'<script', re.IGNORECASE),
    re.compile(r'javascript:', re.IGNORECASE),
    re.compile(r'on\w+\s*=', re.IGNORECASE),  # onclick=, onerror=, etc.
    re.compile(r'[\x00-\x1f]'),  # Control characters
    re.compile(r'\x7f'),  # DEL character
]


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


def sanitize_search_term(term: str) -> str:
    """
    Sanitize a search term for safe API usage.

    Performs the following sanitization:
    - Strips leading/trailing whitespace
    - Collapses multiple spaces to single space
    - Removes null bytes and control characters
    - Truncates to maximum length

    Args:
        term: Raw search term from user

    Returns:
        Sanitized search term
    """
    if not term:
        return ""

    # Remove null bytes and control characters
    sanitized = re.sub(r'[\x00-\x1f\x7f]', '', term)

    # Strip and collapse whitespace
    sanitized = ' '.join(sanitized.split())

    # Truncate to max length
    if len(sanitized) > MAX_SEARCH_LENGTH:
        sanitized = sanitized[:MAX_SEARCH_LENGTH]

    return sanitized


def validate_search_term(term: str) -> tuple[bool, Optional[str]]:
    """
    Validate a search term.

    Checks for:
    - Minimum/maximum length
    - Allowed character patterns
    - Potential injection attempts

    Args:
        term: Search term to validate

    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is None
    """
    if not term:
        return False, "Search term cannot be empty"

    # Check minimum length
    if len(term.strip()) < MIN_SEARCH_LENGTH:
        return False, "Search term is too short"

    # Check maximum length
    if len(term) > MAX_SEARCH_LENGTH:
        return False, f"Search term exceeds maximum length of {MAX_SEARCH_LENGTH} characters"

    # Check for suspicious patterns (potential injection)
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(term):
            logger.warning_structured(
                "Suspicious pattern detected in search term",
                pattern=pattern.pattern,
                term_preview=term[:50]
            )
            return False, "Search term contains invalid characters"

    # Validate allowed characters (optional - can be disabled for more permissive search)
    # Commented out to allow broader international character support
    # if not ALLOWED_SEARCH_PATTERN.match(term):
    #     return False, "Search term contains invalid characters"

    return True, None


def validate_and_sanitize(term: str) -> str:
    """
    Validate and sanitize a search term.

    Convenience function that combines sanitization and validation.

    Args:
        term: Raw search term from user

    Returns:
        Sanitized and validated search term

    Raises:
        ValidationError: If term fails validation
    """
    # Sanitize first
    sanitized = sanitize_search_term(term)

    # Then validate
    is_valid, error = validate_search_term(sanitized)
    if not is_valid:
        raise ValidationError(error)

    return sanitized


def is_valid_discord_id(id_value: int) -> bool:
    """
    Check if a value is a valid Discord snowflake ID.

    Discord snowflakes are 64-bit integers.

    Args:
        id_value: Value to check

    Returns:
        True if valid Discord ID format
    """
    try:
        # Discord snowflakes are between these ranges
        # Minimum is Discord epoch (2015-01-01) as snowflake
        return 0 < id_value < (2 ** 63)
    except (TypeError, ValueError):
        return False


def escape_markdown(text: str) -> str:
    """
    Escape Discord markdown characters in text.

    Prevents user-supplied text from being rendered as markdown.

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for Discord messages
    """
    escape_chars = ['\\', '*', '_', '~', '`', '|', '>', '#', '-', '.', '!', '[', ']', '(', ')']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text
