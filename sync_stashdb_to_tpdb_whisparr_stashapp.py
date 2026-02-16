# %% [markdown]
# # Sync StashDB and ThePornDB with Whisparr and StashApp
#
# The source of truth will be StashDB, and from that, we'll update ThePornDB, Whisparr, and StashApp.
#

# %%
# # documentation: https://docs.totaldebug.uk/pyarr/modules/sonarr.html
import datetime
import json
import os
import subprocess
import sys

# Install required packages
packages = [
    "joblib",
    "requests",
    "loguru",
    "wrapt",
    "backoff",
    "git+https://github.com/harderest/stashapp-tools.git",
    "pyarr",
    "python-dotenv",
    "tqdm",
    "ipywidgets",
    "bs4"
]

try:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", *packages, "--quiet", "--quiet"]
    )
except subprocess.CalledProcessError as e:
    print(f"Failed to install packages: {e}")
    raise

import urllib.parse
from multiprocessing.pool import ThreadPool

import backoff
import requests
import stashapi.log as log
import wrapt
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from joblib import Memory
from loguru import logger
from pyarr import SonarrAPI
from stashapi.stashapp import StashInterface
from tqdm.auto import tqdm


# %%
# !git clone https://github.com/ThePornDatabase/stash_theporndb_scraper.git

# %%

# load from home directory
# assert load_dotenv(os.path.expanduser("~/.env"))
# load_dotenv("..")
assert load_dotenv()

WHISPARR_API_KEY = os.environ["WHISPARR_API_KEY"]
WHISPARR_BASE_URL = os.environ["WHISPARR_BASE_URL"]


STASH_API_KEY = os.environ["STASH_API_KEY"]
STASH_BASE_URL = os.environ["STASH_BASE_URL"]

THEPORNDB_API_KEY = os.environ["THEPORNDB_API_KEY"]
STASHDB_API_KEY = os.environ["STASHDB_API_KEY"]

stash_headers = {
    "ApiKey": STASH_API_KEY,
}
stashdb_headers = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    # 'Accept-Language': 'en-US,en;q=0.9',
    # 'Connection': 'keep-alive',
    "Content-Type": "application/json",
    # 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    "ApiKey": STASHDB_API_KEY,
}
whisparr_headers = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Origin": f"{WHISPARR_BASE_URL}",
    "Referer": f"{WHISPARR_BASE_URL}/settings/importlists",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-Api-Key": WHISPARR_API_KEY,
    "X-Requested-With": "XMLHttpRequest",
}
tpdb_headers = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Authorization": f"Bearer {THEPORNDB_API_KEY}",
}

# TTL logic - check if script should run based on last execution time
TTL_WEEKS = int(os.environ.get("SYNC_TTL_WEEKS", "1"))
TTL_FILE = "/tmp/.last_sync_run"


def should_run_sync():
    """Check if sync should run based on TTL"""
    if not os.path.exists(TTL_FILE):
        logger.info("No previous sync timestamp found. Running sync.")
        return True

    try:
        with open(TTL_FILE, "r") as f:
            last_run_str = f.read().strip()

        last_run = datetime.fromisoformat(last_run_str)
        current_time = datetime.now()
        time_diff = current_time - last_run

        if time_diff.total_seconds() > (TTL_WEEKS * 7 * 24 * 3600):
            logger.info(
                f"TTL exceeded ({TTL_WEEKS} weeks). Last run: {last_run}. Running sync."
            )
            return True
        else:
            remaining_hours = TTL_WEEKS - (time_diff.total_seconds() / (7 * 24 * 3600))
            logger.info(
                f"TTL not exceeded. Last run: {last_run}. Next run in {remaining_hours:.1f} hours."
            )
            return False

    except (ValueError, IOError) as e:
        logger.warning(f"Error reading TTL file: {e}. Running sync.")
        return True


def update_sync_timestamp():
    """Update the timestamp file with current time"""
    try:
        with open(TTL_FILE, "w") as f:
            f.write(datetime.now().isoformat())
        logger.info(f"Updated sync timestamp to {datetime.now()}")
    except IOError as e:
        logger.error(f"Failed to update sync timestamp: {e}")


# Check TTL before proceeding
if not should_run_sync():
    logger.info("Exiting due to TTL check.")
    exit(0)


# %%
# Monkey patch requests.get and requests.post with our cached versions
if "requests_get_original" not in globals():
    requests_get_original = requests.get
    requests_post_original = requests.post


@wrapt.decorator
def loggo(wrapped, instance, args, kwargs):
    logger.info(f"Calling {wrapped.__name__} with args={args} kwargs={kwargs}")
    result = wrapped(*args, **kwargs)
    logger.info(f"{wrapped.__name__} returned {result}")
    return result


