"""Publish an approved reel to Instagram via the Meta Graph API.

Requires the review server to be publicly reachable (Graph API pulls the video by URL).
Env: META_ACCESS_TOKEN (long-lived page token), IG_USER_ID, PUBLIC_BASE_URL.
"""
import json
import os
import time
import urllib.parse
import urllib.request

GRAPH = "https://graph.facebook.com/v21.0"


def _post(path, params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"{GRAPH}/{path}", data=data) as r:
        return json.load(r)


def _get(path, params):
    qs = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{GRAPH}/{path}?{qs}") as r:
        return json.load(r)


def publish_reel(video_url, caption):
    token = os.environ["META_ACCESS_TOKEN"]
    ig_user = os.environ["IG_USER_ID"]
    container = _post(f"{ig_user}/media", {
        "media_type": "REELS", "video_url": video_url,
        "caption": caption, "access_token": token})["id"]
    for _ in range(60):  # Meta transcodes the video; poll until ready
        status = _get(container, {"fields": "status_code", "access_token": token})["status_code"]
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError("Meta could not process the video")
        time.sleep(10)
    else:
        raise TimeoutError("Meta processing timed out")
    return _post(f"{ig_user}/media_publish", {
        "creation_id": container, "access_token": token})["id"]
