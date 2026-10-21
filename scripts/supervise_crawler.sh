#!/bin/zsh
# Keep watch_crawler alive: restart it if it ever exits, so collection
# resumes on failure (proxy death, crash, reboot of tunnels, etc).
# Usage: supervise_crawler.sh [languages]  (default: all)
cd "$(dirname "$0")/.." || exit 1
LANGS="${1:-all}"
while true; do
  echo "$(date '+%F %T') supervisor: starting watcher for $LANGS" >> data/library/supervise.log
  python3 scripts/watch_crawler.py \
    --refresh-command "python3 scripts/refresh_us1_proxy.py" \
    --socks-file data/proxy/proxy.url \
    --languages "$LANGS" \
    --stall-seconds 300 \
    --request-rate 2 \
    --proxy-check-seconds 60 \
    >> data/library/watch.log 2>&1
  CODE=$?
  echo "$(date '+%F %T') supervisor: watcher exited code=$CODE, restarting in 15s" >> data/library/supervise.log
  sleep 15
done
