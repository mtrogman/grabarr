"""
Movie request commands and UI components.

Provides slash commands for searching and requesting movies through Radarr.
"""

from typing import TYPE_CHECKING
import uuid

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View, Button

from ...api.radarr import Movie
from ...logging_config import get_logger, set_correlation_id, clear_correlation_id
from ...utils import RateLimitExceeded, validate_and_sanitize, ValidationError

if TYPE_CHECKING:
    from ..bot import GrabarrBot

logger = get_logger(__name__)


class ConfirmMovieView(View):
    """Confirmation buttons for movie request."""

    def __init__(
        self,
        bot: "GrabarrBot",
        original_interaction: discord.Interaction,
        movie: Movie
    ):
        super().__init__(timeout=180)
        self.bot = bot
        self.original_interaction = original_interaction
        self.movie = movie

    @discord.ui.button(label="Request", style=discord.ButtonStyle.success)
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: Button
    ) -> None:
        """Handle request confirmation."""
        # Delete the ephemeral message
        try:
            await self.original_interaction.delete_original_response()
        except Exception:
            pass

        # Disable buttons
        self.disable_all_items()

        # Send public status message
        status_msg = await interaction.channel.send(
            "🔎 Working on your movie request..."
        )

        # Log the request
        logger.audit(
            action="request_movie",
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            movie_title=self.movie.title,
            tmdb_id=self.movie.tmdb_id
        )

        # Check if movie exists in library
        existing = await self.bot.radarr.get_movie_by_tmdb(self.movie.tmdb_id)

        if existing:
            if existing.has_file:
                # Already downloaded
                await status_msg.edit(
                    content=f"💤 **{interaction.user.display_name}** — "
                    f"**{self.movie.title} ({self.movie.year or 'N/A'})** "
                    f"already exists and is downloaded."
                )
                return

            # Exists but no file - trigger search
            success = await self.bot.radarr.search_existing_movie(existing.radarr_id)
            if success:
                await status_msg.edit(
                    content=f"🔎 **{interaction.user.display_name}** — "
                    f"searching for **{self.movie.title} ({self.movie.year or 'N/A'})**."
                )
            else:
                await status_msg.edit(
                    content=f"❌ **{interaction.user.display_name}** — "
                    f"couldn't start a search for **{self.movie.title} "
                    f"({self.movie.year or 'N/A'})**. Try again later."
                )
            return

        # Add movie to library
        success = await self.bot.radarr.add_movie(
            movie=self.movie,
            quality_profile_id=self.bot.radarr_quality_profile_id,
            root_folder_path=self.bot.radarr_root_folder_path,
            search_for_movie=True
        )

        if success:
            await status_msg.edit(
                content=f"🔎 **{interaction.user.display_name}** — "
                f"requested **{self.movie.title} ({self.movie.year or 'N/A'})** "
                f"and started search."
            )
        else:
            await status_msg.edit(
                content=f"❌ **{interaction.user.display_name}** — "
                f"request for **{self.movie.title} ({self.movie.year or 'N/A'})** "
                f"failed. Try again later."
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: Button
    ) -> None:
        """Handle cancellation."""
        self.disable_all_items()
        await interaction.response.edit_message(
            content="Request cancelled.",
            view=None
        )

    def disable_all_items(self) -> None:
        """Disable all buttons."""
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = True


class MovieSelector(Select):
    """Dropdown selector for movie search results."""

    def __init__(self, bot: "GrabarrBot", movies: list[Movie]):
        self.bot = bot
        self.movies = movies

        options = [
            discord.SelectOption(
                label=f"{m.title} ({m.year or 'N/A'})"[:100],
                value=str(i),
                description=m.overview[:100] if m.overview else None
            )
            for i, m in enumerate(movies)
        ]

        super().__init__(
            placeholder="Choose a movie",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle movie selection."""
        index = int(self.values[0])
        movie = self.movies[index]

        # Show movie details and confirm buttons
        view = ConfirmMovieView(self.bot, interaction, movie)
        overview = movie.overview or "No description available."

        # Truncate overview if too long
        if len(overview) > 1000:
            overview = overview[:997] + "..."

        msg = (
            f"**{movie.title} ({movie.year or 'N/A'})**\n"
            f"{overview}\n\n"
            f"Confirm your request."
        )

        await interaction.response.edit_message(content=msg, view=view)


class MovieSelectorView(View):
    """View containing movie selector dropdown."""

    def __init__(self, bot: "GrabarrBot", movies: list[Movie]):
        super().__init__(timeout=180)
        self.add_item(MovieSelector(bot, movies))


class MoviesCog(commands.Cog):
    """Cog for movie-related commands."""

    def __init__(self, bot: "GrabarrBot"):
        self.bot = bot

    @app_commands.command(
        name="request_movie",
        description="Request a movie via Radarr"
    )
    @app_commands.describe(title="Movie title to search for")
    async def request_movie(
        self,
        interaction: discord.Interaction,
        title: str
    ) -> None:
        """
        Search and request a movie.

        Args:
            interaction: Discord interaction
            title: Movie title to search
        """
        # Set correlation ID for request tracing
        correlation_id = str(uuid.uuid4())[:8]
        set_correlation_id(correlation_id)

        try:
            # Check role-based access
            if not self.bot.has_required_role(interaction.user):
                await interaction.response.send_message(
                    "You don't have permission to use this command.",
                    ephemeral=True
                )
                return

            # Check rate limit
            try:
                await self.bot.rate_limiter.acquire(interaction.user.id)
            except RateLimitExceeded as e:
                await interaction.response.send_message(
                    f"Rate limit exceeded. Try again in {e.retry_after:.0f} seconds.",
                    ephemeral=True
                )
                return

            # Validate and sanitize input
            try:
                clean_title = validate_and_sanitize(title)
            except ValidationError as e:
                await interaction.response.send_message(
                    f"Invalid search term: {e}",
                    ephemeral=True
                )
                return

            # Defer response for long operation
            await interaction.response.defer(ephemeral=True)

            # Show searching message
            searching_msg = await interaction.followup.send(
                "🔎 Searching for movies...",
                ephemeral=True
            )

            # Search movies
            movies = await self.bot.radarr.search_movies(clean_title)

            if not movies:
                await searching_msg.edit(
                    content="No movies found with that title."
                )
                return

            # Show selector
            await searching_msg.edit(
                content="Select a movie to request:",
                view=MovieSelectorView(self.bot, movies)
            )

        finally:
            clear_correlation_id()


async def setup(bot: "GrabarrBot") -> None:
    """Setup function for loading cog."""
    await bot.add_cog(MoviesCog(bot))
