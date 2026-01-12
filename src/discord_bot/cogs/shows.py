"""
TV show request commands and UI components.

Provides slash commands for searching and requesting TV shows through Sonarr.
"""

from typing import TYPE_CHECKING
import uuid

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View, Button

from ...api.sonarr import Show, MonitorOption
from ...logging_config import get_logger, set_correlation_id, clear_correlation_id
from ...utils import RateLimitExceeded, validate_and_sanitize, ValidationError

if TYPE_CHECKING:
    from ..bot import GrabarrBot

logger = get_logger(__name__)


class ConfirmShowView(View):
    """Confirmation buttons for show request."""

    def __init__(
        self,
        bot: "GrabarrBot",
        original_interaction: discord.Interaction,
        show: Show,
        monitor_option: MonitorOption
    ):
        super().__init__(timeout=180)
        self.bot = bot
        self.original_interaction = original_interaction
        self.show = show
        self.monitor_option = monitor_option

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
            "🔎 Working on your series request..."
        )

        # Log the request
        logger.audit(
            action="request_show",
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            show_title=self.show.title,
            tvdb_id=self.show.tvdb_id,
            monitor_option=self.monitor_option.value
        )

        # Check if show exists in library
        existing = await self.bot.sonarr.get_show_by_tvdb(self.show.tvdb_id)

        if existing and existing.sonarr_id:
            # Show exists - trigger search for monitored episodes
            success = await self.bot.sonarr.search_existing_show(existing.sonarr_id)
            if success:
                await status_msg.edit(
                    content=f"🔎 **{interaction.user.display_name}** — "
                    f"**{self.show.title}** exists already; "
                    f"retriggering search for all monitored episodes."
                )
            else:
                await status_msg.edit(
                    content=f"❌ **{interaction.user.display_name}** — "
                    f"search for **{self.show.title}** failed. Try again later."
                )
            return

        # Add show to library
        success = await self.bot.sonarr.add_show(
            show=self.show,
            quality_profile_id=self.bot.sonarr_quality_profile_id,
            root_folder_path=self.bot.sonarr_root_folder_path,
            monitor_option=self.monitor_option,
            search_for_missing=True
        )

        year = self.show.year or 'N/A'
        if success:
            await status_msg.edit(
                content=f"🔎 **{interaction.user.display_name}** — "
                f"added **{self.show.title} ({year})** and "
                f"searching for missing episodes."
            )
        else:
            await status_msg.edit(
                content=f"❌ **{interaction.user.display_name}** — "
                f"request for **{self.show.title} ({year})** failed. "
                f"Try again later."
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


class SeasonSelector(Select):
    """Dropdown selector for season monitoring option."""

    def __init__(self, bot: "GrabarrBot", show: Show):
        self.bot = bot
        self.show = show

        options = [
            discord.SelectOption(
                label="All Seasons",
                value=MonitorOption.ALL.value,
                description="Monitor and download all seasons"
            ),
            discord.SelectOption(
                label="First Season",
                value=MonitorOption.FIRST_SEASON.value,
                description="Only monitor the first season"
            ),
            discord.SelectOption(
                label="Latest Season",
                value=MonitorOption.LAST_SEASON.value,
                description="Only monitor the latest season"
            ),
        ]

        super().__init__(
            placeholder="Which seasons?",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle season selection."""
        monitor_option = MonitorOption(self.values[0])

        # Show confirmation view
        view = ConfirmShowView(
            self.bot,
            interaction,
            self.show,
            monitor_option
        )

        year = self.show.year or 'N/A'
        msg = (
            f"Confirm you want to request **{self.show.title}** ({year}) - "
            f"`{monitor_option.display_name}`"
        )

        await interaction.response.edit_message(content=msg, view=view)


class SeasonSelectorView(View):
    """View containing season selector dropdown."""

    def __init__(self, bot: "GrabarrBot", show: Show):
        super().__init__(timeout=120)
        self.add_item(SeasonSelector(bot, show))


class ShowSelector(Select):
    """Dropdown selector for show search results."""

    def __init__(self, bot: "GrabarrBot", shows: list[Show]):
        self.bot = bot
        self.shows = shows

        options = [
            discord.SelectOption(
                label=f"{s.title} ({s.year or 'N/A'})"[:100],
                value=str(i),
                description=s.overview[:100] if s.overview else None
            )
            for i, s in enumerate(shows)
        ]

        super().__init__(
            placeholder="Choose a show",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle show selection."""
        index = int(self.values[0])
        show = self.shows[index]

        # Show season selector
        year = show.year or 'N/A'
        msg = f"Which seasons would you like to request for **{show.title}** ({year})?"

        await interaction.response.edit_message(
            content=msg,
            view=SeasonSelectorView(self.bot, show)
        )


class ShowSelectorView(View):
    """View containing show selector dropdown."""

    def __init__(self, bot: "GrabarrBot", shows: list[Show]):
        super().__init__(timeout=180)
        self.add_item(ShowSelector(bot, shows))


class ShowsCog(commands.Cog):
    """Cog for TV show-related commands."""

    def __init__(self, bot: "GrabarrBot"):
        self.bot = bot

    @app_commands.command(
        name="request_show",
        description="Request a TV show via Sonarr"
    )
    @app_commands.describe(title="TV show title to search for")
    async def request_show(
        self,
        interaction: discord.Interaction,
        title: str
    ) -> None:
        """
        Search and request a TV show.

        Args:
            interaction: Discord interaction
            title: Show title to search
        """
        # Set correlation ID for request tracing
        correlation_id = str(uuid.uuid4())[:8]
        set_correlation_id(correlation_id)

        try:
            # Service availability check
            if not self.bot.sonarr_available:
                await interaction.response.send_message(
                    "Sonarr is currently unavailable. Please try again later.",
                    ephemeral=True
                )
                return

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
                "🔎 Searching for shows...",
                ephemeral=True
            )

            # Search shows
            shows = await self.bot.sonarr.search_shows(clean_title)

            if not shows:
                await searching_msg.edit(
                    content="No shows found with that title."
                )
                return

            # Show selector
            await searching_msg.edit(
                content="Select a show to request:",
                view=ShowSelectorView(self.bot, shows)
            )

        finally:
            clear_correlation_id()


async def setup(bot: "GrabarrBot") -> None:
    """Setup function for loading cog."""
    await bot.add_cog(ShowsCog(bot))