memory = Memory("cache", verbose=0)


@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.RequestException, requests.exceptions.HTTPError),
    max_tries=5,
    jitter=None,
)
@loggo
@memory.cache(ignore=["headers"])
def requests_get(
    url: str, params: dict = None, headers: dict = None
) -> requests.Response:
    """Make a GET request with retries and error handling"""
    response = requests_get_original(url, params=params, headers=headers)
    response.raise_for_status()
    return response


@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.RequestException, requests.exceptions.HTTPError),
    max_tries=5,
    jitter=None,
)
@loggo
@memory.cache(ignore=["headers"])
def requests_post(
    url: str,
    data: dict = None,
    json: dict = None,
    headers: dict = None,
    params: dict = None,
) -> requests.Response:
    """Make a POST request with retries and error handling"""
    response = requests_post_original(
        url, data=data, json=json, headers=headers, params=params
    )
    response.raise_for_status()
    return response


# requests.get = requests_get
# requests.post = requests_post


# %%
## Get favorite studios from StashDB

stashdb_favorite_studios_payload = {
    "operationName": "Studios",
    "variables": {
        "input": {
            "names": "",
            "is_favorite": True,
            "page": 1,
            "per_page": 1000,
            "direction": "ASC",
            "sort": "NAME",
        }
    },
    "query": "query Studios($input: StudioQueryInput!) {\n  queryStudios(input: $input) {\n    count\n    studios {\n      id\n      name\n      deleted\n      parent {\n        id\n        name\n        __typename\n      }\n      urls {\n        ...URLFragment\n        __typename\n      }\n      images {\n        ...ImageFragment\n        __typename\n      }\n      is_favorite\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment URLFragment on URL {\n  url\n  site {\n    id\n    name\n    icon\n    __typename\n  }\n  __typename\n}\n\nfragment ImageFragment on Image {\n  id\n  url\n  width\n  height\n  __typename\n}",
}


data = requests.post(
    "https://stashdb.org/graphql",
    headers=stashdb_headers,
    json=stashdb_favorite_studios_payload,
).json()
print("data", data)
stashdb_favorite_studios = [x for x in data["data"]["queryStudios"]["studios"]]
print([x["name"] for x in stashdb_favorite_studios])

print("stashdb favorite studios", len(stashdb_favorite_studios))


# %%

## Get favorite performers from StashDB
stashdb_favorite_performers_payload = {
    "operationName": "Performers",
    "variables": {
        "input": {
            "names": "",
            "is_favorite": True,
            "page": 1,
            "per_page": 5000,
            "sort": "NAME",
            "direction": "ASC",
        },
    },
    "query": "query Performers($input: PerformerQueryInput!) {\n  queryPerformers(input: $input) {\n    count\n    performers {\n      id\n      name\n      disambiguation\n      deleted\n      aliases\n      gender\n      birth_date\n      age\n      height\n      hair_color\n      eye_color\n      ethnicity\n      country\n      career_end_year\n      career_start_year\n      breast_type\n      waist_size\n      hip_size\n      band_size\n      cup_size\n      tattoos {\n        location\n        description\n        __typename\n      }\n      piercings {\n        location\n        description\n        __typename\n      }\n      urls {\n        ...URLFragment\n        __typename\n      }\n      images {\n        ...ImageFragment\n        __typename\n      }\n      is_favorite\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment URLFragment on URL {\n  url\n  site {\n    id\n    name\n    icon\n    __typename\n  }\n  __typename\n}\n\nfragment ImageFragment on Image {\n  id\n  url\n  width\n  height\n  __typename\n}",
}

response = requests.post(
    "https://stashdb.org/graphql",
    headers=stashdb_headers,
    json=stashdb_favorite_performers_payload,
)
data = response.json()
stashdb_favorite_performers = [x for x in data["data"]["queryPerformers"]["performers"]]
len(stashdb_favorite_performers)

print("stashdb favorite performers", len(stashdb_favorite_performers))


# %%
# TODO: cache this

# search for each site by name on whisparr

