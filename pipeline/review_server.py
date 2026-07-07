"""Review queue: the band previews pending reels in a browser and approves or rejects.

Approve -> publishes via publish.py (if META_ACCESS_TOKEN is set) and moves to published/.
Reject -> moves to rejected/ and returns the clips to the unused pool.
State changes are POST-only (link prefetchers can't trigger them); access is gated by a
secret path token. Threaded server: Meta fetches the video from us WHILE approve blocks
polling Meta, so a single-threaded server would deadlock.
Env: REVIEW_TOKEN, PORT (default 8037), plus publish.py's vars for live posting.
"""
import html
import json
import os
import shutil
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import publish

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(BASE, "queue")
TOKEN = os.environ["REVIEW_TOKEN"]

PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Bunchy Tops - review queue</title>
<body style="font-family:sans-serif;background:#1C3738;color:#EAE3D8;max-width:420px;margin:auto;padding:1em">
<h2>pending reels</h2>{items}</body>"""
ITEM = """<div style="margin-bottom:2em;border:1px solid #7B9095;padding:1em;border-radius:8px">
<video src="/{token}/video/{rid}" controls playsinline style="width:100%;border-radius:6px"></video>
<pre style="white-space:pre-wrap">{caption}</pre>
<form method=post action="/{token}/approve/{rid}" style="display:inline">
<button style="background:#DCA74E;color:#2B2B2B;padding:.6em 1.2em;border:0;
border-radius:6px;font-weight:bold">post it</button></form>
<form method=post action="/{token}/reject/{rid}" style="display:inline">
<button style="background:none;color:#C16E4F;padding:.6em 1.2em;border:0">nah</button></form></div>"""


def pending():
    if not os.path.isdir(QUEUE):
        return []
    return sorted(d for d in os.listdir(QUEUE)
                  if os.path.exists(os.path.join(QUEUE, d, "reel.mp4")))


def return_clips_to_pool(rid):
    used_path = os.path.join(BASE, "posted.json")
    plan = json.load(open(os.path.join(QUEUE, rid, "plan.json")))
    used = json.load(open(used_path)) if os.path.exists(used_path) else []
    reel_clips = {c["clip"] for c in plan["cuts"]}
    tmp = used_path + ".tmp"
    # posted.json is an ordered list (oldest first) so the recycler can expire the oldest half
    json.dump([u for u in used if u not in reel_clips], open(tmp, "w"))
    os.replace(tmp, used_path)


class Handler(SimpleHTTPRequestHandler):
    def _route(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if not parts or parts[0] != TOKEN:
            return None, None
        action = parts[1] if len(parts) > 1 else "list"
        rid = parts[2] if len(parts) > 2 else None
        if rid is not None and rid not in pending():
            return None, None
        return action, rid

    def do_GET(self):
        action, rid = self._route()
        if action == "list":
            items = "".join(ITEM.format(
                token=TOKEN, rid=r,
                caption=html.escape(
                    open(os.path.join(QUEUE, r, "caption.txt"), encoding="utf-8").read()))
                for r in pending()) or "<p>nothing pending</p>"
            body = PAGE.format(items=items).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif action == "video" and rid:
            self.path = f"/queue/{rid}/reel.mp4"
            super().do_GET()
        else:
            self.send_error(404)

    def do_POST(self):
        action, rid = self._route()
        if action == "approve" and rid:
            caption = open(os.path.join(QUEUE, rid, "caption.txt"), encoding="utf-8").read()
            if os.environ.get("META_ACCESS_TOKEN"):
                url = f"{os.environ['PUBLIC_BASE_URL']}/{TOKEN}/video/{rid}"
                publish.publish_reel(url, caption)
            shutil.move(os.path.join(QUEUE, rid), os.path.join(BASE, "published", rid))
            self._redirect()
        elif action == "reject" and rid:
            return_clips_to_pool(rid)
            shutil.move(os.path.join(QUEUE, rid), os.path.join(BASE, "rejected", rid))
            self._redirect()
        else:
            self.send_error(404)

    def _redirect(self):
        self.send_response(303)
        self.send_header("Location", f"/{TOKEN}/list")
        self.end_headers()


if __name__ == "__main__":
    os.chdir(BASE)
    os.makedirs(os.path.join(BASE, "published"), exist_ok=True)
    os.makedirs(os.path.join(BASE, "rejected"), exist_ok=True)
    port = int(os.environ.get("PORT", 8037))
    print(f"review queue on :{port}/{TOKEN}/list")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
