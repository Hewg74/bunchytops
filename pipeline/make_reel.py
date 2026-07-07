"""Generate one Instagram Reel from the catalog: Gemini plans the cuts, ffmpeg renders.

Style layer ("sauce"): cut durations snap to the song's beat grid, two templates
(cinematic: crossfades + slow push-in / punchy: hard beat cuts + faster punch-in),
a warm brand color grade, and an optional hook-text overlay (drawtext via textfile,
so caption text can't inject into the filtergraph).

The plan is validated against the catalog before ffmpeg runs — a hallucinated clip name,
out-of-range timestamp, or unknown audio track fails loudly into cron.log instead of
rendering garbage. When the unused pool runs low, the oldest half of the used list is
recycled so generation never starves. Output lands in queue/<id>/ for the review server.
Env: GOOGLE_API_KEY. Optional: GEMINI_PLAN_MODEL, REEL_FONT.
Usage: python make_reel.py [cinematic|punchy]   (template override for testing)
"""
import json
import os
import subprocess
import sys
import time

PLAN_MODEL = os.environ.get("GEMINI_PLAN_MODEL", "gemini-3.1-pro-preview")
BASE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(BASE, "catalog.json")
USED = os.path.join(BASE, "posted.json")
QUEUE = os.path.join(BASE, "queue")
CLIPS = os.path.join(BASE, "clips")
AUDIO_DIR = os.path.join(BASE, "audio")

# hot windows + tempo from gemini-analysis.md
TRACKS = {
    "castaway": {"file": "castaway.mp3", "bpm": 100,
                 "windows": [[58, 85], [120, 150], [181, 202]]},
    "northside": {"file": "northside.mp3", "bpm": 86,
                  "windows": [[53, 78], [117, 142], [193, 210]]},
}

# push-in speed per frame; crossfade seconds (0 = hard cuts)
TEMPLATES = {
    "cinematic": {"zoom_rate": 0.0005, "xfade": 0.4},
    "punchy": {"zoom_rate": 0.0012, "xfade": 0.0},
}

GRADE = "colorbalance=rm=0.05:bm=-0.05,eq=saturation=0.9:gamma=1.02"  # warm, slightly desaturated

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
- Pick a template: "cinematic" (dreamy, crossfades, landscape-heavy) or "punchy"
  (hard beat cuts, performance-energy-heavy). Match it to the footage you chose.
- Optionally add hook_text: <=6 lowercase words overlaid on the first shot that make a
  scroller stop ("reggae rock from the north side", "made on maui"). Omit if the opening
  shot speaks for itself.
- Write a caption in the brand voice (1-2 short lines) + 5-8 hashtags including #thebunchytops #mauimusic.

Used clips: {used}

Catalog:
{catalog}

