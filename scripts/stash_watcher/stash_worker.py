#!/usr/bin/python3

from pathlib import Path

import time
import json
import traceback
import requests
import stashapi.log as log
from stashapi.stashapp import StashInterface
from urllib.parse import urlparse
import os
import sys

STASH_API_KEY = os.environ["STASH_API_KEY"]
STASH_BASE_URL = os.environ["STASH_BASE_URL"]

# Add this directory to sys.path
try:
    ai_tagger_config_path = "../../provision/stash/plugins/community/ai_tagger/"
    sys.path.append(os.path.abspath(ai_tagger_config_path))
    import config as ai_config
except Exception as e:
    try:
        log.error(f"Failed to import ai_config: {e}")
        ai_tagger_config_path = "../provision/stash/plugins/community/ai_tagger/"
        sys.path.append(os.path.abspath(ai_tagger_config_path))
        import config as ai_config
    except Exception as ee:
        log.error(f"Failed to import ai_config: {ee}")

try:
    path_mutation = {v: k for v, k in ai_config.path_mutation.items()}
    ai_server_baseurl = ai_config.API_BASE_URL
except Exception as e:
    log.error(f"Failed to import ai_config: {e}")
    path_mutation = {}
    ai_server_baseurl = ""

url = urlparse(STASH_BASE_URL)

connection = {
    "scheme": url.scheme,
    "host": url.hostname,
    "port": url.port,
    "logger": log,
    "ApiKey": STASH_API_KEY,
}
STASH_HEADERS = {
    "content-type": "application/json",
    "ApiKey": STASH_API_KEY,
}


FIND_SCENES_FRAGMENT = """
fragment SlimSceneData on Scene {
  id
  title
  code
  details
  director
  urls
  date
  rating100
  o_counter
  organized
  interactive
  interactive_speed
  resume_time
  play_duration
  play_count
  files {
    ...VideoFileData
    __typename
  }
  paths {
    screenshot
    preview
    stream
    webp
    vtt
    sprite
    funscript
    interactive_heatmap
    caption
    __typename
  }
  scene_markers {
    id
    title
    seconds
    primary_tag {
      id
      name
      __typename
    }
    __typename
  }
  galleries {
    id
    files {
      path
      __typename
    }
    folder {
      path
      __typename
    }
    title
    __typename
  }
  studio {
    id
    name
    image_path
    __typename
  }
  groups {
    group {
      id
      name
      front_image_path
      __typename
    }
    scene_index
    __typename
  }
  tags {
    id
    name
    __typename
  }
  performers {
    id
    name
    disambiguation
    gender
    favorite
    image_path
    __typename
  }
  stash_ids {
    endpoint
    stash_id
    __typename
  }
  __typename
}

fragment VideoFileData on VideoFile {
  id
  path
  size
  mod_time
  duration
  video_codec
  audio_codec
  width
  height
  frame_rate
  bit_rate
  fingerprints {
    type
    value
    __typename
  }
  __typename
}"""
FIND_SCENES_FRAGMENT = None


