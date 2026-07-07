#!/usr/bin/env bash
# One-command deploy to the Hetzner box. Run from the repo root on your PC:
#   bash pipeline/deploy.sh root@YOUR_SERVER_IP
set -euo pipefail
HOST="${1:?usage: bash pipeline/deploy.sh user@server}"
DEST=/opt/bunchytops

ssh "$HOST" "mkdir -p $DEST/audio"
scp pipeline/*.py pipeline/run.sh pipeline/README.md "$HOST:$DEST/"
scp audio/castaway.mp3 audio/northside.mp3 "$HOST:$DEST/audio/"

ssh "$HOST" bash -s <<'REMOTE'
set -e
apt-get install -y -q ffmpeg python3-pip >/dev/null
pip3 install -q --break-system-packages google-genai gdown
cd /opt/bunchytops
if [ ! -f .env ]; then
  TOKEN=$(tr -dc a-z0-9 </dev/urandom | head -c 24 || true)
  IP=$(curl -s ifconfig.me)
  cat > .env <<ENV
GOOGLE_API_KEY=PASTE_ME
REVIEW_TOKEN=$TOKEN
PUBLIC_BASE_URL=http://$IP:8037
# fill these in after creating the Meta app (see README):
#META_ACCESS_TOKEN=
#IG_USER_ID=
ENV
fi
chmod 600 .env
echo "deployed. edit /opt/bunchytops/.env, then: bash run.sh install-cron"
REMOTE