Return STRICT JSON (no fences):
{{"cuts": [{{"clip": "<catalog key>", "start_s": 3.0, "duration_s": 3.5, "why": "..."}}],
  "audio_track": "castaway", "audio_start_s": 58, "template": "cinematic",
  "hook_text": "made on maui", "caption": "...", "hashtags": ["..."],
  "concept": "one-line description of the arc"}}"""


def save_json(obj, path):
    tmp = path + ".tmp"
    json.dump(obj, open(tmp, "w"))
    os.replace(tmp, path)


def default_font():
    if os.environ.get("REEL_FONT"):
        return os.environ["REEL_FONT"]
    if os.name == "nt":
        return "C:/Windows/Fonts/arialbd.ttf"
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def plan(catalog, used):
    from google import genai  # deferred so validate()/render() import without the SDK
    client = genai.Client()
    prompt = PLAN_PROMPT.format(
        brand=BRAND, tracks=json.dumps(TRACKS), used=json.dumps(used),
        catalog=json.dumps(catalog, indent=0))
    r = client.models.generate_content(model=PLAN_MODEL, contents=prompt)
    txt = r.text.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1].lstrip("json").strip()
    return json.loads(txt)


def snap_to_beats(p, catalog):
    """Quantize each cut to a whole number of beats (4-8) so cuts land on the groove."""
    beat = 60.0 / TRACKS[p["audio_track"]]["bpm"]
    for c in p["cuts"]:
        n = max(4, min(8, round(float(c["duration_s"]) / beat)))
        dur = round(n * beat, 3)
        max_dur = catalog[c["clip"]]["duration"] - float(c["start_s"])
        while n > 4 and dur > max_dur:  # shrink rather than run past clip end
            n -= 1
            dur = round(n * beat, 3)
        c["duration_s"] = dur


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
    if p.get("template", "cinematic") not in TEMPLATES:
        raise ValueError(f"unknown template: {p.get('template')!r}")
    hook = p.get("hook_text")
    if hook is not None and not (isinstance(hook, str) and 0 < len(hook) <= 48):
        raise ValueError(f"bad hook_text: {hook!r}")
    if not isinstance(p.get("caption"), str) or not p["caption"].strip():
        raise ValueError("missing caption")


def render(p, catalog, out_dir):
    cuts = p["cuts"]
    tpl = TEMPLATES[p.get("template", "cinematic")]
    xf = tpl["xfade"]
    durs = [float(c["duration_s"]) for c in cuts]
    total = sum(durs) - xf * (len(cuts) - 1)  # crossfades overlap, shortening the reel
    audio = os.path.join(AUDIO_DIR, TRACKS[p["audio_track"]]["file"])

    inputs, filters, vlabels = [], [], []
    for i, c in enumerate(cuts):
        inputs += ["-ss", str(c["start_s"]), "-t", str(c["duration_s"]),
                   "-i", os.path.join(CLIPS, catalog[c["clip"]]["file"])]
        filters.append(
            f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,fps=30,setsar=1,"
            f"zoompan=z='min(1+{tpl['zoom_rate']}*in,1.12)'"
            f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=1080x1920:fps=30,"
            f"{GRADE},format=yuv420p[v{i}]")
        vlabels.append(f"[v{i}]")
    inputs += ["-ss", str(p["audio_start_s"]), "-t", str(total), "-i", audio]

    if xf > 0 and len(cuts) > 1:  # crossfade chain
        chain, prev, elapsed = [], "v0", durs[0]
        for i in range(1, len(cuts)):
            nxt = f"x{i}" if i < len(cuts) - 1 else "vcat"
            chain.append(f"[{prev}][v{i}]xfade=transition=fade:duration={xf}"
                         f":offset={round(elapsed - xf, 3)}[{nxt}]")
            elapsed += durs[i] - xf
            prev = nxt
        concat = ";".join(chain)
    else:  # hard cuts
        concat = "".join(vlabels) + f"concat=n={len(cuts)}:v=1:a=0[vcat]"

    post = "null"
    if p.get("hook_text"):
        hook_file = os.path.join(out_dir, "hook.txt")
        with open(hook_file, "w", encoding="utf-8") as f:
            f.write(" ".join(p["hook_text"].split()))
        font = default_font().replace("\\", "/").replace(":", "\\:")
        hook_path = hook_file.replace("\\", "/").replace(":", "\\:")
        post = (f"drawtext=textfile='{hook_path}':fontfile='{font}':fontsize=58"
                f":fontcolor=0xEAE3D8:shadowx=2:shadowy=2:shadowcolor=0x2B2B2B@0.7"
                f":x=(w-text_w)/2:y=h*0.14:enable='lt(t,2.6)'")

    fc = (";".join(filters) + ";" + concat + f";[vcat]{post}[vout];"
          f"[{len(cuts)}:a]afade=t=in:d=0.5,afade=t=out:st={total - 2}:d=2[aout]")
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs + [
        "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        os.path.join(out_dir, "reel.mp4")], check=True)


def main():
    raw = json.load(open(CATALOG))
    used = json.load(open(USED)) if os.path.exists(USED) else []
    catalog = {v["file"]: v for v in raw.values()
               if v.get("analysis", {}).get("ig_worthy")}
    if not catalog:
        raise SystemExit("no ig_worthy clips in catalog - run catalog.py first")
    if len([k for k in catalog if k not in used]) < 10 and used:
        used = used[len(used) // 2:]  # recycle: unlock the oldest half of the pool

    p = plan(catalog, used)
    if len(sys.argv) > 1:  # template override for testing
        p["template"] = sys.argv[1]
    snap_to_beats(p, catalog)
    validate(p, catalog)
    reel_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(QUEUE, reel_id)
    os.makedirs(out_dir, exist_ok=True)
    render(p, catalog, out_dir)
    with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(p["caption"] + "\n\n" + " ".join(p["hashtags"]))
    save_json(p, os.path.join(out_dir, "plan.json"))
    save_json(used + [c["clip"] for c in p["cuts"] if c["clip"] not in used], USED)
    print("queued", reel_id, "-", p.get("template"), "-", p["concept"])


if __name__ == "__main__":
    main()
