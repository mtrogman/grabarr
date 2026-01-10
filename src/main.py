"""
Main entry point for Grabarr.

Handles:
- Configuration loading and validation
- Logging setup
- Bot initialization
- Health server startup
- Graceful shutdown
"""

import asyncio
import sys
from typing import Optional

from .config import load_config, validate_config, ConfigurationError
from .discord_bot.bot import GrabarrBot, setup_signal_handlers
from .health import HealthServer
from .logging_config import setup_logging, get_logger


async def main() -> int:
    """
    Main application entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Load configuration
    try:
        config = load_config()
    except ConfigurationError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    # Setup logging
    setup_logging(
        level=config.logging.level,
        log_format=config.logging.format,
        file_path=config.logging.file_path
    )

    logger = get_logger(__name__)
    logger.info("Grabarr starting...")

    # Validate configuration
    errors = validate_config(config)
    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        return 1

    # Initialize bot
    bot = GrabarrBot(config)

    # Initialize health server
    health_server = HealthServer(bot, port=8080)

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers(bot)

    try:
        # Start health server
        await health_server.start()

        # Run bot
        logger.info("Starting Discord bot...")
        await bot.start(config.bot.token)

    except Exception as e:
        logger.error_structured(
            "Fatal error",
            error=str(e),
            exc_info=True
        )
        return 1

    finally:
        # Cleanup
        logger.info("Shutting down...")
        await health_server.stop()
        if not bot.is_closed():
            await bot.close()

    return 0


def run() -> None:
    """Run the application."""
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nShutdown requested...")
        sys.exit(0)


if __name__ == "__main__":
    run()
