"""Generate one Instagram Reel from the catalog: Gemini plans the cuts, ffmpeg renders.

The plan is validated against the catalog before ffmpeg runs — a hallucinated clip name,
out-of-range timestamp, or unknown audio track fails loudly into cron.log instead of
rendering garbage. Output lands in queue/<id>/ for the review server; clip usage is
tracked in posted.json. Env: GOOGLE_API_KEY. Optional: GEMINI_PLAN_MODEL.
"""
import json
import os
import subprocess
import time

PLAN_MODEL = os.environ.get("GEMINI_PLAN_MODEL", "gemini-3.1-pro-preview")
BASE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(BASE, "catalog.json")
USED = os.path.join(BASE, "posted.json")
QUEUE = os.path.join(BASE, "queue")
CLIPS = os.path.join(BASE, "clips")
AUDIO_DIR = os.path.join(BASE, "audio")

# hot windows from gemini-analysis.md song structure
TRACKS = {
    "castaway": {"file": "castaway.mp3", "windows": [[58, 85], [120, 150], [181, 202]]},
    "northside": {"file": "northside.mp3", "windows": [[53, 78], [117, 142], [193, 210]]},
}

BRAND = """Voice: warm, hazy, late-summer dusk; salt in your hair, bass humming in your chest.
Grounded and nostalgic, never hype. No neon-tropical cliches, no exclamation marks, lowercase-friendly.
The Bunchy Tops - six friends playing reggae-rock on Maui."""

PLAN_PROMPT = """You are the video editor for The Bunchy Tops. Below is a catalog of raw footage
(clip file -> metadata + timestamped moments) and the list of already-used clips.

Brand: {brand}

Plan ONE Instagram Reel. Rules:
- 5-7 cuts, 20-28s total, each cut 2.5-4.5s.
- Use ONLY clip files that appear as keys in the catalog. Prefer clips NOT in the used list.
- Build a cohesive arc: scenic/curiosity hook -> band/groove build -> a closing shot with identity
  (signage, wide band shot, or sunset). Don't jumble unrelated settings mid-arc.
- Pick an audio track and start second from one of the windows in: {tracks}
- Write a caption in the brand voice (1-2 short lines) + 5-8 hashtags including #thebunchytops #mauimusic.

Used clips: {used}

Catalog:
{catalog}

Return STRICT JSON (no fences):
{{"cuts": [{{"clip": "<catalog key>", "start_s": 3.0, "duration_s": 3.5, "why": "..."}}],
  "audio_track": "castaway", "audio_start_s": 58,
  "caption": "...", "hashtags": ["..."], "concept": "one-line description of the arc"}}"""


def save_json(obj, path):
    tmp = path + ".tmp"
    json.dump(obj, open(tmp, "w"))
    os.replace(tmp, path)


def plan(catalog, used):
    from google import genai  # deferred so validate()/render() import without the SDK
    client = genai.Client()
    prompt = PLAN_PROMPT.format(
        brand=BRAND, tracks=json.dumps(TRACKS), used=json.dumps(sorted(used)),
        catalog=json.dumps(catalog, indent=0))
    r = client.models.generate_content(model=PLAN_MODEL, contents=prompt)
    txt = r.text.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1].lstrip("json").strip()
    return json.loads(txt)


def validate(p, catalog):
    """Reject hallucinated clips, out-of-range cuts, unknown tracks — before ffmpeg runs."""
    if not isinstance(p, dict):
        raise ValueError(f"plan is not an object: {p!r}")
    cuts = p.get("cuts")
    if not isinstance(cuts, list) or not 3 <= len(cuts) <= 8:
        raise ValueError(f"bad cuts shape/count: {cuts!r}")
    for c in cuts:
        if not isinstance(c, dict):
            raise ValueError(f"malformed cut: {c!r}")
        meta = catalog.get(c.get("clip"))
        if meta is None:
            raise ValueError(f"clip not in catalog: {c.get('clip')!r}")
        try:
            start, dur = float(c["start_s"]), float(c["duration_s"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"malformed cut timing: {c!r}") from None
        if not (0 <= start and 1.0 <= dur <= 6.0 and start + dur <= meta["duration"] + 0.5):
            raise ValueError(f"cut out of range for {c['clip']}: {start}+{dur}s "
                             f"(clip is {meta['duration']}s)")
    total = sum(float(c["duration_s"]) for c in cuts)
    if not 12 <= total <= 35:
        raise ValueError(f"bad total duration: {total}s")
    if not isinstance(p.get("audio_track"), str) or p["audio_track"] not in TRACKS:
        raise ValueError(f"unknown audio track: {p.get('audio_track')}")
    if not isinstance(p.get("caption"), str) or not p["caption"].strip():
        raise ValueError("missing caption")


def render(p, catalog, out_path):
    cuts = p["cuts"]
    total = sum(float(c["duration_s"]) for c in cuts)
    audio = os.path.join(AUDIO_DIR, TRACKS[p["audio_track"]]["file"])
    inputs, filters, vlabels = [], [], []
    for i, c in enumerate(cuts):
        inputs += ["-ss", str(c["start_s"]), "-t", str(c["duration_s"]),
                   "-i", os.path.join(CLIPS, catalog[c["clip"]]["file"])]
        filters.append(f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                       f"crop=1080:1920,fps=30,setsar=1,format=yuv420p[v{i}]")
        vlabels.append(f"[v{i}]")
    inputs += ["-ss", str(p["audio_start_s"]), "-t", str(total), "-i", audio]
    fc = (";".join(filters) + ";" + "".join(vlabels)
          + f"concat=n={len(cuts)}:v=1:a=0[vout];"
          + f"[{len(cuts)}:a]afade=t=in:d=0.5,afade=t=out:st={total - 2}:d=2[aout]")
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs + [
        "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path], check=True)


def main():
    raw = json.load(open(CATALOG))
    used = json.load(open(USED)) if os.path.exists(USED) else []
    # key by clip file name; only clips Gemini judged usable
    catalog = {v["file"]: v for v in raw.values()
               if v.get("analysis", {}).get("ig_worthy")}
    if not catalog:
        raise SystemExit("no ig_worthy clips in catalog - run catalog.py first")

    p = plan(catalog, used)
    validate(p, catalog)
    reel_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(QUEUE, reel_id)
    os.makedirs(out_dir, exist_ok=True)
    render(p, catalog, os.path.join(out_dir, "reel.mp4"))
    with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(p["caption"] + "\n\n" + " ".join(p["hashtags"]))
    save_json(p, os.path.join(out_dir, "plan.json"))
    save_json(sorted(set(used) | {c["clip"] for c in p["cuts"]}), USED)
    print("queued", reel_id, "-", p["concept"])


if __name__ == "__main__":
    main()
