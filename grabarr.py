import sys
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View, Button
import requests
import yaml
import logging
import asyncio

# Configuration loading
def get_config(file):
    with open(file, 'r') as yaml_file:
        config = yaml.safe_load(yaml_file)
    return config

# Initialize bot and logging
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

config_location = "/config/config.yml"
config = get_config(config_location)
bot_token = config['bot']['token']
radarr_api_key = config['radarr']['api_key']
radarr_base_url = config['radarr']['url'].rstrip('/')
sonarr_api_key = config['sonarr']['api_key']
sonarr_base_url = config['sonarr']['url'].rstrip('/')

request_movie_command_name = config['bot'].get('request_movie', 'regrab_movie')
request_series_command_name = config['bot'].get('request_series', 'regrab_series')

# Requests Session
session = requests.Session()

def get_root_folders(base_url, api_key):
    url = f"{base_url}/rootfolder?apikey={api_key}"
    try:
        response = session.get(url)
        print(response)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get root folders: {e}")
        return []

def select_root_folder(root_folders):
    if root_folders:
        return root_folders[0]['path']
    else:
        raise Exception("No root folders available")

try:
    sonarr_root_folders = get_root_folders(sonarr_base_url, sonarr_api_key)
    radarr_root_folders = get_root_folders(radarr_base_url, radarr_api_key)
    
    sonarr_root_folder_path = select_root_folder(sonarr_root_folders)
    radarr_root_folder_path = select_root_folder(radarr_root_folders)
    
    logging.info(f"Selected Sonarr Root Folder Path: {sonarr_root_folder_path}")
    logging.info(f"Selected Radarr Root Folder Path: {radarr_root_folder_path}")

except Exception as e:
    logging.error(f"Error: {e}")
    sys.exit(1)

def perform_request(method, url, data=None, headers=None):
    try:
        if method == 'GET':
            response = session.get(url, headers=headers)
        elif method == 'POST':
            response = session.post(url, json=data, headers=headers)
        elif method == 'DELETE':
            response = session.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        logging.error(f"Error performing {method} request: {e}")
        return None

class ConfirmButtonsMovie(View):
    def __init__(self, interaction, media_info):
        super().__init__()
        self.interaction = interaction
        self.media_info = media_info

        grab_button = Button(style=discord.ButtonStyle.primary, label="Request")
        grab_button.callback = self.grab_callback
        self.add_item(grab_button)

        cancel_button = Button(style=discord.ButtonStyle.danger, label="Cancel")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def grab_callback(self, button):
        movie_title = self.media_info['title']
        movie_year = self.media_info['year']
        movie_tmdb = self.media_info['tmdbId']
        await self.interaction.delete_original_response()

        if self.media_info['folderName']:
            await self.interaction.followup.send(content=f"`{self.interaction.user.name}` {movie_title} ({movie_year}) was not processed because this movie has already been requested.")
            logging.warning(f"{self.interaction.user.name} your request to request {movie_title} ({movie_year}) was not processed because this movie has already been requested.")
        else:
            add_url = f"{radarr_base_url}/movie?apikey={radarr_api_key}"
            data = {
                "tmdbId": movie_tmdb,
                "monitored": True,
                "qualityProfileId": 1,
                "minimumAvailability": "released",
                "addOptions": {
                    "searchForMovie": True
                },
                "rootFolderPath": radarr_root_folder_path,
                "title": movie_title
            }
            headers = {"Content-Type": "application/json"}
            add_response = perform_request('POST', add_url, data, headers)
            logging.info(f"Added {movie_title} with a response of {add_response}")

            if add_response and 200 <= add_response.status_code < 400:
                await self.interaction.followup.send(content=f"`{self.interaction.user.name}` your request for {movie_title} ({movie_year}) is being processed.")
                logging.info(f"{self.interaction.user.name} your request for {movie_title} ({movie_year}) is being processed.")
            else:
                await self.interaction.followup.send(content=f"`{self.interaction.user.name}` your request of {movie_title} ({movie_year}) had an issue, please contact the admin")
                logging.error(f"{self.interaction.user.name} your request of {movie_title} ({movie_year}) had an issue, please contact the admin")

    async def cancel_callback(self, button):
        await self.interaction.delete_original_response()
        await self.interaction.followup.send(content="Cancelled the request.", ephemeral=True)

