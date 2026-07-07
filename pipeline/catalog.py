"""Sync the public Drive folder, proxy new clips, catalog them with Gemini video analysis.

Run on a schedule (cron, flock-guarded in run.sh). Idempotent: keyed by Drive file id,
so duplicate/renamed display names can't collide; downloads land as .part first so a
killed run never leaves a truncated file that gets trusted forever.
Env: GOOGLE_API_KEY (aistudio.google.com/apikey). Optional: FOLDER_ID, GEMINI_VIDEO_MODEL.
"""
import json
import os
import re
import subprocess
import time
import urllib.request

from google import genai

FOLDER_ID = os.environ.get("FOLDER_ID", "1B_UDw8-3s_qnJ61HD4xJcoJspwqflLjd")
VIDEO_MODEL = os.environ.get("GEMINI_VIDEO_MODEL", "gemini-3.5-flash")
BASE = os.path.dirname(os.path.abspath(__file__))
CLIPS = os.path.join(BASE, "clips")
PROXIES = os.path.join(BASE, "proxies")
CATALOG = os.path.join(BASE, "catalog.json")

ANALYZE_PROMPT = """You are cataloging raw footage for a reggae-rock band's (The Bunchy Tops, Maui) social media editor.
Watch this clip and return STRICT JSON (no markdown fences):
{
  "setting": "one-line: where/when this appears to be",
  "content": "2-3 sentences: what happens",
  "audio": "what you hear: live music, talking, ambient, silence",
  "people": "who/how many visible, doing what",
  "camera": "static/handheld/drone, orientation, quality issues (shaky, dark, blurry)",
  "vibe_tags": ["3-6 tags like golden-hour, crowd, soundcheck, ocean, backstage"],
  "energy": 5,
  "moments": [{"start_s": 0, "end_s": 5, "desc": "specific moment worth cutting into a reel", "score": 7}],
  "ig_worthy": true,
  "notes": "anything else an editor should know"
}
List 1-5 moments, only ones genuinely usable in an Instagram Reel. Be honest about quality problems."""


def save_json(obj, path):
    tmp = path + ".tmp"
    json.dump(obj, open(tmp, "w"), indent=1)
    os.replace(tmp, path)


def list_folder():
    url = f"https://drive.google.com/embeddedfolderview?id={FOLDER_ID}#list"
    html = urllib.request.urlopen(url).read().decode()
    return re.findall(r'id="entry-([^"]+)".*?flip-entry-title">([^<]+)<', html)


def download(file_id, dest):
    part = dest + ".part"
    subprocess.run(["gdown", "--id", file_id, "-O", part, "--quiet"], check=True)
    os.replace(part, dest)


def make_proxy(src, dst):
    part = dst + ".part.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "fast", "-crf", "30",
                    "-c:a", "aac", "-ac", "1", "-b:a", "64k", part], check=True)
    os.replace(part, dst)


def probe(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                   "-show_entries", "stream=width,height:format=duration",
                                   "-of", "json", path])
    d = json.loads(out)
    s = d["streams"][0]
    return {"width": s["width"], "height": s["height"],
            "duration": round(float(d["format"]["duration"]), 1)}


def analyze(client, path):
    f = client.files.upload(file=path)
    while f.state == "PROCESSING":
        time.sleep(3)
        f = client.files.get(name=f.name)
    if f.state == "FAILED":
        return {"error": "gemini processing failed"}
    r = client.models.generate_content(model=VIDEO_MODEL, contents=[ANALYZE_PROMPT, f])
    txt = r.text.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return {"raw": txt}


def main():
    os.makedirs(CLIPS, exist_ok=True)
    os.makedirs(PROXIES, exist_ok=True)
    catalog = json.load(open(CATALOG)) if os.path.exists(CATALOG) else {}
    client = genai.Client()

    for file_id, name in list_folder():
        if file_id in catalog:
            continue
        if not re.search(r"\.(mov|mp4|m4v)$", name, re.I):
            continue
        # prefix with the id so duplicate display names can't overwrite each other
        fname = f"{file_id[:8]}_{re.sub(r'[^\\w.-]', '_', name)}"
        local = os.path.join(CLIPS, fname)
        proxy = os.path.join(PROXIES, os.path.splitext(fname)[0] + ".mp4")
        try:
            if not os.path.exists(local):
                print("downloading", name)
                download(file_id, local)
            if not os.path.exists(proxy):
                make_proxy(local, proxy)
            entry = probe(local)
            entry["name"] = name
            entry["file"] = fname
            print("analyzing", name)
            entry["analysis"] = analyze(client, proxy)
            catalog[file_id] = entry
            save_json(catalog, CATALOG)
        except Exception as e:  # one bad clip must not kill the nightly run
            print("FAIL", name, e)

    print(len(catalog), "clips in catalog")


if __name__ == "__main__":
    main()
