import sys
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View, Button
import requests
import yaml
import logging

# ---- CONFIG ----
def get_config(file):
    with open(file, 'r') as yaml_file:
        return yaml.safe_load(yaml_file)

def save_config(file, config):
    with open(file, 'w') as yaml_file:
        yaml.safe_dump(config, yaml_file)

config_location = "/config/config.yml"
config = get_config(config_location)
bot_token = config['bot']['token']
radarr_api_key = config['radarr']['api_key']
radarr_base_url = config['radarr']['url'].rstrip('/')
sonarr_api_key = config['sonarr']['api_key']
sonarr_base_url = config['sonarr']['url'].rstrip('/')

request_movie_command_name = config['bot'].get('request_movie', 'request_movie')
request_show_command_name = config['bot'].get('request_show', 'request_show')

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
session = requests.Session()

def get_root_folders(base_url, api_key):
    url = f"{base_url}/rootfolder?apikey={api_key}"
    try:
        response = session.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Failed to get root folders from {base_url}: {e}")
        return []

def select_root_folder(folders):
    if folders:
        return folders[0]['path']
    raise Exception("No root folders available")

def get_first_quality_profile(base_url, api_key):
    url = f"{base_url}/qualityprofile?apikey={api_key}"
    try:
        response = session.get(url)
        response.raise_for_status()
        profiles = response.json()
        if profiles:
            return profiles[0]['id']
        else:
            raise Exception("No quality profiles available")
    except Exception as e:
        logging.error(f"Failed to get quality profiles from {base_url}: {e}")
        return None

def ensure_config_value(section, key, fetch_func):
    if key not in config[section] or not config[section][key]:
        value = fetch_func()
        if value:
            config[section][key] = value
            save_config(config_location, config)
            logging.info(f"Set {key} for {section}: {value}")
        else:
            logging.critical(f"Could not fetch {key} for {section}. Exiting.")
            sys.exit(1)
    return config[section][key]

sonarr_quality_profile_id = ensure_config_value('sonarr', 'qualityprofileid', lambda: get_first_quality_profile(sonarr_base_url, sonarr_api_key))
sonarr_root_folder_path  = ensure_config_value('sonarr', 'root_path', lambda: select_root_folder(get_root_folders(sonarr_base_url, sonarr_api_key)))
radarr_quality_profile_id = ensure_config_value('radarr', 'qualityprofileid', lambda: get_first_quality_profile(radarr_base_url, radarr_api_key))
radarr_root_folder_path  = ensure_config_value('radarr', 'root_path', lambda: select_root_folder(get_root_folders(radarr_base_url, radarr_api_key)))

def perform_request(method, url, data=None, headers=None, params=None):
    try:
        if method == 'GET':
            response = session.get(url, headers=headers, params=params)
        elif method == 'POST':
            response = session.post(url, json=data, headers=headers)
        elif method == 'DELETE':
            response = session.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        response.raise_for_status()
        return response
    except Exception as e:
        logging.error(f"{method} request failed: {e}")
        return None

# ---- MOVIE UI ----
class ConfirmButtonsMovie(View):
    def __init__(self, interaction, movie):
        super().__init__()
        self.interaction = interaction
        self.movie = movie
        request_button = Button(style=discord.ButtonStyle.success, label="Request")
        request_button.callback = self.request_callback
        self.add_item(request_button)

        cancel_button = Button(style=discord.ButtonStyle.danger, label="Cancel")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def request_callback(self, interaction):
        headers = {"Content-Type": "application/json"}
        data = {
            "tmdbId": self.movie["tmdbId"],
            "title": self.movie["title"],
            "qualityProfileId": radarr_quality_profile_id,
            "titleSlug": self.movie["titleSlug"],
            "images": self.movie.get("images", []),
            "monitored": True,
            "rootFolderPath": radarr_root_folder_path,
            "addOptions": {"searchForMovie": True},
        }
        try:
            await self.interaction.delete_original_response()
        except Exception:
            pass

        response = perform_request('POST', f"{radarr_base_url}/movie?apikey={radarr_api_key}", data, headers)
        if response and response.status_code < 400:
            msg = "Movie request submitted successfully!"
        else:
            msg = "Failed to submit request. Try again later."
        try:
            await self.interaction.followup.send(content=msg, ephemeral=True)
        except Exception:
            pass

    async def cancel_callback(self, interaction):
        try:
            await self.interaction.delete_original_response()
        except Exception:
            pass
        try:
            await self.interaction.followup.send(content="Cancelled the request.", ephemeral=True)
        except Exception:
            pass

