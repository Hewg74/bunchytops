#!/usr/bin/env bash
# Pipeline entrypoints. Usage: bash run.sh [catalog|reel|server|install-cron]
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a

case "${1:-}" in
  catalog) python3 catalog.py ;;
  reel)    python3 make_reel.py ;;
  server)  python3 review_server.py ;;
  install-cron)
    ( crontab -l 2>/dev/null | grep -v bunchytops || true
      # nightly sync+catalog at 3:41, new reel Mon/Wed/Fri morning
      echo "41 3 * * * bash /opt/bunchytops/run.sh catalog >> /opt/bunchytops/cron.log 2>&1"
      echo "17 8 * * 1,3,5 bash /opt/bunchytops/run.sh reel >> /opt/bunchytops/cron.log 2>&1"
    ) | crontab -
    # review server as a systemd unit so it survives reboots
    cat > /etc/systemd/system/bunchytops-review.service <<UNIT
[Unit]
Description=Bunchy Tops reel review queue
After=network.target
[Service]
ExecStart=/usr/bin/bash /opt/bunchytops/run.sh server
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable --now bunchytops-review
    echo "cron + review server installed"
    ;;
  *) echo "usage: bash run.sh [catalog|reel|server|install-cron]"; exit 1 ;;
esac