def get_watch_directories():
    json_data = {
        "operationName": "Configuration",
        "variables": {},
        "query": "query Configuration {\n  configuration {\n    ...ConfigData\n    __typename\n  }\n}\n\nfragment ConfigData on ConfigResult {\n  general {\n    ...ConfigGeneralData\n    __typename\n  }\n  interface {\n    ...ConfigInterfaceData\n    __typename\n  }\n  dlna {\n    ...ConfigDLNAData\n    __typename\n  }\n  scraping {\n    ...ConfigScrapingData\n    __typename\n  }\n  defaults {\n    ...ConfigDefaultSettingsData\n    __typename\n  }\n  ui\n  plugins\n  __typename\n}\n\nfragment ConfigGeneralData on ConfigGeneralResult {\n  stashes {\n    path\n    excludeVideo\n    excludeImage\n    __typename\n  }\n  databasePath\n  backupDirectoryPath\n  generatedPath\n  metadataPath\n  scrapersPath\n  pluginsPath\n  cachePath\n  blobsPath\n  blobsStorage\n  ffmpegPath\n  ffprobePath\n  calculateMD5\n  videoFileNamingAlgorithm\n  parallelTasks\n  previewAudio\n  previewSegments\n  previewSegmentDuration\n  previewExcludeStart\n  previewExcludeEnd\n  previewPreset\n  transcodeHardwareAcceleration\n  maxTranscodeSize\n  maxStreamingTranscodeSize\n  writeImageThumbnails\n  createImageClipsFromVideos\n  apiKey\n  username\n  password\n  maxSessionAge\n  logFile\n  logOut\n  logLevel\n  logAccess\n  createGalleriesFromFolders\n  galleryCoverRegex\n  videoExtensions\n  imageExtensions\n  galleryExtensions\n  excludes\n  imageExcludes\n  customPerformerImageLocation\n  stashBoxes {\n    name\n    endpoint\n    api_key\n    __typename\n  }\n  pythonPath\n  transcodeInputArgs\n  transcodeOutputArgs\n  liveTranscodeInputArgs\n  liveTranscodeOutputArgs\n  drawFunscriptHeatmapRange\n  scraperPackageSources {\n    name\n    url\n    local_path\n    __typename\n  }\n  pluginPackageSources {\n    name\n    url\n    local_path\n    __typename\n  }\n  __typename\n}\n\nfragment ConfigInterfaceData on ConfigInterfaceResult {\n  menuItems\n  soundOnPreview\n  wallShowTitle\n  wallPlayback\n  showScrubber\n  maximumLoopDuration\n  noBrowser\n  notificationsEnabled\n  autostartVideo\n  autostartVideoOnPlaySelected\n  continuePlaylistDefault\n  showStudioAsText\n  css\n  cssEnabled\n  javascript\n  javascriptEnabled\n  customLocales\n  customLocalesEnabled\n  language\n  imageLightbox {\n    slideshowDelay\n    displayMode\n    scaleUp\n    resetZoomOnNav\n    scrollMode\n    scrollAttemptsBeforeChange\n    __typename\n  }\n  disableDropdownCreate {\n    performer\n    tag\n    studio\n    movie\n    __typename\n  }\n  handyKey\n  funscriptOffset\n  useStashHostedFunscript\n  __typename\n}\n\nfragment ConfigDLNAData on ConfigDLNAResult {\n  serverName\n  enabled\n  port\n  whitelistedIPs\n  interfaces\n  videoSortOrder\n  __typename\n}\n\nfragment ConfigScrapingData on ConfigScrapingResult {\n  scraperUserAgent\n  scraperCertCheck\n  scraperCDPPath\n  excludeTagPatterns\n  __typename\n}\n\nfragment ConfigDefaultSettingsData on ConfigDefaultSettingsResult {\n  scan {\n    scanGenerateCovers\n    scanGeneratePreviews\n    scanGenerateImagePreviews\n    scanGenerateSprites\n    scanGeneratePhashes\n    scanGenerateThumbnails\n    scanGenerateClipPreviews\n    __typename\n  }\n  identify {\n    sources {\n      source {\n        ...ScraperSourceData\n        __typename\n      }\n      options {\n        ...IdentifyMetadataOptionsData\n        __typename\n      }\n      __typename\n    }\n    options {\n      ...IdentifyMetadataOptionsData\n      __typename\n    }\n    __typename\n  }\n  autoTag {\n    performers\n    studios\n    tags\n    __typename\n  }\n  generate {\n    covers\n    sprites\n    previews\n    imagePreviews\n    previewOptions {\n      previewSegments\n      previewSegmentDuration\n      previewExcludeStart\n      previewExcludeEnd\n      previewPreset\n      __typename\n    }\n    markers\n    markerImagePreviews\n    markerScreenshots\n    transcodes\n    phashes\n    interactiveHeatmapsSpeeds\n    clipPreviews\n    imageThumbnails\n    __typename\n  }\n  deleteFile\n  deleteGenerated\n  __typename\n}\n\nfragment ScraperSourceData on ScraperSource {\n  stash_box_index\n  stash_box_endpoint\n  scraper_id\n  __typename\n}\n\nfragment IdentifyMetadataOptionsData on IdentifyMetadataOptions {\n  fieldOptions {\n    ...IdentifyFieldOptionsData\n    __typename\n  }\n  setCoverImage\n  setOrganized\n  includeMalePerformers\n  skipMultipleMatches\n  skipMultipleMatchTag\n  skipSingleNamePerformers\n  skipSingleNamePerformerTag\n  __typename\n}\n\nfragment IdentifyFieldOptionsData on IdentifyFieldOptions {\n  field\n  strategy\n  createMissing\n  __typename\n}",
    }

    response = requests.post(
        STASH_BASE_URL + "/graphql", headers=STASH_HEADERS, json=json_data, verify=False
    )
    response.raise_for_status()
    stashes = response.json()["data"]["configuration"]["general"]["stashes"]
    paths = [
        x["path"] for x in stashes if not x["excludeVideo"] or not x["excludeImage"]
    ]
    return paths


