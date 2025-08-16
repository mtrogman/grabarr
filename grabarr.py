import sys
import time
import logging
import requests
import yaml
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View, Button

# ------------- Logging -------------
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ------------- Config I/O -------------
def get_config(file):
    with open(file, "r") as yaml_file:
        return yaml.safe_load(yaml_file)

def save_config(file, config):
    with open(file, "w") as yaml_file:
        yaml.safe_dump(config, yaml_file, sort_keys=False)  # keep human layout

def ensure_section(cfg, name):
    if name not in cfg or cfg[name] is None:
        cfg[name] = {}

def normalize_base_url(u: str) -> str:
    return (u or "").rstrip("/")

# ------------- Constants -------------
REQUEST_TIMEOUT = 15  # avoid indefinite hangs

# ------------- Load config (startup behavior unchanged) -------------
config_location = "/config/config.yml"
config = get_config(config_location)

ensure_section(config, "bot")
ensure_section(config, "radarr")
ensure_section(config, "sonarr")

bot_token = config["bot"]["token"]

radarr_api_key = config["radarr"]["api_key"]
radarr_base_url = normalize_base_url(config["radarr"]["url"])
sonarr_api_key = config["sonarr"]["api_key"]
sonarr_base_url = normalize_base_url(config["sonarr"]["url"])

request_movie_command_name = config["bot"].get("request_movie", "request_movie")
request_show_command_name = config["bot"].get("request_show", "request_show")

# ------------- HTTP session -------------
session = requests.Session()

def perform_request(method, url, data=None, headers=None, params=None):
    try:
        if method == "GET":
            response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        elif method == "POST":
            response = session.post(url, json=data, headers=headers, timeout=REQUEST_TIMEOUT)
        elif method == "DELETE":
            response = session.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        response.raise_for_status()
        return response
    except Exception as e:
        logging.error(f"{method} {url} failed: {e}")
        return None

# ------------- Discovery (unchanged behavior) -------------
def get_root_folders(base_url, api_key):
    url = f"{base_url}/rootfolder?apikey={api_key}"
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Failed to get root folders from {base_url}: {e}")
        return []

def select_root_folder(folders):
    if folders:
        return folders[0]["path"]
    raise Exception("No root folders available")

def get_first_quality_profile(base_url, api_key):
    url = f"{base_url}/qualityprofile?apikey={api_key}"
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        profiles = response.json()
        if profiles:
            return profiles[0]["id"]
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

# Fill when missing (original startup methodology)
sonarr_quality_profile_id = ensure_config_value("sonarr", "qualityprofileid",
    lambda: get_first_quality_profile(sonarr_base_url, sonarr_api_key))
sonarr_root_folder_path = ensure_config_value("sonarr", "root_path",
    lambda: select_root_folder(get_root_folders(sonarr_base_url, sonarr_api_key)))

radarr_quality_profile_id = ensure_config_value("radarr", "qualityprofileid",
    lambda: get_first_quality_profile(radarr_base_url, radarr_api_key))
radarr_root_folder_path = ensure_config_value("radarr", "root_path",
    lambda: select_root_folder(get_root_folders(radarr_base_url, radarr_api_key)))

# ------------- Discord bot -------------
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

async def safe_delete_original(interaction: discord.Interaction):
    """Delete the original ephemeral UI message to keep the channel clean."""
    try:
        await interaction.delete_original_response()
    except Exception:
        pass

@bot.event
async def on_ready():
    logging.info("Bot is Up and Ready!")
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logging.error(f"Command sync failed: {e}")