example_response_studio_when_searching_in_whisparr = {
    "title": "Brazzers Vault",
    "sortTitle": "brazzers vault",
    "status": "ended",
    "ended": True,
    "overview": "Brazzers Vault is a part of the Mind Geek network.",
    "network": "Mind Geek",
    "images": [
        {
            "coverType": "poster",
            "url": "/MediaCoverProxy/2593114f4778ed1427d39d7706b55192f823b32ffbfe5494b6c085a5b119ae11/poster.jpg",
            "remoteUrl": "https://cdn.theporndb.net/sites/db/5f/e9/90621fcefb7c21fcbe49c1c630d5de2/poster/poster.jpg",
        },
        {
            "coverType": "logo",
            "url": "/MediaCoverProxy/d603039d5356d02c100e7d8bf2c46e07c9a8b6337bc1e046718f55a670e2e4f2/brazzersvault-logo.png",
            "remoteUrl": "https://cdn.theporndb.net/sites/1b/1d/a8/48bcdfc13a9cd52a9c91391d54734e4/logo/brazzersvault-logo.png",
        },
    ],
    "originalLanguage": {"id": 1, "name": "English"},
    "remotePoster": "https://cdn.theporndb.net/sites/db/5f/e9/90621fcefb7c21fcbe49c1c630d5de2/poster/poster.jpg",
    "seasons": [],
    "year": 0,
    "qualityProfileId": 0,
    "monitored": True,
    "monitorNewItems": "all",
    "useSceneNumbering": False,
    "runtime": 32,
    "tvdbId": 116,
    "cleanTitle": "brazzersvault",
    "titleSlug": "brazzersvault",
    "folder": "Brazzers Vault",
    "genres": [],
    "tags": [],
    "added": "0001-01-01T00:00:00Z",
    "ratings": {"votes": 0, "value": 0},
    "statistics": {
        "seasonCount": 0,
        "episodeFileCount": 0,
        "episodeCount": 0,
        "totalEpisodeCount": 0,
        "sizeOnDisk": 0,
        "percentOfEpisodes": 0,
    },
}


# Initialize WhisparrAPI (using SonarrAPI since they're identical)

whisparr = SonarrAPI(WHISPARR_BASE_URL, whisparr_headers["X-Api-Key"])


def update_studio_on_whisparr(studio_id: int):
    # Get current series data
    series = whisparr.get_series(studio_id)

    # Update monitoring options
    series["monitored"] = True
    series["monitorNewItems"] = "all"
    series["seasons"] = [
        {"monitored": True, "seasonNumber": season["seasonNumber"]}
        for season in series.get("seasons", [])
    ]
    # Get all episodes for this series
    episodes = whisparr.get_episode(series["id"], series=True)

    # Update all episodes to be monitored
    updated = whisparr.upd_series(data=series)
    episode_ids = [ep["id"] for ep in episodes if not ep.get("monitored", False)]
    whisparr.upd_episode_monitor(episode_ids=episode_ids, monitored=True)
    # Update series with monitoring enabled and search for episodes

    # Search for all monitored episodes
    whisparr.post_command(name="SeriesSearch", seriesId=studio_id)
    return updated


def add_studio_to_whisparr(studio_name: str):
    # Search for studio using series lookup endpoint
    results = whisparr.lookup_series(term=studio_name)
    # print(f'{results=}')
    results = [r for r in results if isinstance(r, dict)]
    if not results:
        raise ValueError(f"No results found for studio: {studio_name}")

    # Get best match
    data = results[0]
    # data = min(results, key=lambda x: len(set(x['title'].lower()) ^ set(studio_name.lower())))
    # print(f'[d] Found {len(results)} results while searching for "{studio_name}": {[x["title"] for x in results]}\nUsing: {data["title"]}')

    # Update required fields
    data["qualityProfileId"] = 1
    data["addOptions"] = {
        "monitor": "all",
        "searchForMissingEpisodes": True,
        "searchForCutoffUnmetEpisodes": False,
    }
    data["rootFolderPath"] = "/data/media/whisparr"

    # first check if studio is already added
    if "id" not in data:
        # Add studio using series endpoint
        data = whisparr.add_series(
            series=data,
            quality_profile_id=1,
            language_profile_id=1,  # Using default language profile ID
            root_dir="/data/media/whisparr",
            search_for_missing_episodes=True,
        )
        logger.debug(f"Studio {studio_name} not found on Whisparr, added", end=" ")
    else:
        logger.info(f'Studio "{studio_name}" already added to Whisparr', end=" ")
    logger.info(WHISPARR_BASE_URL + "/site/" + data["sortTitle"].replace(" ", ""))

    # # Update monitoring options
    update_data = update_studio_on_whisparr(data["id"])
    return data, update_data


# studio_name = 'Futabasha'
# studio_data, update_data = add_studio_to_whisparr(studio_name)


def add_studio_wrapper(studio):
    try:
        studio_data, update_data = add_studio_to_whisparr(studio["name"])
        return studio_data, update_data
    except Exception as e:
        logger.error(f"Error adding studio {studio['name']}: {e}")
        return None, None


