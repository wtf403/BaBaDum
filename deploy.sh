#!/usr/bin/env bash
# deploy.sh — sync BaBaDum to se1 and reload the service
set -euo pipefail

HOST="se1"
REMOTE_DIR="/var/www/babadum.xyz"
SERVICE="babadum"

echo "→ Syncing files to $HOST:$REMOTE_DIR"
rsync -az --exclude '__pycache__' --exclude '*.pyc' --exclude '*.bak' \
  --exclude 'deploy.sh' \
  --exclude '*.log' --exclude '*.tmp' \
  --exclude '/data/library/.crawler.lock' --exclude '/data/library/*.pid' \
  --exclude '/data/library/.workers/' \
  ./ "$HOST:$REMOTE_DIR/"

# Install/update the service file if it changed
echo "→ Installing $SERVICE.service"
ssh "$HOST" "
  cp $REMOTE_DIR/babadum.service /etc/systemd/system/babadum.service
  systemctl daemon-reload
"

echo "→ Restarting $SERVICE"
ssh "$HOST" "systemctl restart $SERVICE"

# Wait and verify
sleep 2
STATUS=$(ssh "$HOST" "systemctl is-active $SERVICE")
if [ "$STATUS" = "active" ]; then
  echo "✓ $SERVICE is running"
  ssh "$HOST" "curl -so /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/"
else
  echo "✗ $SERVICE failed to start — check: ssh $HOST journalctl -u $SERVICE -n 30"
  exit 1
fi