# ------------- Radarr helpers (existence & search) -------------
def radarr_find_movie_by_tmdb(tmdb_id: int):
    """Return (movie_obj or None) via GET /movie?tmdbId=..."""
    try:
        resp = session.get(
            f"{radarr_base_url}/movie",
            params={"tmdbId": tmdb_id},
            headers={"X-Api-Key": radarr_api_key},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.ok:
            arr = resp.json()
            if isinstance(arr, list) and arr:
                return arr[0]
    except Exception as e:
        logging.error(f"radarr_find_movie_by_tmdb failed: {e}")
    return None

def radarr_add_movie_and_search(tmdb_id: int, title: str, year, title_slug: str, images):
    payload = {
        "tmdbId": tmdb_id,
        "title": title,
        "year": year,  # can be None; Radarr accepts null
        "qualityProfileId": radarr_quality_profile_id,
        "titleSlug": title_slug or "",
        "images": images or [],
        "monitored": True,
        "rootFolderPath": radarr_root_folder_path,
        "addOptions": {"searchForMovie": True},
    }
    return perform_request("POST", f"{radarr_base_url}/movie?apikey={radarr_api_key}",
                           data=payload, headers={"Content-Type": "application/json"})

def radarr_search_existing(movie_id: int):
    """Trigger a search for an existing movie ID."""
    payload = {"name": "MoviesSearch", "movieIds": [movie_id]}
    return perform_request("POST", f"{radarr_base_url}/command/",
                           data=payload, headers={"Content-Type": "application/json", "X-Api-Key": radarr_api_key})

# ------------- Sonarr helpers (existence/search) -------------
def sonarr_get_series_all():
    try:
        resp = session.get(f"{sonarr_base_url}/series?apikey={sonarr_api_key}", timeout=REQUEST_TIMEOUT)
        if resp.ok:
            return resp.json()
    except Exception as e:
        logging.error(f"sonarr_get_series_all failed: {e}")
    return []

def sonarr_find_series_by_tvdb(tvdb_id: int):
    all_series = sonarr_get_series_all()
    for s in all_series:
        if s.get("tvdbId") == tvdb_id:
            return s
    return None

def sonarr_add_series(title: str, tvdb_id: int, title_slug: str, images, monitor_flag: str):
    payload = {
        "title": title,
        "tvdbId": tvdb_id,
        "qualityProfileId": sonarr_quality_profile_id,
        "titleSlug": title_slug or "",
        "images": images or [],
        "monitored": True,
        "rootFolderPath": sonarr_root_folder_path,
        "addOptions": {"monitor": monitor_flag, "searchForMissingEpisodes": True},
    }
    return perform_request("POST", f"{sonarr_base_url}/series?apikey={sonarr_api_key}",
                           data=payload, headers={"Content-Type": "application/json"})

def sonarr_series_search(series_id: int):
    return perform_request("POST", f"{sonarr_base_url}/command/",
                           data={"name": "SeriesSearch", "seriesId": series_id},
                           headers={"Content-Type": "application/json", "X-Api-Key": sonarr_api_key})

# ------------- Movies UI -------------
async def fetch_movie(movie_name):
    url = f"{radarr_base_url}/movie/lookup?term={movie_name}"
    headers = {"X-Api-Key": radarr_api_key}
    try:
        response = perform_request("GET", url, headers=headers)
        if response and response.status_code == 200:
            movie_list = response.json()
            return movie_list[:10]
        return []
    except Exception as e:
        logging.error(f"Error fetching movie data: {e}")
        return []

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
        # delete ephemeral confirm
        await safe_delete_original(self.interaction)

        # public placeholder while we work
        status_msg = await interaction.channel.send("🔎 Working on your movie request…")

        tmdb_id = int(self.movie["tmdbId"])
        title = self.movie["title"]
        year = self.movie.get("year")  # None accepted
        title_slug = self.movie.get("titleSlug", "")
        images = self.movie.get("images", [])

        # 1) Check if it already exists in Radarr
        existing = radarr_find_movie_by_tmdb(tmdb_id)
        if existing:
            movie_id = int(existing["id"])
            has_file = bool(existing.get("hasFile")) or bool(existing.get("movieFile"))
            if has_file:
                # Already downloaded → nothing to do
                await status_msg.edit(content=f"💤 **{interaction.user.display_name}** — **{title} ({year or 'N/A'})** already exists and is downloaded.")
                return
            # Exists but no file → trigger search
            resp = radarr_search_existing(movie_id)
            if resp and resp.status_code < 400:
                await status_msg.edit(content=f"🔎 **{interaction.user.display_name}** — searching for **{title} ({year or 'N/A'})**.")
            else:
                await status_msg.edit(content=f"❌ **{interaction.user.display_name}** — couldn’t start a search for **{title} ({year or 'N/A'})**. Try again later.")
            return

        # 2) Not in Radarr → Add and search
        add_resp = radarr_add_movie_and_search(tmdb_id, title, year, title_slug, images)
        if add_resp and add_resp.status_code < 400:
            await status_msg.edit(content=f"🔎 **{interaction.user.display_name}** — requested **{title} ({year or 'N/A'})** and started search.")
        else:
            await status_msg.edit(content=f"❌ **{interaction.user.display_name}** — request for **{title} ({year or 'N/A'})** failed. Try again later.")

    async def cancel_callback(self, interaction):
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
        overview = movie.get("overview", "No description available.")
        msg = f"**{movie['title']} ({movie.get('year', 'N/A')})**\n{overview}\n\nConfirm your request."
        await interaction.response.edit_message(content=msg, view=view)

class MovieSelectorView(View):
    def __init__(self, movies):
        super().__init__(timeout=180)
        self.add_item(MovieSelector(movies))

# ------------- Shows UI -------------
async def fetch_show(show_name):
    url = f"{sonarr_base_url}/series/lookup?term={show_name}"
    headers = {"X-Api-Key": sonarr_api_key}
    try:
        response = perform_request("GET", url, headers=headers)
        if response and response.status_code == 200:
            show_list = response.json()
            return show_list[:10]
        return []
    except Exception as e:
        logging.error(f"Error fetching show data: {e}")
        return []

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
        # delete ephemeral confirm
        await safe_delete_original(self.interaction)

        # public placeholder while we work
        status_msg = await interaction.channel.send("🔎 Working on your series request…")

        title = self.show["title"]
        tvdb_id = int(self.show["tvdbId"])
        year = self.show.get("year", "N/A")
        title_slug = self.show.get("titleSlug", "")
        images = self.show.get("images", [])

        # If show exists: retrigger a search for all monitored episodes
        existing = sonarr_find_series_by_tvdb(tvdb_id)
        if existing and existing.get("id"):
            series_id = int(existing["id"])
            resp = sonarr_series_search(series_id)
            if resp and resp.status_code < 400:
                await status_msg.edit(content=f"🔎 **{interaction.user.display_name}** — **{title}** exists already; retriggering a search for all monitored episodes.")
            else:
                await status_msg.edit(content=f"❌ **{interaction.user.display_name}** — search for **{title}** failed. Try again later.")
            return

        # Not found — add and search for missing episodes
        add_resp = sonarr_add_series(title, tvdb_id, title_slug, images, self.monitor_flag)
        if add_resp and add_resp.status_code < 400:
            await status_msg.edit(content=f"🔎 **{interaction.user.display_name}** — added **{title} ({year})** and searching for missing episodes.")
        else:
            await status_msg.edit(content=f"❌ **{interaction.user.display_name}** — request for **{title} ({year})** failed. Try again later.")

    async def cancel_callback(self, interaction):
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
        label = "All Seasons" if selection == "all" else ("First Season" if selection == "firstSeason" else "Latest Season")
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

# ------------- Slash Commands (add a “🔎 Searching…” ephemeral window) -------------
@bot.tree.command(name=request_movie_command_name, description="Request a movie via Radarr")
@app_commands.describe(title="Movie title")
async def request_movie(ctx, *, title: str):
    await ctx.response.defer(ephemeral=True)
    # show a searching window
    searching = await ctx.followup.send("🔎 Searching for movies…", ephemeral=True)
    movie_results = await fetch_movie(title)
    if not movie_results:
        await searching.edit(content="No movie found with that title.")
        return
    await searching.edit(content="Select a movie to request:", view=MovieSelectorView(movie_results))

@bot.tree.command(name=request_show_command_name, description="Request a TV show via Sonarr")
@app_commands.describe(title="TV show title")
async def request_show(ctx, *, title: str):
    await ctx.response.defer(ephemeral=True)
    # show a searching window
    searching = await ctx.followup.send("🔎 Searching for shows…", ephemeral=True)
    show_results = await fetch_show(title)
    if not show_results:
        await searching.edit(content="No show found with that title.")
        return
    await searching.edit(content="Select a show to request:", view=ShowSelectorView(show_results))

if __name__ == "__main__":
    bot.run(bot_token)