with ThreadPool() as pool:
    results = list(
        tqdm(
            pool.imap(add_studio_wrapper, stashdb_favorite_studios),
            total=len(stashdb_favorite_studios),
            desc="Adding studios from stashdb to Whisparr",
        )
    )

# %%

parsed = urllib.parse.urlparse(STASH_BASE_URL)
scheme = parsed.scheme
host = parsed.hostname
port = parsed.port

stash = StashInterface(
    {
        "scheme": scheme,
        "host": host,
        "port": port,
        "ApiKey": STASH_API_KEY,
        "logger": log,
    }
)


# %%


@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.RequestException, requests.exceptions.HTTPError),
    max_tries=5,
    jitter=None,
)
@loggo
@memory.cache(ignore=[])
def stashdb_id_to_stashapp_performer(id: int):
    json_data = {
        "operationName": "FindPerformers",
        "variables": {
            "filter": {
                "q": "",
                "page": 1,
                "per_page": 40,
            },
            "performer_filter": {
                "stash_id_endpoint": {
                    "endpoint": "",
                    "stash_id": id,
                    "modifier": "EQUALS",
                },
            },
        },
        "query": "query FindPerformers($filter: FindFilterType, $performer_filter: PerformerFilterType, $performer_ids: [Int!]) {\n  findPerformers(\n    filter: $filter\n    performer_filter: $performer_filter\n    performer_ids: $performer_ids\n  ) {\n    count\n    performers {\n      ...PerformerData\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment PerformerData on Performer {\n  id\n  name\n  disambiguation\n  urls\n  gender\n  birthdate\n  ethnicity\n  country\n  eye_color\n  height_cm\n  measurements\n  fake_tits\n  penis_length\n  circumcised\n  career_length\n  tattoos\n  piercings\n  alias_list\n  favorite\n  ignore_auto_tag\n  image_path\n  scene_count\n  image_count\n  gallery_count\n  group_count\n  performer_count\n  o_counter\n  tags {\n    ...SlimTagData\n    __typename\n  }\n  stash_ids {\n    stash_id\n    endpoint\n    __typename\n  }\n  rating100\n  details\n  death_date\n  hair_color\n  weight\n  __typename\n}\n\nfragment SlimTagData on Tag {\n  id\n  name\n  aliases\n  image_path\n  parent_count\n  child_count\n  __typename\n}",
    }

    response = requests.post(
        f"{STASH_BASE_URL}/graphql", headers=stash_headers, json=json_data, verify=False
    )
    response.raise_for_status()
    data = response.json()
    return data["data"]["findPerformers"]["performers"]


def stashapp_search_performers(name: str):
    json_data = {
        "operationName": "FindPerformers",
        "variables": {"filter": {"q": name, "page": 1, "per_page": 40}},
        "query": "query FindPerformers($filter: FindFilterType, $performer_filter: PerformerFilterType, $performer_ids: [Int!]) {\n  findPerformers(\n    filter: $filter\n    performer_filter: $performer_filter\n    performer_ids: $performer_ids\n  ) {\n    count\n    performers {\n      ...PerformerData\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment PerformerData on Performer {\n  id\n  name\n  disambiguation\n  urls\n  gender\n  birthdate\n  ethnicity\n  country\n  eye_color\n  height_cm\n  measurements\n  fake_tits\n  penis_length\n  circumcised\n  career_length\n  tattoos\n  piercings\n  alias_list\n  favorite\n  ignore_auto_tag\n  image_path\n  scene_count\n  image_count\n  gallery_count\n  group_count\n  performer_count\n  o_counter\n  tags {\n    ...SlimTagData\n    __typename\n  }\n  stash_ids {\n    stash_id\n    endpoint\n    __typename\n  }\n  rating100\n  details\n  death_date\n  hair_color\n  weight\n  __typename\n}\n\nfragment SlimTagData on Tag {\n  id\n  name\n  aliases\n  image_path\n  parent_count\n  child_count\n  __typename\n}",
    }

    response = requests.post(
        f"{STASH_BASE_URL}/graphql", headers=stash_headers, json=json_data, verify=False
    )
    response.raise_for_status()
    data = response.json()
    return data["data"]["findPerformers"]["performers"]


