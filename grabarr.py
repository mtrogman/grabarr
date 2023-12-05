import sys
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View, Button
from datetime import datetime
import requests
import json
import yaml
import logging

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def getConfig(file):
    with open(file, 'r') as yaml_file:
        config = yaml.safe_load(yaml_file)
    return config


config_location = "/config/config.yml"
config = getConfig(config_location)
bot_token = config['bot']['token']
radarr_api_key = config['radarr']['api_key']
radarr_base_url = config['radarr']['url']
sonarr_api_key = config['sonarr']['api_key']
sonarr_base_url = config['sonarr']['url']


# Replace async with synchronous requests
def perform_request(method, url, data=None, headers=None):
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers)
        elif method == 'POST':
            response = requests.post(url, json=data, headers=headers)
        elif method == 'DELETE':
            response = requests.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        return response

    except requests.exceptions.RequestException as e:
        logging.error(f"Error performing {method} request: {e}")
        return None


class ConfirmButtonsMovie(View):
    def __init__(self, interaction, media_info):
        super().__init__()
        grab_button = Button(style=discord.ButtonStyle.primary, label="Request")
        grab_button.callback = self.grab_callback
        self.add_item(grab_button)

        cancel_button = Button(style=discord.ButtonStyle.danger, label="Cancel")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

        self.interaction = interaction
        self.media_info = media_info

    async def grab_callback(self, button):
        # Use self.media_info to access movie details
        movie_title = self.media_info['title']
        movie_year = self.media_info['year']
        movie_tmdb = self.media_info['tmdbId']

        if self.media_info['folderName']:
            await self.interaction.followup.send(content=f"`{self.interaction.user.name} your request to request {movie_title}` ({movie_year}) was not processed because this movie has already been requested.")
        else:
            # Add the movie back (and search for it)
            add_url = f"{radarr_base_url}/movie?apikey={radarr_api_key}"
            data = {
                "tmdbId": movie_tmdb,
                "monitored": True,
                "qualityProfileId": 1,
                "minimumAvailability": "released",
                "addOptions": {
                    "searchForMovie": True
                },
                "rootFolderPath": "/movies",
                "title": movie_title
            }
            headers = {
                "Content-Type": "application/json"
            }
            add_response = perform_request('POST', add_url, data, headers)
            logging.info(f"Added {movie_title} with a response of {add_response}")

            # Respond to discord
            await self.interaction.followup.send(content=f"`{self.interaction.user.name} your request to delete and redownload {movie_title}` ({movie_year}) is being processed.")

    # Cancel just responds with msg
    async def cancel_callback(self, button):
        await self.interaction.delete_original_response()
        await self.interaction.followup.send(content="Cancelled the request.", ephemeral=True)


class ConfirmButtonsSeries(View):
    def __init__(self, interaction, media_info):
        super().__init__()
        regrab_button = Button(style=discord.ButtonStyle.primary, label="Request")
        regrab_button.callback = self.regrab_callback
        self.add_item(regrab_button)

        cancel_button = Button(style=discord.ButtonStyle.danger, label="Cancel")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

        self.interaction = interaction
        self.media_info = media_info

    async def grab_callback(self, button):
        # Checks if episodeFileId is 0 and if it is doesn't delete it since it's not there.
        if media_info['episodeFileId'] != 0:
            # Delete the show
            delete_url = f"{sonarr_base_url}/episodefile/{media_info['episodeFileId']}?apikey={sonarr_api_key}"
            try:
                delete_response = requests.delete(delete_url)
                delete_response.raise_for_status()  # Raise an exception for non-200 responses
                logging.info(f"Deleted EpisodeFileID {media_info['episodeFileId']} with a response of {delete_response.status_code}")
            except requests.exceptions.RequestException as e:
                logging.error(f"Error deleting EpisodeFileID {media_info['episodeFileId']}: {e}")
        else:
            logging.info(f"No Episode Found")

        # Search for the episode
        search_url = f"{sonarr_base_url}/command/"
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": sonarr_api_key
        }
        data = {
            "episodeIds": [media_info['episodeId']],
            "name": "EpisodeSearch",
        }

        try:
            search_response = requests.post(search_url, headers=headers, json=data)
            search_response.raise_for_status()  # Raise an exception for non-200 responses
            logging.info(f"Searching for EpisodeID {media_info['episodeNumber']} with a response of {search_response.status_code}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error searching for EpisodeID {media_info['episodeId']}: {e}")

        await self.interaction.delete_original_response()
        await self.interaction.followup.send(content=f"`{self.interaction.user.name} your request to (re)grab {media_info['series']}` Season {media_info['seasonNumber']}) Episode {media_info['episodeNumber']} is being processed.")

    # Cancel just responds with msg
    async def cancel_callback(self, button):
        await self.interaction.delete_original_response()
        await self.interaction.followup.send(content="Cancelled the request.", ephemeral=True)

