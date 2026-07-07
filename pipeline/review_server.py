"""Review queue: the band previews pending reels in a browser and approves or rejects.

Approve -> publishes via publish.py (if META_ACCESS_TOKEN is set) and moves to published/.
Reject -> moves to rejected/ and returns the clips to the unused pool.
Access is gated by a secret path token. Env: REVIEW_TOKEN, PORT (default 8037),
plus publish.py's vars for live posting.
"""
import json
import os
import shutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
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
<a href="/{token}/approve/{rid}" style="background:#DCA74E;color:#2B2B2B;padding:.6em 1.2em;
border-radius:6px;text-decoration:none;font-weight:bold">post it</a>
<a href="/{token}/reject/{rid}" style="color:#C16E4F;padding:.6em 1.2em">nah</a></div>"""


def pending():
    if not os.path.isdir(QUEUE):
        return []
    return sorted(d for d in os.listdir(QUEUE)
                  if os.path.exists(os.path.join(QUEUE, d, "reel.mp4")))


def return_clips_to_pool(rid):
    used_path = os.path.join(BASE, "posted.json")
    plan = json.load(open(os.path.join(QUEUE, rid, "plan.json")))
    used = set(json.load(open(used_path))) if os.path.exists(used_path) else set()
    json.dump(sorted(used - {c["clip"] for c in plan["cuts"]}), open(used_path, "w"))


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if not parts or parts[0] != TOKEN:
            self.send_error(404)
            return
        action = parts[1] if len(parts) > 1 else "list"
        rid = parts[2] if len(parts) > 2 else None
        if rid and (rid not in pending()):
            self.send_error(404)
            return

        if action == "list":
            items = "".join(ITEM.format(
                token=TOKEN, rid=r,
                caption=open(os.path.join(QUEUE, r, "caption.txt"), encoding="utf-8").read())
                for r in pending()) or "<p>nothing pending</p>"
            body = PAGE.format(items=items).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif action == "video":
            self.path = f"/queue/{rid}/reel.mp4"
            super().do_GET()
        elif action == "approve":
            caption = open(os.path.join(QUEUE, rid, "caption.txt"), encoding="utf-8").read()
            if os.environ.get("META_ACCESS_TOKEN"):
                url = f"{os.environ['PUBLIC_BASE_URL']}/{TOKEN}/video/{rid}"
                media_id = publish.publish_reel(url, caption)
                msg = f"posted (media id {media_id})"
            else:
                msg = "approved - no META_ACCESS_TOKEN set, marked ready for manual posting"
            shutil.move(os.path.join(QUEUE, rid), os.path.join(BASE, "published", rid))
            self._redirect(msg)
        elif action == "reject":
            return_clips_to_pool(rid)
            shutil.move(os.path.join(QUEUE, rid), os.path.join(BASE, "rejected", rid))
            self._redirect("rejected, clips returned to pool")
        else:
            self.send_error(404)

    def _redirect(self, msg):
        self.send_response(303)
        self.send_header("Location", f"/{TOKEN}/list?m={msg}")
        self.end_headers()


if __name__ == "__main__":
    os.chdir(BASE)
    os.makedirs(os.path.join(BASE, "published"), exist_ok=True)
    os.makedirs(os.path.join(BASE, "rejected"), exist_ok=True)
    port = int(os.environ.get("PORT", 8037))
    print(f"review queue on :{port}/{TOKEN}/list")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