for stashdb_performer in tqdm(
    stashdb_favorite_performers, desc="Adding performers from stashdb to StashApp"
):
    stashapp_performers = stashdb_id_to_stashapp_performer(stashdb_performer["id"])
    stashdb_url = f"https://stashdb.org/performers/{stashdb_performer['id']}"
    performer_name = stashdb_performer["name"]
    if not stashapp_performers:
        logger.warning(
            f'Performer not found on StashApp, retrying with name search "{performer_name}"',
            end=" ... ",
        )
        stashapp_performers = stashapp_search_performers(performer_name)
        if not stashapp_performers:
            logger.error(
                f'name search failed, skipping "{performer_name}" ({stashdb_url})'
            )
            continue
        else:
            stashapp_url = f"{STASH_BASE_URL}/performers/{stashapp_performers[0]['id']}"
            logger.info(
                f'Found {len(stashapp_performers)} performers on StashApp for "{performer_name}" ({stashdb_url}) -> {stashapp_url}'
            )

    stashapp_url = f"{STASH_BASE_URL}/performers/{stashapp_performers[0]['id']}"
    stashapp_performer = stashapp_performers[0]

    if stashapp_performer["favorite"]:
        # print(f"[i] Performer already favorite on StashApp "{performer_name}" ({stashdb_url}) {stashapp_url}")
        continue

    ## set as favorite
    json_data = {
        "operationName": "PerformerUpdate",
        "variables": {
            "input": {
                "id": stashapp_performer["id"],
                "favorite": True,
            },
        },
        "query": "mutation PerformerUpdate($input: PerformerUpdateInput!) {\n  performerUpdate(input: $input) {\n    ...PerformerData\n    __typename\n  }\n}\n\nfragment PerformerData on Performer {\n  id\n  name\n  disambiguation\n  urls\n  gender\n  birthdate\n  ethnicity\n  country\n  eye_color\n  height_cm\n  measurements\n  fake_tits\n  penis_length\n  circumcised\n  career_length\n  tattoos\n  piercings\n  alias_list\n  favorite\n  ignore_auto_tag\n  image_path\n  scene_count\n  image_count\n  gallery_count\n  group_count\n  performer_count\n  o_counter\n  tags {\n    ...SlimTagData\n    __typename\n  }\n  stash_ids {\n    stash_id\n    endpoint\n    __typename\n  }\n  rating100\n  details\n  death_date\n  hair_color\n  weight\n  __typename\n}\n\nfragment SlimTagData on Tag {\n  id\n  name\n  aliases\n  image_path\n  parent_count\n  child_count\n  __typename\n}",
    }

    logger.info(
        f'Setting "{performer_name}" ({stashdb_url}) as favorite on StashApp {stashapp_url}'
    )
    response = requests.post(
        f"{STASH_BASE_URL}/graphql", headers=stash_headers, json=json_data, verify=False
    )
    response.raise_for_status()
    logger.debug(response.json())


# %%


@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.RequestException, requests.exceptions.HTTPError),
    max_tries=5,
    jitter=None,
)
@loggo
@memory.cache(ignore=[])
def stashdb_id_to_stashapp_studio(id: int):
    json_data = {
        "operationName": "FindStudios",
        "variables": {
            "filter": {
                "q": "",
                "page": 1,
                "per_page": 40,
            },
            "studio_filter": {
                "stash_id_endpoint": {
                    "endpoint": "",
                    "stash_id": id,
                    "modifier": "EQUALS",
                },
            },
        },
        "query": "query FindStudios($filter: FindFilterType, $studio_filter: StudioFilterType) {\n  findStudios(filter: $filter, studio_filter: $studio_filter) {\n    count\n    studios {\n      ...StudioData\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment StudioData on Studio {\n  id\n  name\n  url\n  parent_studio {\n    id\n    name\n    url\n    __typename\n  }\n  child_studios {\n    id\n    name\n    __typename\n  }\n  image_path\n  scene_count\n  image_count\n  gallery_count\n  performer_count\n  details\n  rating100\n  favorite\n  aliases\n  stash_ids {\n    stash_id\n    endpoint\n    __typename\n  }\n  __typename\n}",
    }

    response = requests.post(
        f"{STASH_BASE_URL}/graphql", headers=stash_headers, json=json_data, verify=False
    )
    response.raise_for_status()
    data = response.json()
    return data["data"]["findStudios"]["studios"]


@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.RequestException, requests.exceptions.HTTPError),
    max_tries=5,
    jitter=None,
)
@loggo
@memory.cache(ignore=[])
def stashapp_search_studios(name: str):
    json_data = {
        "operationName": "FindStudios",
        "variables": {"filter": {"q": name, "page": 1, "per_page": 40}},
        "query": "query FindStudios($filter: FindFilterType, $studio_filter: StudioFilterType) {\n  findStudios(filter: $filter, studio_filter: $studio_filter) {\n    count\n    studios {\n      ...StudioData\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment StudioData on Studio {\n  id\n  name\n  url\n  parent_studio {\n    id\n    name\n    url\n    __typename\n  }\n  child_studios {\n    id\n    name\n    __typename\n  }\n  image_path\n  scene_count\n  image_count\n  gallery_count\n  performer_count\n  details\n  rating100\n  favorite\n  aliases\n  stash_ids {\n    stash_id\n    endpoint\n    __typename\n  }\n  __typename\n}",
    }

    response = requests.post(
        f"{STASH_BASE_URL}/graphql", headers=stash_headers, json=json_data, verify=False
    )
    response.raise_for_status()
    data = response.json()
    return data["data"]["findStudios"]["studios"]