# this is what works rn
def find_scenes(
    self,
    f: dict = {},
    filter: dict = {"per_page": -1},
    q: str = "",
    fragment=None,
    get_count=False,
    callback=None,
):
    import re

    query = """
    query FindScenes($filter: FindFilterType, $scene_filter: SceneFilterType, $scene_ids: [Int!]) {
        findScenes(filter: $filter, scene_filter: $scene_filter, scene_ids: $scene_ids) {
            count
            scenes {
                id
                title
                code
                details
                director
                urls
                date
                rating100
                o_counter
                organized
                interactive
                interactive_speed
                resume_time
                play_duration
                play_count
                files {
                    id
                    path
                    size
                    mod_time
                    duration
                    video_codec
                    audio_codec
                    width
                    height
                    frame_rate
                    bit_rate
                    fingerprints {
                        type
                        value
                    }
                }
                paths {
                    screenshot
                    preview
                    stream
                    webp
                    vtt
                    sprite
                    funscript
                    interactive_heatmap
                    caption
                }
                scene_markers {
                    id
                    title
                    seconds
                    primary_tag {
                        id
                        name
                    }
                }
                galleries {
                    id
                    files {
                        path
                    }
                    folder {
                        path
                    }
                    title
                }
                studio {
                    id
                    name
                    image_path
                }
                movies {
                    movie {
                        id
                        name
                        front_image_path
                    }
                    scene_index
                }
                tags {
                    id
                    name
                }
                performers {
                    id
                    name
                    disambiguation
                    gender
                    favorite
                    image_path
                }
                stash_ids {
                    endpoint
                    stash_id
                }
            }
        }
    }
    """
    if fragment:
        query = re.sub(r"\.\.\.Scene", fragment, query)

    filter["q"] = q
    variables = {"filter": filter, "scene_filter": f}

    result = self.call_GQL(query, variables, callback=callback)
    if get_count:
        return result["findScenes"]["count"], result["findScenes"]["scenes"]
    else:
        return result["findScenes"]["scenes"]


def delete_scene_ids(ids_to_delete):
    json_data = {
        "operationName": "ScenesDestroy",
        "variables": {
            "ids": ids_to_delete,
            "delete_file": True,
            "delete_generated": True,
        },
        "query": "mutation ScenesDestroy($ids: [ID!]!, $delete_file: Boolean, $delete_generated: Boolean) {\n  scenesDestroy(\n    input: {ids: $ids, delete_file: $delete_file, delete_generated: $delete_generated}\n  )\n}",
    }

    response = requests.post(
        STASH_BASE_URL + "/graphql", headers=STASH_HEADERS, json=json_data, verify=False
    )
    response.raise_for_status()
    return response.json()