class ConfirmButtonsSeries(View):
    def __init__(self, interaction, media_info):
        super().__init__()
        self.interaction = interaction
        self.media_info = media_info

        grab_button = Button(style=discord.ButtonStyle.primary, label="Request")
        grab_button.callback = self.grab_callback
        self.add_item(grab_button)

        cancel_button = Button(style=discord.ButtonStyle.danger, label="Cancel")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def grab_callback(self, button):
        tv_series_title = self.media_info["series"]
        tv_series_year = self.media_info["year"]
        series_existed = False

        if 'path' in self.media_info and 'id' in self.media_info:
            series_id = self.media_info['id']
            del_url = f"{sonarr_base_url}/series/{series_id}?deleteFiles=false&addImportListExclusion=false&apikey={sonarr_api_key}"
            del_response = perform_request('DELETE', del_url)
            if del_response and 200 <= del_response.status_code < 400:
                series_existed = True
                logging.warning(f"{self.interaction.user.name} {tv_series_title} ({tv_series_year}) had existed, resetting and searching for media again.")
            else:
                await self.interaction.followup.send(content=f"`{self.interaction.user.name}` the preparation to request {tv_series_title} ({tv_series_year}) had an issue, please contact the admin")
                logging.error(f"{self.interaction.user.name} the preparation to request {tv_series_title} ({tv_series_year}) had an issue, please contact the admin")

        add_url = f"{sonarr_base_url}/series"
        data = {
            "tvdbId": self.media_info["tvdbId"],
            "title": self.media_info["series"],
            "qualityProfileId": 1,
            "titleSlug": self.media_info['titleSlug'],
            "rootFolderPath": sonarr_root_folder_path,
            "languageProfileId": 1,
            "monitored": True,
            "addOptions": {
                "monitor": self.media_info['selectedSeasons'],
                "searchForMissingEpisodes": True,
                "searchForCutoffUnmetEpisodes": False
            }
        }
        headers = {"X-Api-Key": sonarr_api_key}
        add_response = perform_request('POST', add_url, data, headers)
        await self.interaction.delete_original_response()
        if add_response and 200 <= add_response.status_code < 400:
            if series_existed:
                await self.interaction.followup.send(content=f"`{self.interaction.user.name}` {tv_series_title} ({tv_series_year}) had existed, resetting and searching for media again.")
                logging.info(f"{self.interaction.user.name} {tv_series_title} ({tv_series_year}) had existed, resetting and searching for media again.")
            else:
                await self.interaction.followup.send(content=f"`{self.interaction.user.name}` {tv_series_title} ({tv_series_year}) is being processed.")
                logging.info(f"{self.interaction.user.name} your request of {tv_series_title} ({tv_series_year}) is being processed")
        else:
            await self.interaction.followup.send(content=f"`{self.interaction.user.name}` your request of {tv_series_title} ({tv_series_year}) had an issue, please contact the admin")
            logging.error(f"{self.interaction.user.name} your request of {tv_series_title} ({tv_series_year}) had an issue, please contact the admin")
        logging.info(f"Added {tv_series_title} with a response of {add_response}")

    async def cancel_callback(self, button):
        await self.interaction.delete_original_response()
        await self.interaction.followup.send(content="Cancelled the request.", ephemeral=True)

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
        await interaction.response.edit_message(content=confirmation_message, view=confirmation_view)

async def fetch_movie(movie_name):
    url = f"{radarr_base_url}/movie/lookup?term={movie_name}"
    headers = {"X-Api-Key": radarr_api_key}
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
        if response.status_code == 200:
            movie_list = response.json()
            return movie_list[:10]
        else:
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching movie data: {e}")
        return []

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
        self.media_info['titleSlug'] = selected_series_data['titleSlug']
        self.media_info['tvdbId'] = selected_series_data['tvdbId']
        self.media_info['year'] = selected_series_data['year']
        if 'path' in selected_series_data:
            self.media_info['path'] = selected_series_data['path']
        if 'id' in selected_series_data:
            self.media_info['id'] = selected_series_data['id']
        await interaction.response.edit_message(content="Please select season(s) you wish to request", view=BaseSeasonSelectorView(self.media_info))

async def fetch_series(series_name):
    url = f"{sonarr_base_url}/series/lookup?term={series_name}"
    headers = {"X-Api-Key": sonarr_api_key}
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
        if response.status_code == 200:
            series_list = response.json()
            return series_list[:10]
        else:
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching series data: {e}")
        return []

async def fetch_seasons(selected_series_data):
    seasons = selected_series_data.get('seasons', [])
    seasons = [season for season in seasons if season['seasonNumber'] != 0]
    return seasons

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
            discord.SelectOption(label="First Season"),
            discord.SelectOption(label="All Seasons")
        ]
        super().__init__(placeholder="What season(s) to request", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        selected_season_index = self.values[0]
        if selected_season_index == "Latest Season":
            self.media_info['selectedSeasons'] = "lastSeason"
        elif selected_season_index == "First Season":
            self.media_info['selectedSeasons'] = "firstSeason"
        else:
            self.media_info['selectedSeasons'] = "all"
        confirmation_message = (
            f"Please confirm that you would like to request the following:\n"
            f"**Series:** {self.media_info['series']}\n"
            f"**Season:** {selected_season_index}\n"
        )
        confirmation_view = ConfirmButtonsSeries(interaction, self.media_info)
        await interaction.response.edit_message(content=confirmation_message, view=confirmation_view)

media_info = {}

@bot.event
async def on_ready():
    logging.info('Bot is Up and Ready!')
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logging.error(f"{e}")

@bot.tree.command(name=request_movie_command_name, description="Will search and download selected Movie")
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

@bot.tree.command(name=request_series_command_name, description="Will search and download selected TV Series")
@app_commands.describe(series="What TV series should we grab?")
async def request_series(ctx, *, series: str):
    series_results = await fetch_series(series)
    if not series_results:
        await ctx.response.send_message(f"No TV series matching the title: {series}")
        return
    media_info['what'] = 'series'
    media_info['delete'] = 'no'
    await ctx.response.send_message("Select a TV series to grab", view=SeriesSelectorView(series_results, media_info), ephemeral=True)

bot.run(bot_token)
