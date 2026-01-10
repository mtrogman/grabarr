"""
Health check HTTP server for container orchestration.

Provides endpoints for:
- /health - Basic liveness check
- /ready - Readiness check with dependency status
- /metrics - Basic metrics (can be extended for Prometheus)
"""

import asyncio
import json
from typing import TYPE_CHECKING, Callable, Optional

from aiohttp import web

from .logging_config import get_logger

if TYPE_CHECKING:
    from .discord_bot.bot import GrabarrBot

logger = get_logger(__name__)


class HealthServer:
    """
    HTTP server for health checks.

    Designed for Kubernetes/Docker health probes.
    """

    def __init__(
        self,
        bot: "GrabarrBot",
        host: str = "0.0.0.0",
        port: int = 8080
    ):
        """
        Initialize health server.

        Args:
            bot: GrabarrBot instance for health checks
            host: Host to bind to
            port: Port to listen on
        """
        self.bot = bot
        self.host = host
        self.port = port
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        # Metrics counters
        self.request_count = 0
        self.error_count = 0

    async def _health_handler(self, request: web.Request) -> web.Response:
        """
        Liveness probe handler.

        Returns 200 if process is alive.
        """
        return web.json_response({"status": "alive"})

    async def _ready_handler(self, request: web.Request) -> web.Response:
        """
        Readiness probe handler.

        Returns 200 if bot and all dependencies are healthy.
        """
        health_status = await self.bot.health_check()

        if health_status["healthy"]:
            return web.json_response(health_status)
        else:
            return web.json_response(health_status, status=503)

    async def _metrics_handler(self, request: web.Request) -> web.Response:
        """
        Basic metrics handler.

        Returns JSON metrics (can be extended for Prometheus format).
        """
        metrics = {
            "bot_ready": self.bot.is_healthy(),
            "guilds": len(self.bot.guilds) if self.bot.is_healthy() else 0,
            "latency_ms": round(self.bot.latency * 1000, 2) if self.bot.is_healthy() else None,
            "request_count": self.request_count,
            "error_count": self.error_count,
        }
        return web.json_response(metrics)

    async def start(self) -> None:
        """Start the health check server."""
        self._app = web.Application()
        self._app.router.add_get("/health", self._health_handler)
        self._app.router.add_get("/ready", self._ready_handler)
        self._app.router.add_get("/metrics", self._metrics_handler)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        logger.info_structured(
            "Health server started",
            host=self.host,
            port=self.port
        )

    async def stop(self) -> None:
        """Stop the health check server."""
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        logger.info("Health server stopped")

    def increment_request_count(self) -> None:
        """Increment request counter."""
        self.request_count += 1

    def increment_error_count(self) -> None:
        """Increment error counter."""
        self.error_count += 1