class MovieSelector(Select):
    def __init__(self, movies):
        self.movies = movies
        options = [
            discord.SelectOption(label=f"{m['title']} ({m.get('year', 'N/A')})", value=str(i))
            for i, m in enumerate(movies)
        ]
        super().__init__(placeholder="Choose a movie", min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        index = int(self.values[0])
        movie = self.movies[index]
        view = ConfirmButtonsMovie(interaction, movie)
        overview = movie.get('overview', 'No description available.')
        msg = f"**{movie['title']} ({movie.get('year', 'N/A')})**\n{overview}\n\nConfirm your request."
        await interaction.response.edit_message(content=msg, view=view)

class MovieSelectorView(View):
    def __init__(self, movies):
        super().__init__(timeout=180)
        self.add_item(MovieSelector(movies))

async def fetch_movie(movie_name):
    url = f"{radarr_base_url}/movie/lookup?term={movie_name}"
    headers = {"X-Api-Key": radarr_api_key}
    try:
        response = perform_request('GET', url, headers=headers)
        if response and response.status_code == 200:
            movie_list = response.json()
            return movie_list[:10]
        else:
            return []
    except Exception as e:
        logging.error(f"Error fetching movie data: {e}")
        return []

# ---- SHOW UI (with season selector) ----
class ConfirmButtonsShow(View):
    def __init__(self, interaction, show, monitor_flag):
        super().__init__()
        self.interaction = interaction
        self.show = show
        self.monitor_flag = monitor_flag
        request_button = Button(style=discord.ButtonStyle.success, label="Request")
        request_button.callback = self.request_callback
        self.add_item(request_button)

        cancel_button = Button(style=discord.ButtonStyle.danger, label="Cancel")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def request_callback(self, interaction):
        headers = {"Content-Type": "application/json"}
        data = {
            "title": self.show["title"],
            "qualityProfileId": sonarr_quality_profile_id,
            "titleSlug": self.show["titleSlug"],
            "images": self.show.get("images", []),
            "monitored": True,
            "rootFolderPath": sonarr_root_folder_path,
            "addOptions": {
                "monitor": self.monitor_flag,
                "searchForMissingEpisodes": True
            },
            "tvdbId": self.show["tvdbId"],
        }
        try:
            await self.interaction.delete_original_response()
        except Exception:
            pass

        response = perform_request('POST', f"{sonarr_base_url}/series?apikey={sonarr_api_key}", data, headers)
        if response and response.status_code < 400:
            msg = "Show request submitted successfully!"
        else:
            msg = "Failed to submit request. Try again later."
        try:
            await self.interaction.followup.send(content=msg, ephemeral=True)
        except Exception:
            pass

    async def cancel_callback(self, interaction):
        try:
            await self.interaction.delete_original_response()
        except Exception:
            pass
        try:
            await self.interaction.followup.send(content="Cancelled the request.", ephemeral=True)
        except Exception:
            pass

class SeasonChoiceSelector(Select):
    def __init__(self, show):
        self.show = show
        options = [
            discord.SelectOption(label="All Seasons", value="all"),
            discord.SelectOption(label="First Season", value="firstSeason"),
            discord.SelectOption(label="Latest Season", value="lastSeason"),
        ]
        super().__init__(placeholder="Which seasons?", min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        selection = self.values[0]
        # Convert flag to label for UI message
        if selection == "all":
            label = "All Seasons"
        elif selection == "firstSeason":
            label = "First Season"
        else:
            label = "Latest Season"
        view = ConfirmButtonsShow(interaction, self.show, selection)
        msg = f"Confirm you want to request **{self.show['title']}** ({self.show.get('year','N/A')}) - `{label}`"
        await interaction.response.edit_message(content=msg, view=view)

class ShowSelector(Select):
    def __init__(self, shows):
        self.shows = shows
        options = [
            discord.SelectOption(label=f"{s['title']} ({s.get('year', 'N/A')})", value=str(i))
            for i, s in enumerate(shows)
        ]
        super().__init__(placeholder="Choose a show", min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        index = int(self.values[0])
        show = self.shows[index]
        msg = f"Which seasons would you like to request for **{show['title']}** ({show.get('year','N/A')})?"
        await interaction.response.edit_message(content=msg, view=SeasonChoiceView(show))

class SeasonChoiceView(View):
    def __init__(self, show):
        super().__init__(timeout=120)
        self.add_item(SeasonChoiceSelector(show))

class ShowSelectorView(View):
    def __init__(self, shows):
        super().__init__(timeout=180)
        self.add_item(ShowSelector(shows))

async def fetch_show(show_name):
    url = f"{sonarr_base_url}/series/lookup?term={show_name}"
    headers = {"X-Api-Key": sonarr_api_key}
    try:
        response = perform_request('GET', url, headers=headers)
        if response and response.status_code == 200:
            show_list = response.json()
            return show_list[:10]
        else:
            return []
    except Exception as e:
        logging.error(f"Error fetching show data: {e}")
        return []

# ---- Discord Events ----
@bot.event
async def on_ready():
    logging.info('Bot is Up and Ready!')
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logging.error(f"{e}")

@bot.tree.command(name=request_movie_command_name, description="Request a movie via Radarr")
@app_commands.describe(title="Movie title")
async def request_movie(ctx, *, title: str):
    await ctx.response.defer(ephemeral=True)
    movie_results = await fetch_movie(title)
    if not movie_results:
        await ctx.followup.send("No movie found with that title.", ephemeral=True)
        return
    await ctx.followup.send("Select a movie to request:", view=MovieSelectorView(movie_results), ephemeral=True)

@bot.tree.command(name=request_show_command_name, description="Request a TV show via Sonarr")
@app_commands.describe(title="TV show title")
async def request_show(ctx, *, title: str):
    await ctx.response.defer(ephemeral=True)
    show_results = await fetch_show(title)
    if not show_results:
        await ctx.followup.send("No show found with that title.", ephemeral=True)
        return
    await ctx.followup.send("Select a show to request:", view=ShowSelectorView(show_results), ephemeral=True)

if __name__ == "__main__":
    bot.run(bot_token)