# View & Select required to build out Discord Dropdown.
class MovieSelectorView(View):
    def __init__(self, search_results, media_info):
        super().__init__()
        self.search_results = search_results
        self.add_item(MovieSelector(search_results, media_info))


class MovieSelector(Select):
    def __init__(self, search_results, media_info):
        self.search_results = search_results
        self.media_info = media_info
        options = [
            discord.SelectOption(
                label=movie['title'],
                value=str(idx),
                description=str(movie['year'])
            )
            for idx, movie in enumerate(search_results)
        ]
        super().__init__(placeholder="Please select a movie", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        selected_movie_index = int(self.values[0])
        selected_movie_data = self.search_results[selected_movie_index]
        self.media_info['movieId'] = selected_movie_data.get('id', 'N/A')
        self.media_info['title'] = selected_movie_data['title']
        self.media_info['year'] = selected_movie_data['year']
        self.media_info['overview'] = selected_movie_data['overview']
        self.media_info['folderName'] = selected_movie_data['folderName']
        confirmation_message = (
            f"Please confirm that you would like to grab the following movie:\n"
            f"**Title:** {self.media_info['title']}\n"
            f"**Year:** {self.media_info['year']}\n"
            f"**Overview:** {self.media_info['overview']}\n"
        )

        confirmation_view = ConfirmButtonsMovie(interaction, selected_movie_data)

        await interaction.response.edit_message(
            content=confirmation_message,
            view=confirmation_view
        )


# Call to get list of top 10 Movies found that match the search and to put into Discord Dropdown
async def fetch_movie(movie_name):
    url = f"{radarr_base_url}/movie/lookup?term={movie_name}"
    headers = {"X-Api-Key": radarr_api_key}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception for non-200 responses

        if response.status_code == 200:
            movie_list = response.json()
            return movie_list[:10]  # Return the first 10 movies
        else:
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching movie data: {e}")
        return []


# View & Select required to build out TV Series Discord Dropdown.
class SeriesSelectorView(View):
    def __init__(self, series_results, media_info):
        super().__init__()
        self.series_results = series_results
        self.media_info = media_info
        self.add_item(TVSeriesSelector(series_results, media_info))


class TVSeriesSelector(Select):
    def __init__(self, series_results, media_info):
        self.series_results = series_results
        self.media_info = media_info
        options = [
            discord.SelectOption(
                label=series['title'],
                value=str(idx),
                description=str(series['year'])
            )
            for idx, series in enumerate(series_results)
        ]
        super().__init__(placeholder="Please select a TV series", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        selected_series_index = int(self.values[0])
        selected_series_data = self.series_results[selected_series_index]
        self.media_info['seasonList'] = await fetch_seasons(selected_series_data)
        self.media_info['series'] = selected_series_data['title']

        # Add media_info parameter to callback method
        await interaction.response.edit_message(content="Please select season(s) you wish to request",  view=BaseSeasonSelectorView(self.media_info))


# Call to get list of top 10 TV Series found that match the search and to put into Discord Dropdown
async def fetch_series(series_name):
    url = f"{sonarr_base_url}/series/lookup?term={series_name}"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception for non-200 responses

        if response.status_code == 200:
            series_list = response.json()
            return series_list[:10]  # Return the first 10 series
        else:
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching series data: {e}")
        return []


# Call to get list of seasons within the series and put into Discord Dropdown
async def fetch_seasons(selected_series_data, ):
    seasons = selected_series_data.get('seasons', [])
    # Filter out season 0 which is extras
    seasons = [season for season in seasons if season['seasonNumber'] != 0]
    return seasons


# View & Select required to build out TV Season Discord Dropdown.
class BaseSeasonSelectorView(View):
    def __init__(self, media_info):
        super().__init__()
        self.media_info = media_info
        self.add_item(BaseSeasonSelector(media_info))


class BaseSeasonSelector(Select):
    def __init__(self, media_info):
        self.media_info = media_info
        options = [
            discord.SelectOption(label="Latest Season"),
            discord.SelectOption(label="All Seasons"),
            discord.SelectOption(label="Choose which seasons")
        ]
        super().__init__(placeholder="What season(s) to request", options=options, min_values=1, max_values=1)
    async def callback(self, interaction: discord.Interaction):
        selected_season_index = self.values[0]
        if selected_season_index == "Latest Season":
            media_info['seasonChoice'] = "latestSeason"
        elif selected_season_index == "All Seasons":
            media_info['seasonChoice'] = "allSeasons"
        else:
            await interaction.response.edit_message(content="Please select a season", view=SeasonSelectorView(media_info))


class SeasonSelectorView(View):
    def __init__(self, media_info):
        super().__init__()
        self.add_item(SeasonSelector(media_info))


class SeasonSelector(Select):
    def __init__(self, media_info):
        options = [
            discord.SelectOption(
                label=f"Season {int(season['seasonNumber'])}",
                value=str(season['seasonNumber'])
            )
            for season in media_info['seasonList']
        ]
        super().__init__(placeholder="Please select season(s) you want to request", options=options, min_values=1, max_values=10)

    # async def callback(self, interaction: discord.Interaction):
    #     selected_season_index = int(self.values[0])
    #     self.media_info['seasonNumber'] = self.seasons_results[selected_season_index]['seasonNumber']
    #     episode_results = await fetch_episodes(media_info)
    #     await interaction.response.edit_message(content="Please select an episode", view=EpisodeSelectorView(episode_results, self.media_info))

media_info = {}


# Sync commands with discord
@bot.event
async def on_ready():
    logging.info('Bot is Up and Ready!')
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logging.error(f"{e}")


# Bot command to "grab" (search) for movie
@bot.tree.command(name="request_movie", description="Will search and download selected Movie")
@app_commands.describe(movie="What movie should we grab?")
async def request_movie(ctx, *, movie: str):
    movie_results = await fetch_movie(movie)
    if not movie_results:
        await ctx.response.send_message(
            f"{ctx.user.name} no movie matching the following title was found: {movie}")
        return
    media_info['what'] = 'movie'
    media_info['delete'] = 'no'
    await ctx.response.send_message("Select a movie to grab", view=MovieSelectorView(movie_results, media_info), ephemeral=True)


# Bot command to "grab" (search) for TV Show
@bot.tree.command(name="request_series", description="Will search and download selected TV Series")
@app_commands.describe(series="What TV series should we grab?")
async def request_series(ctx, *, series: str):
    # Fetch TV series matching the input series name
    series_results = await fetch_series(series)
    if not series_results:
        await ctx.response.send_message(f"No TV series matching the title: {series}")
        return
    media_info['what'] = 'series'
    media_info['delete'] = 'no'
    await ctx.response.send_message("Select a TV series to grab", view=SeriesSelectorView(series_results, media_info), ephemeral=True)


bot.run(bot_token)