"""
Sonarr API client for TV show management.

Provides async methods for:
- Searching TV shows
- Adding shows to library
- Triggering downloads
- Managing quality profiles
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .base import APIClient, APIError
from ..logging_config import get_logger

logger = get_logger(__name__)


class MonitorOption(str, Enum):
    """Season monitoring options."""
    ALL = "all"
    FIRST_SEASON = "firstSeason"
    LAST_SEASON = "lastSeason"
    FUTURE = "future"
    MISSING = "missing"
    EXISTING = "existing"
    NONE = "none"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        names = {
            "all": "All Seasons",
            "firstSeason": "First Season",
            "lastSeason": "Latest Season",
            "future": "Future Episodes",
            "missing": "Missing Episodes",
            "existing": "Existing Episodes",
            "none": "None",
        }
        return names.get(self.value, self.value)


@dataclass
class Show:
    """TV show data model."""
    tvdb_id: int
    title: str
    year: Optional[int]
    overview: str
    title_slug: str
    images: list
    sonarr_id: Optional[int] = None

    @classmethod
    def from_lookup(cls, data: dict) -> "Show":
        """Create Show from lookup API response."""
        return cls(
            tvdb_id=data.get("tvdbId", 0),
            title=data.get("title", "Unknown"),
            year=data.get("year"),
            overview=data.get("overview", "No description available."),
            title_slug=data.get("titleSlug", ""),
            images=data.get("images", []),
        )

    @classmethod
    def from_library(cls, data: dict) -> "Show":
        """Create Show from library API response."""
        return cls(
            tvdb_id=data.get("tvdbId", 0),
            title=data.get("title", "Unknown"),
            year=data.get("year"),
            overview=data.get("overview", "No description available."),
            title_slug=data.get("titleSlug", ""),
            images=data.get("images", []),
            sonarr_id=data.get("id"),
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


class SonarrClient(APIClient):
    """Async Sonarr API client."""

    async def search_shows(self, term: str, limit: int = 10) -> list[Show]:
        """
        Search for TV shows by title.

        Args:
            term: Search term
            limit: Maximum results to return

        Returns:
            List of Show objects
        """
        logger.info_structured("Searching shows", term=term)

        try:
            results = await self.get("/series/lookup", params={"term": term})
            if not results:
                return []

            shows = [Show.from_lookup(s) for s in results[:limit]]
            logger.info_structured(
                "Show search completed",
                term=term,
                results=len(shows)
            )
            return shows

        except APIError as e:
            logger.error_structured(
                "Show search failed",
                term=term,
                error=str(e)
            )
            return []

    async def get_show_by_tvdb(self, tvdb_id: int) -> Optional[Show]:
        """
        Get show from library by TVDB ID.

        Uses optimized API endpoint instead of fetching all series.

        Args:
            tvdb_id: TVDB show ID

        Returns:
            Show if found in library, None otherwise
        """
        try:
            # Use lookup endpoint with tvdbId to check if show exists
            # This is more efficient than fetching all series
            results = await self.get("/series", params={"tvdbId": tvdb_id})
            if results and isinstance(results, list) and len(results) > 0:
                return Show.from_library(results[0])
            return None

        except APIError as e:
            # Fallback: search all series (less efficient)
            logger.warning_structured(
                "Optimized lookup failed, falling back to full search",
                tvdb_id=tvdb_id,
                error=str(e)
            )
            return await self._get_show_by_tvdb_fallback(tvdb_id)

    async def _get_show_by_tvdb_fallback(self, tvdb_id: int) -> Optional[Show]:
        """Fallback method to find show by searching all series."""
        try:
            all_series = await self.get("/series")
            if not all_series:
                return None

            for series in all_series:
                if series.get("tvdbId") == tvdb_id:
                    return Show.from_library(series)
            return None

        except APIError as e:
            logger.error_structured(
                "Failed to get show by TVDB ID (fallback)",
                tvdb_id=tvdb_id,
                error=str(e)
            )
            return None

    async def add_show(
        self,
        show: Show,
        quality_profile_id: int,
        root_folder_path: str,
        monitor_option: MonitorOption = MonitorOption.ALL,
        search_for_missing: bool = True
    ) -> bool:
        """
        Add show to library and optionally search.

        Args:
            show: Show to add
            quality_profile_id: Quality profile ID
            root_folder_path: Root folder path for downloads
            monitor_option: Which seasons to monitor
            search_for_missing: Whether to search for missing episodes

        Returns:
            True if successful, False otherwise
        """
        payload = {
            "title": show.title,
            "tvdbId": show.tvdb_id,
            "qualityProfileId": quality_profile_id,
            "titleSlug": show.title_slug or f"{show.title}-{show.tvdb_id}",
            "images": show.images,
            "monitored": True,
            "rootFolderPath": root_folder_path,
            "addOptions": {
                "monitor": monitor_option.value,
                "searchForMissingEpisodes": search_for_missing,
            },
        }

        try:
            await self.post("/series", data=payload)
            logger.info_structured(
                "Show added to library",
                title=show.title,
                tvdb_id=show.tvdb_id,
                monitor=monitor_option.value,
                search=search_for_missing
            )
            return True

        except APIError as e:
            logger.error_structured(
                "Failed to add show",
                title=show.title,
                tvdb_id=show.tvdb_id,
                error=str(e)
            )
            return False

    async def search_existing_show(self, sonarr_id: int) -> bool:
        """
        Trigger search for existing show.

        Args:
            sonarr_id: Sonarr series ID

        Returns:
            True if search triggered, False otherwise
        """
        payload = {
            "name": "SeriesSearch",
            "seriesId": sonarr_id
        }

        try:
            await self.post("/command", data=payload)
            logger.info_structured(
                "Triggered search for existing show",
                sonarr_id=sonarr_id
            )
            return True

        except APIError as e:
            logger.error_structured(
                "Failed to trigger show search",
                sonarr_id=sonarr_id,
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
