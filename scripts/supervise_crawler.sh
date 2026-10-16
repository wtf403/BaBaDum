#!/bin/zsh
# Keep watch_crawler alive: restart it if it ever exits, so collection
# resumes on failure (proxy death, crash, reboot of tunnels, etc).
# Usage: supervise_crawler.sh [languages]  (default: fr,ru,us,gb)
cd "$(dirname "$0")/.." || exit 1
LANGS="${1:-fr,ru,us,gb}"
NWORKERS=$(echo "$LANGS" | tr ',' '\n' | wc -l | tr -d ' ')
while true; do
  echo "$(date '+%F %T') supervisor: starting watcher for $LANGS" >> data/library/supervise.log
  python3 scripts/watch_crawler.py \
    --refresh-command /tmp/babadum-proxy-rotate.py \
    --socks-file /tmp/babadum-proxy.url \
    --languages "$LANGS" \
    --stall-seconds 300 \
    --proxy-check-seconds 60 \
    >> data/library/watch.log 2>&1
  CODE=$?
  echo "$(date '+%F %T') supervisor: watcher exited code=$CODE, restarting in 15s" >> data/library/supervise.log
  sleep 15
done