for stashdb_studio in tqdm(
    stashdb_favorite_studios, desc="Adding studios from stashdb to StashApp"
):
    stashapp_studios = stashdb_id_to_stashapp_studio(stashdb_studio["id"])
    stashdb_url = f"https://stashdb.org/studios/{stashdb_studio['id']}"
    studio_name = stashdb_studio["name"]
    if not stashapp_studios:
        logger.warning(
            f'Studio not found on StashApp, retrying with name search "{studio_name}"',
            end=" ... ",
        )
        stashapp_studios = stashapp_search_studios(studio_name)
        if not stashapp_studios:
            logger.error(
                f'name search failed, skipping "{studio_name}" ({stashdb_url})'
            )
            continue
        else:
            stashapp_url = f"{STASH_BASE_URL}/studios/{stashapp_studios[0]['id']}"
            logger.info(
                f'Found {len(stashapp_studios)} studios on StashApp for "{studio_name}" ({stashdb_url}) -> {stashapp_url}'
            )

    stashapp_url = f"{STASH_BASE_URL}/studios/{stashapp_studios[0]['id']}"
    stashapp_studio = stashapp_studios[0]

    if stashapp_studio["favorite"]:
        logger.info(
            f'Studio already favorite on StashApp "{studio_name}" ({stashdb_url}) {stashapp_url}'
        )
        continue

    ## set as favorite
    json_data = {
        "operationName": "StudioUpdate",
        "variables": {
            "input": {
                "id": stashapp_studio["id"],
                "favorite": True,
            },
        },
        "query": "mutation StudioUpdate($input: StudioUpdateInput!) {\n  studioUpdate(input: $input) {\n    ...StudioData\n    __typename\n  }\n}\n\nfragment StudioData on Studio {\n  id\n  name\n  url\n  parent_studio {\n    id\n    name\n    url\n    __typename\n  }\n  child_studios {\n    id\n    name\n    __typename\n  }\n  image_path\n  scene_count\n  image_count\n  gallery_count\n  performer_count\n  details\n  rating100\n  favorite\n  aliases\n  stash_ids {\n    stash_id\n    endpoint\n    __typename\n  }\n  __typename\n}",
    }

    logger.info(
        f'Setting "{studio_name}" ({stashdb_url}) as favorite on StashApp {stashapp_url}'
    )
    response = requests.post(
        f"{STASH_BASE_URL}/graphql", headers=stash_headers, json=json_data, verify=False
    )
    response.raise_for_status()
    logger.debug(response.json())


# %%
tpdb_ids = {}


def get_tpdb_performer_data(id: str):
    json_data = {
        "operationName": "FullPerformer",
        "variables": {
            "id": id,
        },
        "query": "query FullPerformer($id: ID!) {\n  findPerformer(id: $id) {\n    ...PerformerFragment\n    studios {\n      scene_count\n      studio {\n        id\n        name\n        parent {\n          id\n          name\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment URLFragment on URL {\n  url\n  site {\n    id\n    name\n    icon\n    __typename\n  }\n  __typename\n}\n\nfragment ImageFragment on Image {\n  id\n  url\n  width\n  height\n  __typename\n}\n\nfragment PerformerFragment on Performer {\n  id\n  name\n  disambiguation\n  deleted\n  aliases\n  gender\n  birth_date\n  age\n  height\n  hair_color\n  eye_color\n  ethnicity\n  country\n  career_end_year\n  career_start_year\n  breast_type\n  waist_size\n  hip_size\n  band_size\n  cup_size\n  tattoos {\n    location\n    description\n    __typename\n  }\n  piercings {\n    location\n    description\n    __typename\n  }\n  urls {\n    ...URLFragment\n    __typename\n  }\n  images {\n    ...ImageFragment\n    __typename\n  }\n  is_favorite\n  __typename\n}",
    }

    response = requests.post(
        "https://stashdb.org/graphql", headers=stashdb_headers, json=json_data
    )
    response.raise_for_status()
    performer_data = response.json()
    logger.debug(f"Performer: {performer_data}")

    try:
        porndb_url = next(
            url["url"]
            for url in performer_data["data"]["findPerformer"]["urls"]
            if url["site"]["name"] == "ThePornDB"
        )
        response = requests.get(porndb_url, headers=tpdb_headers)
        response.raise_for_status()
        parsed_html = BeautifulSoup(response.text, "html.parser")
        tpdb_performer_data = json.loads(parsed_html.find(id="app")["data-page"])[
            "props"
        ]["performer"]
    except Exception:
        logger.warning("tpdb url not found, trying to scrape using name...")
        response = requests.get(
            "https://theporndb.net/performers?orderBy=recently_created&page=1&q="
            + requests.utils.quote(performer_data["data"]["findPerformer"]["name"]),
            headers=tpdb_headers,
        )
        response.raise_for_status()
        parsed_html = BeautifulSoup(response.text, "html.parser")
        data = json.loads(parsed_html.find(id="app")["data-page"])
        tpdb_performer_data = data["props"]["performers"]["data"][0]
    return tpdb_performer_data