def get_duplicate_scenes():
    json_data = {
        "operationName": "FindDuplicateScenes",
        "variables": {
            "distance": 10,
            "duration_diff": -1,
        },
        "query": "query FindDuplicateScenes($distance: Int, $duration_diff: Float) {\n  findDuplicateScenes(distance: $distance, duration_diff: $duration_diff) {\n    ...SlimSceneData\n    __typename\n  }\n}\n\nfragment SlimSceneData on Scene {\n  id\n  title\n  code\n  details\n  director\n  urls\n  date\n  rating100\n  o_counter\n  organized\n  interactive\n  interactive_speed\n  resume_time\n  play_duration\n  play_count\n  files {\n    ...VideoFileData\n    __typename\n  }\n  paths {\n    screenshot\n    preview\n    stream\n    webp\n    vtt\n    sprite\n    funscript\n    interactive_heatmap\n    caption\n    __typename\n  }\n  scene_markers {\n    id\n    title\n    seconds\n    primary_tag {\n      id\n      name\n      __typename\n    }\n    __typename\n  }\n  galleries {\n    id\n    files {\n      path\n      __typename\n    }\n    folder {\n      path\n      __typename\n    }\n    title\n    __typename\n  }\n  studio {\n    id\n    name\n    image_path\n    __typename\n  }\n  movies {\n    movie {\n      id\n      name\n      front_image_path\n      __typename\n    }\n    scene_index\n    __typename\n  }\n  tags {\n    id\n    name\n    __typename\n  }\n  performers {\n    id\n    name\n    disambiguation\n    gender\n    favorite\n    image_path\n    __typename\n  }\n  stash_ids {\n    endpoint\n    stash_id\n    __typename\n  }\n  __typename\n}\n\nfragment VideoFileData on VideoFile {\n  id\n  path\n  size\n  mod_time\n  duration\n  video_codec\n  audio_codec\n  width\n  height\n  frame_rate\n  bit_rate\n  fingerprints {\n    type\n    value\n    __typename\n  }\n  __typename\n}",
    }

    response = requests.post(
        STASH_BASE_URL + "/graphql", headers=STASH_HEADERS, json=json_data, verify=False
    )
    response.raise_for_status()
    return response.json()


def del_duplicates_main():
    data = get_duplicate_scenes()
    # for each group we want to select all files except the largest one
    ids_to_delete = []
    for scenes in data["data"]["findDuplicateScenes"]:
        scenes.sort(key=lambda scene: max([f["size"] for f in scene["files"]]))
        for scene in scenes[:-1]:
            ids_to_delete.append(scene["id"])

    print("IDs to delete", ids_to_delete)

    if ids_to_delete:
        delete_scene_ids(ids_to_delete)


def get_closest_parent_directory(path):
    path = Path(path)
    if path.is_dir():
        return str(path)
    if path.is_file():
        return str(path.parent)


def wait_for_job(stash, job_id, status="FINISHED", period=1.5, timeout=12000):
    """Waits for stash job to match desired status

    Args:
        job_id (ID): the ID of the job to wait for
        status (str, optional): Desired status to wait for. Defaults to "FINISHED".
        period (float, optional): Interval between checks for job status. Defaults to 1.5.
        timeout (int, optional): time in seconds that if exceeded raises Exception. Defaults to 120.

    Raises:
        Exception: timeout raised if wait task takes longer than timeout

    Returns:
        bool:
            True: job stats is desired status
            False: job finished or was cancelled without matching desired status
            None: job could not be found
    """
    timeout_value = time.time() + timeout
    while time.time() < timeout_value:
        job = stash.find_job(job_id)
        if not job:
            return None
        progress = (
            job["progress"]
            if "progress" in job and job["progress"] is not None
            else 0.0
        )
        stash.log.debug(
            f"Waiting for Job:{job_id} Status:{job['status']} Progress:{progress:.1f}"
        )
        if job["status"] == status:
            return True
        if job["status"] in ["FINISHED", "CANCELLED"]:
            return False
        time.sleep(period)
    raise Exception("Hit timeout waiting for Job to complete")


