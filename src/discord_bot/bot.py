"""
Main Discord bot class with enterprise features.

Features:
- Minimal required intents (principle of least privilege)
- Graceful shutdown handling
- Health check support
- Structured logging integration
- Service resilience with automatic reconnection
"""

import asyncio
import signal
from typing import Optional

import discord
from discord.ext import commands

from ..config import AppConfig
from ..api import RadarrClient, SonarrClient
from ..logging_config import get_logger
from ..utils import RateLimiter

logger = get_logger(__name__)

# Retry configuration for service resilience
BACKGROUND_RETRY_INTERVAL = 60  # seconds between background retry attempts


class GrabarrBot(commands.Bot):
    """
    Enterprise Discord bot for media management.

    Integrates with Sonarr and Radarr with proper async handling,
    rate limiting, and access control.
    """

    def __init__(self, config: AppConfig):
        """
        Initialize bot with configuration.

        Args:
            config: Application configuration
        """
        # Use minimal required intents
        intents = discord.Intents.default()
        # Only enable message content if needed for prefix commands
        # intents.message_content = True

        super().__init__(
            command_prefix="!",  # Prefix commands disabled, but required
            intents=intents,
            help_command=None  # Disable default help
        )

        self.config = config
        self._shutdown_event = asyncio.Event()
        self._is_ready = False

        # Service availability tracking
        self.radarr_available: bool = False
        self.sonarr_available: bool = False
        self._config_retry_task: Optional[asyncio.Task] = None

        # Initialize API clients
        self.radarr = RadarrClient(
            base_url=config.radarr.url,
            api_key=config.radarr.api_key,
            timeout=config.http_timeout,
            max_retries=config.http_max_retries,
            retry_delay=config.http_retry_delay
        )

        self.sonarr = SonarrClient(
            base_url=config.sonarr.url,
            api_key=config.sonarr.api_key,
            timeout=config.http_timeout,
            max_retries=config.http_max_retries,
            retry_delay=config.http_retry_delay
        )

        # Initialize rate limiter
        self.rate_limiter = RateLimiter(
            max_requests=config.bot.rate_limit_requests,
            window_seconds=config.bot.rate_limit_window_seconds
        )

        # Store configuration values for cogs
        self.allowed_role_ids = config.bot.allowed_role_ids
        self.radarr_quality_profile_id = config.radarr.quality_profile_id
        self.radarr_root_folder_path = config.radarr.root_folder_path
        self.sonarr_quality_profile_id = config.sonarr.quality_profile_id
        self.sonarr_root_folder_path = config.sonarr.root_folder_path

    async def setup_hook(self) -> None:
        """Called when bot is starting up."""
        logger.info("Bot setup starting...")

        # Try to initialize services (don't crash if they fail)
        radarr_ok = await self._initialize_radarr()
        sonarr_ok = await self._initialize_sonarr()

        # Log status
        if radarr_ok and sonarr_ok:
            logger.info("All services initialized successfully")
        else:
            services_down = []
            if not radarr_ok:
                services_down.append("Radarr")
            if not sonarr_ok:
                services_down.append("Sonarr")
            logger.warning_structured(
                "Services unavailable at startup",
                services=services_down,
                message="Commands will be disabled until they reconnect"
            )

            # Start background retry task
            if self._config_retry_task is None or self._config_retry_task.done():
                self._config_retry_task = asyncio.create_task(
                    self._retry_unavailable_services()
                )
                logger.info("Started background service retry task")

        # Load cogs
        from .cogs.movies import MoviesCog
        from .cogs.shows import ShowsCog

        await self.add_cog(MoviesCog(self))
        await self.add_cog(ShowsCog(self))

        logger.info("Cogs loaded successfully")

    async def _initialize_radarr(self) -> bool:
        """
        Initialize Radarr configuration.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Auto-config quality profile if not set
            if not self.radarr_quality_profile_id:
                profile_id = await self.radarr.get_first_quality_profile_id()
                if profile_id:
                    self.radarr_quality_profile_id = profile_id
                    logger.info_structured(
                        "Auto-configured Radarr quality profile",
                        profile_id=profile_id
                    )
                else:
                    logger.warning("Radarr: No quality profiles available")
                    return False

            # Auto-config root folder if not set
            if not self.radarr_root_folder_path:
                root_path = await self.radarr.get_first_root_folder_path()
                if root_path:
                    self.radarr_root_folder_path = root_path
                    logger.info_structured(
                        "Auto-configured Radarr root folder",
                        path=root_path
                    )
                else:
                    logger.warning("Radarr: No root folders available")
                    return False

            self.radarr_available = True
            logger.info_structured(
                "Radarr connected successfully",
                root_folder=self.radarr_root_folder_path,
                quality_profile_id=self.radarr_quality_profile_id
            )
            return True

        except Exception as e:
            logger.warning_structured(
                "Radarr initialization failed",
                error=str(e)
            )
            self.radarr_available = False
            return False

    async def _initialize_sonarr(self) -> bool:
        """
        Initialize Sonarr configuration.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Auto-config quality profile if not set
            if not self.sonarr_quality_profile_id:
                profile_id = await self.sonarr.get_first_quality_profile_id()
                if profile_id:
                    self.sonarr_quality_profile_id = profile_id
                    logger.info_structured(
                        "Auto-configured Sonarr quality profile",
                        profile_id=profile_id
                    )
                else:
                    logger.warning("Sonarr: No quality profiles available")
                    return False

            # Auto-config root folder if not set
            if not self.sonarr_root_folder_path:
                root_path = await self.sonarr.get_first_root_folder_path()
                if root_path:
                    self.sonarr_root_folder_path = root_path
                    logger.info_structured(
                        "Auto-configured Sonarr root folder",
                        path=root_path
                    )
                else:
                    logger.warning("Sonarr: No root folders available")
                    return False

            self.sonarr_available = True
            logger.info_structured(
                "Sonarr connected successfully",
                root_folder=self.sonarr_root_folder_path,
                quality_profile_id=self.sonarr_quality_profile_id
            )
            return True

        except Exception as e:
            logger.warning_structured(
                "Sonarr initialization failed",
                error=str(e)
            )
            self.sonarr_available = False
            return False

    async def _retry_unavailable_services(self) -> None:
        """
        Background task to retry connecting to unavailable services.

        Runs periodically until all services are available.
        """
        while True:
            await asyncio.sleep(BACKGROUND_RETRY_INTERVAL)

            # Stop if all services are available
            if self.radarr_available and self.sonarr_available:
                logger.info("All services available, stopping retry task")
                break

            # Retry unavailable services
            if not self.radarr_available:
                logger.info("Retrying Radarr connection...")
                await self._initialize_radarr()

            if not self.sonarr_available:
                logger.info("Retrying Sonarr connection...")
                await self._initialize_sonarr()

    async def on_ready(self) -> None:
        """Called when bot is ready."""
        self._is_ready = True
        logger.info_structured(
            "Bot is ready",
            user=str(self.user),
            guilds=len(self.guilds)
        )

        # Sync commands
        try:
            synced = await self.tree.sync()
            logger.info_structured(
                "Commands synced",
                count=len(synced)
            )
        except Exception as e:
            logger.error_structured(
                "Failed to sync commands",
                error=str(e)
            )

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """Global error handler."""
        logger.error_structured(
            "Unhandled error in event",
            event=event_method,
            exc_info=True
        )

    async def close(self) -> None:
        """Graceful shutdown."""
        logger.info("Bot shutting down...")

        # Cancel retry task if running
        if self._config_retry_task and not self._config_retry_task.done():
            self._config_retry_task.cancel()
            try:
                await self._config_retry_task
            except asyncio.CancelledError:
                pass
            logger.info("Background retry task cancelled")

        # Close API clients
        await self.radarr.close()
        await self.sonarr.close()

        # Signal shutdown complete
        self._shutdown_event.set()

        await super().close()
        logger.info("Bot shutdown complete")

    def is_healthy(self) -> bool:
        """Check if bot is healthy for health checks."""
        return self._is_ready and not self.is_closed()

    async def health_check(self) -> dict:
        """
        Comprehensive health check.

        Returns:
            Dict with health status of all components
        """
        health = {
            "bot": self.is_healthy(),
            "radarr": False,
            "sonarr": False,
        }

        if self.is_healthy():
            # Check API connections
            health["radarr"] = await self.radarr.health_check()
            health["sonarr"] = await self.sonarr.health_check()

        health["healthy"] = all(health.values())
        return health

    def has_required_role(self, member: discord.Member) -> bool:
        """
        Check if member has required role for commands.

        Args:
            member: Discord member to check

        Returns:
            True if member has access
        """
        # If no roles configured, allow all
        if not self.allowed_role_ids:
            return True

        # Check if member has any allowed role
        member_role_ids = {role.id for role in member.roles}
        return bool(member_role_ids & set(self.allowed_role_ids))


def setup_signal_handlers(bot: GrabarrBot) -> None:
    """
    Setup signal handlers for graceful shutdown.

    Args:
        bot: Bot instance to shutdown
    """
    loop = asyncio.get_event_loop()

    def signal_handler(sig):
        logger.info_structured("Received shutdown signal", signal=sig.name)
        loop.create_task(bot.close())

    # Register handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            signal.signal(sig, lambda s, f: signal_handler(signal.Signals(s)))