tpdb_performer_datas = list(
    tqdm(
        ThreadPool(10).imap(
            get_tpdb_performer_data, [x["id"] for x in stashdb_favorite_performers]
        ),
        total=len(stashdb_favorite_performers),
        desc="Getting TPDB performer data",
    )
)
for tpdb_performer_data in tpdb_performer_datas:
    tpdb_ids[tpdb_performer_data["id"]] = tpdb_performer_data["slug"]


# %%
len(tpdb_ids)

# %%
# theporndb: add them to favorite performers

for id, name in tqdm(tpdb_ids.items(), desc="Adding performers to TPDB favorites"):
    json_data = {
        "type": "performer",
        "value": id,
    }
    while True:
        # toggle
        response = requests.post(
            "https://api.theporndb.net/favourites", headers=tpdb_headers, json=json_data
        )
        response.raise_for_status()
        if response.json()["value"] is True:
            break
    logger.info(
        f"Added performer {name} (ID: {id}) to TPDB favorites",
        response.json(),
        "url",
        f"https://theporndb.net/performers/{name}",
    )


# %%


def create_tag(name):
    json_data = {
        "label": name,
    }

    response = requests.post(
        f"{WHISPARR_BASE_URL}/api/v3/tag",
        headers=whisparr_headers,
        json=json_data,
        verify=False,
    )
    response.raise_for_status()
    return response.json()["id"]


def get_importlists():
    response = requests.get(
        f"{WHISPARR_BASE_URL}/api/v3/importlist", headers=whisparr_headers, verify=False
    )
    response.raise_for_status()
    return response.json()


params = ""

for id, name in tqdm(tpdb_ids.items(), desc="Adding performers to Whisparr"):
    tags = [create_tag("performer--" + name), create_tag("performer")]
    json_data = {
        "enableAutomaticAdd": False,
        "searchForMissingEpisodes": True,
        "shouldMonitor": "specificEpisode",
        "siteMonitorType": "all",
        "monitorNewItems": "all",
        "qualityProfileId": 1,
        "listType": "advanced",
        "listOrder": 5,
        "minRefreshInterval": "06:00:00",
        "fields": [
            {
                "name": "performerId",
                "value": str(id),
            },
        ],
        "implementationName": "TPDb Performer",
        "implementation": "TPDbPerformer",
        "configContract": "TPDbPerformerSettings",
        "infoLink": "https://wiki.servarr.com/whisparr/supported#tpdbperformer",
        "tags": tags,
        "name": f"{name} - {id}",
        "rootFolderPath": "/data/media/whisparr",
    }

    response = requests.post(
        f"{WHISPARR_BASE_URL}/api/v3/importlist",
        params=params,
        headers=whisparr_headers,
        json=json_data,
        verify=False,
    )
    # response.raise_for_status()
    print(response.json())


# %%
# %pip install joblib loguru backoff warpt

# %%
# from loguru import logger
# import logging
# from joblib import Memory
# import requests
# import backoff

# # Set up Joblib memory for caching
# cachedir = 'cache_directory'
# mem = Memory(cachedir)

# # Define a function with backoff for retries
# @backoff.on_exception(backoff.expo,
#                       requests.exceptions.RequestException,
#                       max_tries=5)  # Retry up to 5 times
# # @logger.catch  # Logs exceptions automatically
# @mem.cache  # Apply the Joblib caching decorator
# def requests_get(*args, **kwargs):
#     logger.info(f"Fetching data from URL: {args[0]}")  # Log input
#     response = requests.get(*args, **kwargs)
#     response.raise_for_status()  # Raise an exception for HTTP errors
#     data = response.json()
#     logger.info(f"Fetched data: {data}")  # Log output
#     return data