def main(paths=None):
    paths = None
    if paths is None:
        paths = []
    paths = list(map(Path, paths))
    print("Stash worker script incoming paths:", paths)
    paths += [get_closest_parent_directory(path) for path in paths]
    paths += [
        str(path).replace(old, new)
        for path in paths
        for old, new in path_mutation.items()
    ]
    paths = list(map(str, paths))
    stash = StashInterface(connection)
    stash.wait_for_job = wait_for_job.__get__(stash, StashInterface)
    log.debug("Scanning metadata")
    scan_job = stash.metadata_scan(paths=paths)
    log.debug("Checking for duplicates")
    assert stash.wait_for_job(scan_job)
    del_duplicates_main()
    log.info("mapped paths: " + json.dumps(paths))

    try:
        unorganized_scene_ids = [
            scene["id"] for scene in find_scenes(stash, f={"organized": False})
        ]
        log.info("Unorganized scenes: " + str(len(unorganized_scene_ids)))
        log.debug("Unorganized scenes: " + json.dumps(unorganized_scene_ids))
    except Exception as e:
        log.error("Failed to get unorganized scenes" + str(e))
        unorganized_scene_ids = []

    # shunned scenes (always failing)
    if os.path.isfile("shunned_scenes.json"):
        with open("shunned_scenes.json") as f:
            shunned_scenes = json.load(f)
        unorganized_scene_ids = [
            scene_id
            for scene_id in unorganized_scene_ids
            if scene_id not in shunned_scenes
        ]

    if unorganized_scene_ids:
        log.info("Identifying unorganized scenes")
        # the identify task will go over all the unorganized and tries to identify them, and if successful, it will set the organized field to true
        # later we will check if the unorganized scenes are still unorganized, if so, we will add them to the shunned scenes
        assert stash.wait_for_job(
            stash.stashbox_identify_task(unorganized_scene_ids)["metadataIdentify"]
        )
        shunned_scenes = [
            scene["id"]
            for scene in find_scenes(stash, f={"organized": False})
            if scene["id"] in unorganized_scene_ids
        ]
        try:
            with open("shunned_scenes.json", "w") as f:
                json.dump(shunned_scenes, f, indent=4)
        except OSError as e:
            log.error("Failed to write shunned scenes file: " + str(e))
            log.error(traceback.format_exc())

    non_ai_tagged_scenes = [
        scene
        for scene in find_scenes(stash)
        if "AI_Tagged" not in [tag["name"] for tag in scene.get("tags", [])]
    ]
    if non_ai_tagged_scenes:
        try:
            AI_TAG_ID = stash.find_tag("AI_TagMe")["id"]
            stash.update_scenes(
                {
                    "ids": [x["id"] for x in non_ai_tagged_scenes],
                    "tag_ids": {"mode": "ADD", "ids": [AI_TAG_ID]},
                    # "organized": True
                }
            )
        except Exception as e:
            log.error("Failed to add AI_TagMe tag to non AI tagged scenes: " + str(e))

    # check if ai server is running
    try:
        response = requests.get(ai_server_baseurl + "/docs", timeout=100)
        response.raise_for_status()
        log.info("AI Server is running :D")
        ai_tagger_job_id = stash.run_plugin_task(
            plugin_id="ai_tagger",
            task_name="Tag Scenes",
        )
        assert stash.wait_for_job(ai_tagger_job_id)
    except requests.RequestException as e:
        log.error("Failed to connect to AI Server" + str(e))

    log.info("Generating metadata")
    stash.metadata_generate()


if __name__ == "__main__":
    main(get_watch_directories())
