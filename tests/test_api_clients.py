"""
Tests for API clients (Radarr and Sonarr).

Tests:
- HTTP request handling
- Response parsing
- Error handling
- Retry logic
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponseError, ClientConnectionError

from src.api.base import APIClient, APIError
from src.api.radarr import RadarrClient, Movie
from src.api.sonarr import SonarrClient, Show, MonitorOption


class TestAPIClient:
    """Tests for base APIClient class."""

    @pytest.fixture
    def client(self):
        """Create a test API client."""
        return APIClient(
            base_url="http://localhost:8989/api/v3",
            api_key="test_api_key",
            timeout=5,
            max_retries=2,
            retry_delay=0.1
        )

    def test_headers_include_api_key(self, client):
        """Test that headers include API key."""
        assert "X-Api-Key" in client._headers
        assert client._headers["X-Api-Key"] == "test_api_key"

    def test_headers_include_content_type(self, client):
        """Test that headers include content type."""
        assert client._headers["Content-Type"] == "application/json"

    def test_base_url_normalized(self):
        """Test that base URL trailing slash is removed."""
        client = APIClient(
            base_url="http://localhost:8989/api/v3/",
            api_key="key"
        )
        assert client.base_url == "http://localhost:8989/api/v3"

    @pytest.mark.asyncio
    async def test_close_session(self, client):
        """Test closing the session."""
        # Create a session first
        await client._get_session()
        assert client._session is not None

        # Close it
        await client.close()
        assert client._session is None or client._session.closed


class TestRadarrClient:
    """Tests for RadarrClient class."""

    @pytest.fixture
    def radarr_client(self):
        """Create a Radarr client for testing."""
        return RadarrClient(
            base_url="http://localhost:7878/api/v3",
            api_key="test_radarr_key",
            timeout=5,
            max_retries=2,
            retry_delay=0.1
        )

    @pytest.mark.asyncio
    async def test_search_movies_success(
        self,
        radarr_client,
        mock_radarr_movie_response
    ):
        """Test successful movie search."""
        with patch.object(
            radarr_client,
            "get",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_radarr_movie_response

            movies = await radarr_client.search_movies("Inception")

            assert len(movies) == 2
            assert movies[0].title == "Inception"
            assert movies[0].tmdb_id == 27205
            assert movies[1].title == "Interstellar"

            mock_get.assert_called_once_with(
                "/movie/lookup",
                params={"term": "Inception"}
            )

    @pytest.mark.asyncio
    async def test_search_movies_empty_results(self, radarr_client):
        """Test movie search with no results."""
        with patch.object(
            radarr_client,
            "get",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = []

            movies = await radarr_client.search_movies("NonexistentMovie123")

            assert len(movies) == 0

    @pytest.mark.asyncio
    async def test_search_movies_api_error(self, radarr_client):
        """Test movie search with API error."""
        with patch.object(
            radarr_client,
            "get",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = APIError("Connection failed")

            movies = await radarr_client.search_movies("Inception")

            assert len(movies) == 0  # Returns empty list on error

    @pytest.mark.asyncio
    async def test_get_movie_by_tmdb_found(
        self,
        radarr_client,
        mock_radarr_movie_response
    ):
        """Test getting movie by TMDB ID when found."""
        with patch.object(
            radarr_client,
            "get",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [
                {**mock_radarr_movie_response[0], "id": 1, "hasFile": True}
            ]

            movie = await radarr_client.get_movie_by_tmdb(27205)

            assert movie is not None
            assert movie.tmdb_id == 27205
            assert movie.has_file is True
            assert movie.radarr_id == 1

    @pytest.mark.asyncio
    async def test_get_movie_by_tmdb_not_found(self, radarr_client):
        """Test getting movie by TMDB ID when not found."""
        with patch.object(
            radarr_client,
            "get",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = []

            movie = await radarr_client.get_movie_by_tmdb(99999)

            assert movie is None

    @pytest.mark.asyncio
    async def test_add_movie_success(self, radarr_client):
        """Test adding a movie successfully."""
        movie = Movie(
            tmdb_id=27205,
            title="Inception",
            year=2010,
            overview="A thief...",
            title_slug="inception-27205",
            images=[]
        )

        with patch.object(
            radarr_client,
            "post",
            new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"id": 1}

            success = await radarr_client.add_movie(
                movie=movie,
                quality_profile_id=1,
                root_folder_path="/movies"
            )

            assert success is True
            mock_post.assert_called_once()

            # Verify payload
            call_args = mock_post.call_args
            payload = call_args[1]["data"]
            assert payload["tmdbId"] == 27205
            assert payload["title"] == "Inception"
            assert payload["qualityProfileId"] == 1
            assert payload["rootFolderPath"] == "/movies"
            assert payload["addOptions"]["searchForMovie"] is True

    @pytest.mark.asyncio
    async def test_add_movie_failure(self, radarr_client):
        """Test adding a movie when API fails."""
        movie = Movie(
            tmdb_id=27205,
            title="Inception",
            year=2010,
            overview="",
            title_slug="",
            images=[]
        )

        with patch.object(
            radarr_client,
            "post",
            new_callable=AsyncMock
        ) as mock_post:
            mock_post.side_effect = APIError("Failed")

            success = await radarr_client.add_movie(
                movie=movie,
                quality_profile_id=1,
                root_folder_path="/movies"
            )

            assert success is False

    @pytest.mark.asyncio
    async def test_get_quality_profiles(
        self,
        radarr_client,
        mock_quality_profiles
    ):
        """Test getting quality profiles."""
        with patch.object(
            radarr_client,
            "get",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_quality_profiles

            profiles = await radarr_client.get_quality_profiles()

            assert len(profiles) == 3
            assert profiles[0].id == 1
            assert profiles[0].name == "HD-1080p"

    @pytest.mark.asyncio
    async def test_get_root_folders(
        self,
        radarr_client,
        mock_root_folders
    ):
        """Test getting root folders."""
        with patch.object(
            radarr_client,
            "get",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_root_folders

            folders = await radarr_client.get_root_folders()

            assert len(folders) == 2
            assert folders[0].path == "/movies"


class TestSonarrClient:
    """Tests for SonarrClient class."""

    @pytest.fixture
    def sonarr_client(self):
        """Create a Sonarr client for testing."""
        return SonarrClient(
            base_url="http://localhost:8989/api/v3",
            api_key="test_sonarr_key",
            timeout=5,
            max_retries=2,
            retry_delay=0.1
        )

    @pytest.mark.asyncio
    async def test_search_shows_success(
        self,
        sonarr_client,
        mock_sonarr_show_response
    ):
        """Test successful show search."""
        with patch.object(
            sonarr_client,
            "get",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_sonarr_show_response

            shows = await sonarr_client.search_shows("Breaking Bad")

            assert len(shows) == 2
            assert shows[0].title == "Breaking Bad"
            assert shows[0].tvdb_id == 81189
            assert shows[1].title == "Better Call Saul"

    @pytest.mark.asyncio
    async def test_add_show_with_monitor_option(self, sonarr_client):
        """Test adding a show with monitor option."""
        show = Show(
            tvdb_id=81189,
            title="Breaking Bad",
            year=2008,
            overview="",
            title_slug="breaking-bad",
            images=[]
        )

        with patch.object(
            sonarr_client,
            "post",
            new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"id": 1}

            success = await sonarr_client.add_show(
                show=show,
                quality_profile_id=1,
                root_folder_path="/tv",
                monitor_option=MonitorOption.FIRST_SEASON
            )

            assert success is True

            # Verify payload
            payload = mock_post.call_args[1]["data"]
            assert payload["addOptions"]["monitor"] == "firstSeason"


class TestMovieModel:
    """Tests for Movie data model."""

    def test_from_lookup(self, mock_radarr_movie_response):
        """Test creating Movie from lookup response."""
        movie = Movie.from_lookup(mock_radarr_movie_response[0])

        assert movie.tmdb_id == 27205
        assert movie.title == "Inception"
        assert movie.year == 2010
        assert movie.has_file is False

    def test_from_library(self):
        """Test creating Movie from library response."""
        data = {
            "id": 1,
            "tmdbId": 27205,
            "title": "Inception",
            "year": 2010,
            "overview": "A thief...",
            "titleSlug": "inception",
            "images": [],
            "hasFile": True,
            "movieFile": {"id": 1},
        }

        movie = Movie.from_library(data)

        assert movie.radarr_id == 1
        assert movie.has_file is True


class TestShowModel:
    """Tests for Show data model."""

    def test_from_lookup(self, mock_sonarr_show_response):
        """Test creating Show from lookup response."""
        show = Show.from_lookup(mock_sonarr_show_response[0])

        assert show.tvdb_id == 81189
        assert show.title == "Breaking Bad"
        assert show.year == 2008

    def test_from_library(self):
        """Test creating Show from library response."""
        data = {
            "id": 1,
            "tvdbId": 81189,
            "title": "Breaking Bad",
            "year": 2008,
            "overview": "",
            "titleSlug": "breaking-bad",
            "images": [],
        }

        show = Show.from_library(data)

        assert show.sonarr_id == 1
        assert show.tvdb_id == 81189


class TestMonitorOption:
    """Tests for MonitorOption enum."""

    def test_display_names(self):
        """Test display names for monitor options."""
        assert MonitorOption.ALL.display_name == "All Seasons"
        assert MonitorOption.FIRST_SEASON.display_name == "First Season"
        assert MonitorOption.LAST_SEASON.display_name == "Latest Season"

    def test_values(self):
        """Test enum values match Sonarr API."""
        assert MonitorOption.ALL.value == "all"
        assert MonitorOption.FIRST_SEASON.value == "firstSeason"
        assert MonitorOption.LAST_SEASON.value == "lastSeason"