# # Example usage
# try:
#     data = requests_get('https://api.theporndb.net/performers/9ac1b398-106c-495b-887d-c588b89cba9d',  headers=tpdb_headers)
# except Exception as e:
#     logger.error(f"An error occurred: {e}")


# %%


# %%
# from loguru import logger
# from joblib import Memory
# import requests
# import backoff

# # Configure Loguru to log to a file
# logger.add("app.log", format="{time} {level} {message}", level="DEBUG")

# # Set up Joblib memory for caching
# cachedir = 'cache_directory'
# mem = Memory(cachedir)

# # Custom logging decorator
# def loggo(func):
#     def wrapper(*args, **kwargs):
#         # Log the function call with its arguments
#         logger.info(f"Calling {func.__name__} with args={args} kwargs={kwargs}")
#         try:
#             result = func(*args, **kwargs)
#             # Log the return value
#             logger.info(f"{func.__name__} returned {result}")
#             return result
#         except Exception as e:
#             # Log the exception if it occurs
#             logger.error(f"Error in {func.__name__}: {e}")
#             raise  # Re-raise the exception after logging it
#     return wrapper

# # Define a function with backoff for retries
# @backoff.on_exception(backoff.expo,
#                       requests.exceptions.RequestException,
#                       max_tries=5)  # Retry up to 5 times
# @loggo  # Apply the logging decorator
# @mem.cache  # Apply the Joblib caching decorator
# def fetch_data(api_url):
#     response = requests.get(api_url)
#     response.raise_for_status()  # Raise an exception for HTTP errors
#     return response.json()

# # Example usage
# try:
#     data = fetch_data('https://api.example.com/data')
# except Exception as e:
#     logger.error(f"An error occurred: {e}")


# %%


@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.RequestException, requests.exceptions.HTTPError),
    max_tries=5,
    jitter=None,
)
@loggo
@memory.cache(ignore=[])
def get_tpdb_page(performer_slug: str, page: int, per_page: int) -> requests.Response:
    """Get a single page of scenes for a performer from ThePornDB"""
    url = f"https://theporndb.net/performers/{performer_slug}"
    params = {
        "scenes_page": page,
        "movies_page": 1,
        "jav_page": 1,
        "per_page": per_page,
    }
    headers = {
        "x-inertia": "true",
        "x-inertia-version": "a5070278aaf7e9364d2c3f9c697b6df5",
        **tpdb_headers,
    }
    return requests_get(url, params=params, headers=headers)


def get_tpdb_performer_scenes(performer_slug, per_page=1000):
    """
    Get all scenes for a performer from ThePornDB


    curl 'https://theporndb.net/performers/jade-maris?scenes_page=4&movies_page=1&jav_page=1&per_page=10' \
        -H 'accept: text/html, application/xhtml+xml' \
        -H 'accept-language: en-US,en;q=0.9' \
        -H 'content-type: application/json' \
        -H 'priority: u=1, i' \
        -H 'referer: https://theporndb.net/performers/jade-maris?jav_page=1&movies_page=1&per_page=10&scenes_page=3'
    
    response.json()['props']['scenes']['data'][i]
    """
    scenes = []
    page = 1
    pbar = tqdm(total=5000, desc=f"Getting TPDB scenes for {performer_slug}")
    while True:
        response = get_tpdb_page(performer_slug, page, per_page)
        # Parse response HTML to get scenes
        # If no more scenes found, break
        if not response.ok:
            break

        try:
            response_json = response.json()
        except Exception as e:
            print(f"Error parsing response: {e}")
            print(response.text)
            # Save error response to HTML file for debugging
            with open("tpdb_error.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            print("Saved error response to tpdb_error.html")
            raise e

        scenes.extend(response_json["props"]["scenes"]["data"])
        page += 1
        pbar.update(len(response_json["props"]["scenes"]["data"]))
    return scenes


# for id, name in tqdm(tpdb_ids.items(), desc="Getting TPDB scenes"):
#     scenes = get_tpdb_performer_scenes(name)
#     print(scenes)


# %%
## Set all scenes as unorganized

# page = 1
# per_page = 100
# total_scenes = []

# pbar = tqdm(total=1000000, desc="Setting scenes as unorganized")
# while True:
#     scenes_page = stash.find_scenes(filter={'per_page': per_page, 'page': page})
#     if not scenes_page:
#         break
#     total_scenes.extend(scenes_page)
#     page += 1
#     pbar.update(len(scenes_page))

# for scene in tqdm(total_scenes, desc="Setting scenes as unorganized"):
#     stash.update_scene({
#         'id': scene['id'],
#         'organized': False
#     })
update_sync_timestamp()
