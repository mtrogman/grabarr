"""
Integration tests for end-to-end functionality.

These tests verify components work together correctly.
Requires mocked external services.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import AppConfig, BotConfig, RadarrConfig, SonarrConfig, LoggingConfig
from src.api.radarr import RadarrClient, Movie
from src.api.sonarr import SonarrClient, Show, MonitorOption
from src.utils import RateLimiter, validate_and_sanitize
from src.health import HealthServer


class TestEndToEndMovieRequest:
    """Integration tests for movie request flow."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return AppConfig(
            bot=BotConfig(
                token="test_token",
                rate_limit_requests=5,
                rate_limit_window_seconds=60,
            ),
            radarr=RadarrConfig(
                api_key="radarr_key",
                url="http://localhost:7878/api/v3",
                quality_profile_id=1,
                root_folder_path="/movies",
            ),
            sonarr=SonarrConfig(
                api_key="sonarr_key",
                url="http://localhost:8989/api/v3",
                quality_profile_id=1,
                root_folder_path="/tv",
            ),
            logging=LoggingConfig(),
        )

    @pytest.mark.asyncio
    async def test_movie_request_flow_new_movie(self, config):
        """Test complete flow for requesting a new movie."""
        # Setup
        radarr = RadarrClient(
            base_url=config.radarr.url,
            api_key=config.radarr.api_key
        )
        rate_limiter = RateLimiter(
            max_requests=config.bot.rate_limit_requests,
            window_seconds=config.bot.rate_limit_window_seconds
        )

        user_id = 12345
        search_term = "  Inception  "

        # Step 1: Validate and sanitize input
        clean_term = validate_and_sanitize(search_term)
        assert clean_term == "Inception"

        # Step 2: Check rate limit
        await rate_limiter.acquire(user_id)
        remaining = await rate_limiter.get_remaining(user_id)
        assert remaining == 4  # One request used

        # Step 3: Search for movie (mocked)
        with patch.object(
            radarr, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [
                {
                    "tmdbId": 27205,
                    "title": "Inception",
                    "year": 2010,
                    "overview": "A thief...",
                    "titleSlug": "inception",
                    "images": [],
                }
            ]

            movies = await radarr.search_movies(clean_term)
            assert len(movies) == 1
            assert movies[0].title == "Inception"

        # Step 4: Check if exists (mocked - not found)
        with patch.object(
            radarr, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = []

            existing = await radarr.get_movie_by_tmdb(27205)
            assert existing is None

        # Step 5: Add movie (mocked)
        with patch.object(
            radarr, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"id": 1}

            success = await radarr.add_movie(
                movie=movies[0],
                quality_profile_id=config.radarr.quality_profile_id,
                root_folder_path=config.radarr.root_folder_path
            )
            assert success is True

        await radarr.close()

    @pytest.mark.asyncio
    async def test_movie_request_flow_existing_movie(self, config):
        """Test complete flow for requesting an existing movie."""
        radarr = RadarrClient(
            base_url=config.radarr.url,
            api_key=config.radarr.api_key
        )

        # Search returns movie
        with patch.object(
            radarr, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [
                {
                    "id": 1,
                    "tmdbId": 27205,
                    "title": "Inception",
                    "year": 2010,
                    "overview": "",
                    "titleSlug": "inception",
                    "images": [],
                    "hasFile": False,
                }
            ]

            # Check exists - found without file
            existing = await radarr.get_movie_by_tmdb(27205)
            assert existing is not None
            assert existing.has_file is False

        # Should trigger search, not add
        with patch.object(
            radarr, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {}

            success = await radarr.search_existing_movie(1)
            assert success is True

            # Verify search command was sent
            call_args = mock_post.call_args
            assert call_args[0][0] == "/command"
            assert call_args[1]["data"]["name"] == "MoviesSearch"

        await radarr.close()


class TestEndToEndShowRequest:
    """Integration tests for show request flow."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return AppConfig(
            bot=BotConfig(token="test"),
            radarr=RadarrConfig(
                api_key="key",
                url="http://localhost:7878/api/v3"
            ),
            sonarr=SonarrConfig(
                api_key="sonarr_key",
                url="http://localhost:8989/api/v3",
                quality_profile_id=1,
                root_folder_path="/tv",
            ),
            logging=LoggingConfig(),
        )

    @pytest.mark.asyncio
    async def test_show_request_flow_with_season_selection(self, config):
        """Test complete flow with season selection."""
        sonarr = SonarrClient(
            base_url=config.sonarr.url,
            api_key=config.sonarr.api_key
        )

        # Step 1: Search shows
        with patch.object(
            sonarr, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [
                {
                    "tvdbId": 81189,
                    "title": "Breaking Bad",
                    "year": 2008,
                    "overview": "",
                    "titleSlug": "breaking-bad",
                    "images": [],
                }
            ]

            shows = await sonarr.search_shows("Breaking Bad")
            assert len(shows) == 1

        # Step 2: Check if exists (not found)
        with patch.object(
            sonarr, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = []

            existing = await sonarr.get_show_by_tvdb(81189)
            assert existing is None

        # Step 3: Add show with first season only
        with patch.object(
            sonarr, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"id": 1}

            success = await sonarr.add_show(
                show=shows[0],
                quality_profile_id=config.sonarr.quality_profile_id,
                root_folder_path=config.sonarr.root_folder_path,
                monitor_option=MonitorOption.FIRST_SEASON
            )
            assert success is True

            # Verify monitor option
            payload = mock_post.call_args[1]["data"]
            assert payload["addOptions"]["monitor"] == "firstSeason"

        await sonarr.close()


class TestRateLimiterIntegration:
    """Integration tests for rate limiting across requests."""

    @pytest.mark.asyncio
    async def test_rate_limit_enforced_across_requests(self):
        """Test that rate limit is enforced across multiple requests."""
        rate_limiter = RateLimiter(max_requests=3, window_seconds=60)

        user_id = 12345
        blocked_count = 0

        # Simulate user making many requests
        for i in range(10):
            try:
                await rate_limiter.acquire(user_id)
            except Exception:
                blocked_count += 1

        assert blocked_count == 7  # 3 allowed, 7 blocked

    @pytest.mark.asyncio
    async def test_different_users_independent(self):
        """Test that rate limits are independent per user."""
        rate_limiter = RateLimiter(max_requests=2, window_seconds=60)

        user1_blocked = 0
        user2_blocked = 0

        for _ in range(5):
            try:
                await rate_limiter.acquire(1)
            except Exception:
                user1_blocked += 1

            try:
                await rate_limiter.acquire(2)
            except Exception:
                user2_blocked += 1

        # Each user should have 2 allowed, 3 blocked
        assert user1_blocked == 3
        assert user2_blocked == 3


class TestHealthServerIntegration:
    """Integration tests for health server."""

    @pytest.mark.asyncio
    async def test_health_endpoints(self):
        """Test health server endpoints."""
        # Create mock bot
        mock_bot = MagicMock()
        mock_bot.is_healthy.return_value = True
        mock_bot.guilds = [MagicMock(), MagicMock()]
        mock_bot.latency = 0.05

        async def mock_health_check():
            return {"healthy": True, "bot": True, "radarr": True, "sonarr": True}

        mock_bot.health_check = mock_health_check

        # Create and start server
        server = HealthServer(mock_bot, host="127.0.0.1", port=18080)
        await server.start()

        try:
            # Test health endpoint via aiohttp client
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get("http://127.0.0.1:18080/health") as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["status"] == "alive"

                async with session.get("http://127.0.0.1:18080/ready") as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["healthy"] is True

                async with session.get("http://127.0.0.1:18080/metrics") as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert "bot_ready" in data
                    assert data["guilds"] == 2

        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_health_server_unhealthy_state(self):
        """Test health server when bot is unhealthy."""
        mock_bot = MagicMock()
        mock_bot.is_healthy.return_value = False
        mock_bot.guilds = []
        mock_bot.latency = 0

        async def mock_health_check():
            return {"healthy": False, "bot": False, "radarr": False, "sonarr": False}

        mock_bot.health_check = mock_health_check

        server = HealthServer(mock_bot, host="127.0.0.1", port=18081)
        await server.start()

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get("http://127.0.0.1:18081/ready") as resp:
                    # Should return 503 when unhealthy
                    assert resp.status == 503
                    data = await resp.json()
                    assert data["healthy"] is False

        finally:
            await server.stop()


class TestConfigurationIntegration:
    """Integration tests for configuration loading."""

    @pytest.mark.asyncio
    async def test_full_config_to_client_flow(self, temp_config_file, clean_environment):
        """Test loading config and creating clients."""
        from src.config import load_config, validate_config

        # Load configuration
        config = load_config(str(temp_config_file))

        # Validate
        errors = validate_config(config)
        assert errors == []

        # Create clients
        radarr = RadarrClient(
            base_url=config.radarr.url,
            api_key=config.radarr.api_key,
            timeout=config.http_timeout,
            max_retries=config.http_max_retries,
            retry_delay=config.http_retry_delay
        )

        sonarr = SonarrClient(
            base_url=config.sonarr.url,
            api_key=config.sonarr.api_key,
            timeout=config.http_timeout,
            max_retries=config.http_max_retries,
            retry_delay=config.http_retry_delay
        )

        # Verify clients configured correctly
        assert radarr.api_key == "radarr_key_123"
        assert sonarr.api_key == "sonarr_key_456"
        assert radarr.max_retries == 3
        assert sonarr.max_retries == 3

        await radarr.close()
        await sonarr.close()
