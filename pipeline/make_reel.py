"""Generate one Instagram Reel from the catalog: Gemini plans the cuts, ffmpeg renders.

Output lands in queue/<id>/ (reel.mp4, caption.txt, plan.json) for the review server.
Tracks clip usage in posted.json so footage isn't repeated until the pool runs dry.
Env: GOOGLE_API_KEY.
"""
import json
import os
import subprocess
import time

from google import genai

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
(clip name -> metadata + timestamped moments) and the list of already-used clips.

Brand: {brand}

Plan ONE Instagram Reel. Rules:
- 5-7 cuts, 20-28s total, each cut 2.5-4.5s.
- Prefer clips NOT in the used list. Only moments the catalog marks ig_worthy.
- Build a cohesive arc: scenic/curiosity hook -> band/groove build -> a closing shot with identity
  (signage, wide band shot, or sunset). Don't jumble unrelated settings mid-arc.
- Pick an audio track and window from: {tracks}
- Write a caption in the brand voice (1-2 short lines) + 5-8 hashtags including #thebunchytops #mauimusic.

Used clips: {used}

Catalog:
{catalog}

Return STRICT JSON (no fences):
{{"cuts": [{{"clip": "IMG_1234.MOV", "start_s": 3.0, "duration_s": 3.5, "why": "..."}}],
  "audio_track": "castaway", "audio_start_s": 58,
  "caption": "...", "hashtags": ["..."], "concept": "one-line description of the arc"}}"""


def plan(catalog, used):
    client = genai.Client()
    prompt = PLAN_PROMPT.format(
        brand=BRAND, tracks=json.dumps(TRACKS), used=json.dumps(sorted(used)),
        catalog=json.dumps(catalog, indent=0))
    r = client.models.generate_content(model="gemini-3.1-pro-preview", contents=prompt)
    txt = r.text.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1].lstrip("json").strip()
    return json.loads(txt)


def render(p, out_path):
    cuts = p["cuts"]
    total = sum(c["duration_s"] for c in cuts)
    audio = os.path.join(AUDIO_DIR, TRACKS[p["audio_track"]]["file"])
    inputs, filters, vlabels = [], [], []
    for i, c in enumerate(cuts):
        inputs += ["-ss", str(c["start_s"]), "-t", str(c["duration_s"]),
                   "-i", os.path.join(CLIPS, c["clip"])]
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
    catalog = json.load(open(CATALOG))
    used = json.load(open(USED)) if os.path.exists(USED) else []
    usable = {k: v for k, v in catalog.items()
              if v.get("analysis", {}).get("ig_worthy")}
    if not usable:
        raise SystemExit("no ig_worthy clips in catalog - run catalog.py first")

    p = plan(usable, used)
    reel_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(QUEUE, reel_id)
    os.makedirs(out_dir, exist_ok=True)
    render(p, os.path.join(out_dir, "reel.mp4"))
    with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(p["caption"] + "\n\n" + " ".join(p["hashtags"]))
    json.dump(p, open(os.path.join(out_dir, "plan.json"), "w"), indent=1)
    json.dump(sorted(set(used) | {c["clip"] for c in p["cuts"]}), open(USED, "w"))
    print("queued", reel_id, "-", p["concept"])


if __name__ == "__main__":
    main()
