# Bunchy Tops — automated Instagram Reel pipeline

Drive folder → Gemini analysis → cut plan → ffmpeg render → review queue → Instagram.

## How it runs (on the Hetzner box)

- **Nightly** (`run.sh catalog`): scrapes the public Drive folder, downloads new clips,
  makes 360p proxies, sends each to Gemini for timestamped moment analysis → `catalog.json`.
- **Mon/Wed/Fri morning** (`run.sh reel`): Gemini picks unused ig-worthy moments, plans a
  5–7-cut 20–28s arc + caption in the brand voice, ffmpeg renders 1080×1920 → `queue/<id>/`.
- **Always on** (`run.sh server`, systemd): the review page. Open
  `http://SERVER_IP:8037/<REVIEW_TOKEN>/list` on your phone, watch the pending reel,
  tap **post it** (publishes via Meta API) or **nah** (clips return to the pool).

## Setup

1. `bash pipeline/deploy.sh root@SERVER_IP` (from the repo root on your PC)
2. On the server, edit `/opt/bunchytops/.env`:
   - `GOOGLE_API_KEY` — mint at https://aistudio.google.com/apikey (free tier is fine)
   - Meta vars — see below
3. `bash /opt/bunchytops/run.sh catalog` once by hand (first run downloads ~160 clips; hours)
4. `bash /opt/bunchytops/run.sh install-cron`

Without `META_ACCESS_TOKEN` set, everything still works — approved reels just land in
`published/` for manual posting instead of going to Instagram.

## Meta app setup (one-time, ~10 min)

1. https://developers.facebook.com → **Create App** → type "Business".
2. Add the **Instagram Graph API** product.
3. App settings → link the Facebook **Page** connected to the band's IG Business account.
4. Graph API Explorer: generate a **Page access token** with scopes
   `instagram_basic, instagram_content_publish, pages_read_engagement`.
5. Exchange it for a long-lived token (60 days):
   `GET /oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN`
6. Get the IG user id: `GET /me/accounts` → page id → `GET /{page-id}?fields=instagram_business_account`.
7. Put both in `.env` as `META_ACCESS_TOKEN` and `IG_USER_ID`.

Token expires every 60 days — the publish call will start failing with an OAuth error;
re-run step 5 with the current token to refresh.

## Files

| file | job |
|---|---|
| `catalog.py` | sync + analyze new footage into `catalog.json` |
| `make_reel.py` | plan + render one reel into `queue/` |
| `review_server.py` | phone-friendly approve/reject page |
| `publish.py` | Meta Graph API reel publishing |
| `run.sh` | entrypoints + cron/systemd install |
| `deploy.sh` | copy everything to the server |

Local prototype scripts that produced `bunchytops_reel_prototype.mp4` live in the
session scratchpad; this directory is the production version of the same flow.
