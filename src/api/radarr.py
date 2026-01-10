"""
Radarr API client for movie management.

Provides async methods for:
- Searching movies
- Adding movies to library
- Triggering downloads
- Managing quality profiles
"""

from dataclasses import dataclass
from typing import Optional

from .base import APIClient, APIError
from ..logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Movie:
    """Movie data model."""
    tmdb_id: int
    title: str
    year: Optional[int]
    overview: str
    title_slug: str
    images: list
    has_file: bool = False
    radarr_id: Optional[int] = None

    @classmethod
    def from_lookup(cls, data: dict) -> "Movie":
        """Create Movie from lookup API response."""
        return cls(
            tmdb_id=data.get("tmdbId", 0),
            title=data.get("title", "Unknown"),
            year=data.get("year"),
            overview=data.get("overview", "No description available."),
            title_slug=data.get("titleSlug", ""),
            images=data.get("images", []),
        )

    @classmethod
    def from_library(cls, data: dict) -> "Movie":
        """Create Movie from library API response."""
        return cls(
            tmdb_id=data.get("tmdbId", 0),
            title=data.get("title", "Unknown"),
            year=data.get("year"),
            overview=data.get("overview", "No description available."),
            title_slug=data.get("titleSlug", ""),
            images=data.get("images", []),
            has_file=bool(data.get("hasFile")) or bool(data.get("movieFile")),
            radarr_id=data.get("id"),
        )


@dataclass
class QualityProfile:
    """Quality profile data model."""
    id: int
    name: str


@dataclass
class RootFolder:
    """Root folder data model."""
    path: str
    free_space: int


class RadarrClient(APIClient):
    """Async Radarr API client."""

    async def search_movies(self, term: str, limit: int = 10) -> list[Movie]:
        """
        Search for movies by title.

        Args:
            term: Search term
            limit: Maximum results to return

        Returns:
            List of Movie objects
        """
        logger.info_structured("Searching movies", term=term)

        try:
            results = await self.get("/movie/lookup", params={"term": term})
            if not results:
                return []

            movies = [Movie.from_lookup(m) for m in results[:limit]]
            logger.info_structured(
                "Movie search completed",
                term=term,
                results=len(movies)
            )
            return movies

        except APIError as e:
            logger.error_structured(
                "Movie search failed",
                term=term,
                error=str(e)
            )
            return []

    async def get_movie_by_tmdb(self, tmdb_id: int) -> Optional[Movie]:
        """
        Get movie from library by TMDB ID.

        Args:
            tmdb_id: TMDB movie ID

        Returns:
            Movie if found in library, None otherwise
        """
        try:
            results = await self.get("/movie", params={"tmdbId": tmdb_id})
            if results and isinstance(results, list) and len(results) > 0:
                return Movie.from_library(results[0])
            return None

        except APIError as e:
            logger.error_structured(
                "Failed to get movie by TMDB ID",
                tmdb_id=tmdb_id,
                error=str(e)
            )
            return None

    async def add_movie(
        self,
        movie: Movie,
        quality_profile_id: int,
        root_folder_path: str,
        search_for_movie: bool = True
    ) -> bool:
        """
        Add movie to library and optionally search.

        Args:
            movie: Movie to add
            quality_profile_id: Quality profile ID
            root_folder_path: Root folder path for downloads
            search_for_movie: Whether to search for movie after adding

        Returns:
            True if successful, False otherwise
        """
        payload = {
            "tmdbId": movie.tmdb_id,
            "title": movie.title,
            "year": movie.year,
            "qualityProfileId": quality_profile_id,
            "titleSlug": movie.title_slug or f"{movie.title}-{movie.tmdb_id}",
            "images": movie.images,
            "monitored": True,
            "rootFolderPath": root_folder_path,
            "addOptions": {"searchForMovie": search_for_movie},
        }

        try:
            await self.post("/movie", data=payload)
            logger.info_structured(
                "Movie added to library",
                title=movie.title,
                tmdb_id=movie.tmdb_id,
                search=search_for_movie
            )
            return True

        except APIError as e:
            logger.error_structured(
                "Failed to add movie",
                title=movie.title,
                tmdb_id=movie.tmdb_id,
                error=str(e)
            )
            return False

    async def search_existing_movie(self, radarr_id: int) -> bool:
        """
        Trigger search for existing movie.

        Args:
            radarr_id: Radarr movie ID

        Returns:
            True if search triggered, False otherwise
        """
        payload = {
            "name": "MoviesSearch",
            "movieIds": [radarr_id]
        }

        try:
            await self.post("/command", data=payload)
            logger.info_structured(
                "Triggered search for existing movie",
                radarr_id=radarr_id
            )
            return True

        except APIError as e:
            logger.error_structured(
                "Failed to trigger movie search",
                radarr_id=radarr_id,
                error=str(e)
            )
            return False

    async def get_quality_profiles(self) -> list[QualityProfile]:
        """Get available quality profiles."""
        try:
            results = await self.get("/qualityprofile")
            return [
                QualityProfile(id=p["id"], name=p["name"])
                for p in results
            ]
        except APIError as e:
            logger.error_structured("Failed to get quality profiles", error=str(e))
            return []

    async def get_root_folders(self) -> list[RootFolder]:
        """Get available root folders."""
        try:
            results = await self.get("/rootfolder")
            return [
                RootFolder(path=f["path"], free_space=f.get("freeSpace", 0))
                for f in results
            ]
        except APIError as e:
            logger.error_structured("Failed to get root folders", error=str(e))
            return []

    async def get_first_quality_profile_id(self) -> Optional[int]:
        """Get ID of first quality profile."""
        profiles = await self.get_quality_profiles()
        return profiles[0].id if profiles else None

    async def get_first_root_folder_path(self) -> Optional[str]:
        """Get path of first root folder."""
        folders = await self.get_root_folders()
        return folders[0].path if folders else None
