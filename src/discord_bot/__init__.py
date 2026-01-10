"""Discord bot module with commands and UI components."""

from .bot import GrabarrBot
from .cogs.movies import MoviesCog
from .cogs.shows import ShowsCog

__all__ = ["GrabarrBot", "MoviesCog", "ShowsCog"]
