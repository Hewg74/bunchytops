# One-off local run: catalog the already-downloaded sample clips with the real
# production analyze()/probe() from catalog.py. (The VM's cron run does this at scale.)
import glob
import json
import os

os.environ.setdefault("GOOGLE_API_KEY", open("../.env").read().split("GOOGLE_API_KEY=")[1].splitlines()[0])
os.environ.setdefault("GEMINI_VIDEO_MODEL", "gemini-flash-latest")
from google import genai  # noqa: E402

import catalog as cat  # noqa: E402

client = genai.Client()
out = {}
if os.path.exists(cat.CATALOG):
    out = json.load(open(cat.CATALOG))
for src in sorted(glob.glob("clips/*")):
    fname = os.path.basename(src)
    if fname in out:
        print("skip", fname)
        continue
    proxy = os.path.join("proxies", os.path.splitext(fname)[0] + ".mp4")
    os.makedirs("proxies", exist_ok=True)
    if not os.path.exists(proxy):
        cat.make_proxy(src, proxy)
    entry = cat.probe(src)
    entry["name"] = fname
    entry["file"] = fname
    print("analyzing", fname)
    entry["analysis"] = cat.analyze(client, proxy)
    out[fname] = entry
    cat.save_json(out, cat.CATALOG)
print(len(out), "clips cataloged;",
      sum(1 for v in out.values() if v["analysis"].get("ig_worthy")), "ig_worthy")
