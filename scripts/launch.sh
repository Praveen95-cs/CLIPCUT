#!/bin/bash
# Opens ClipCut in its own Terminal window and waits until the web page is up.
DEST="${CLIPCUT_HOME:-$HOME/ClipCut}"
URL="http://127.0.0.1:4747"

if curl -s "$URL/api/env" >/dev/null 2>&1; then
  open "$URL"; echo "RUNNING: $URL (was already running)"; exit 0
fi
[ -f "$DEST/start.command" ] || { echo "NOT_INSTALLED: run install.sh first"; exit 2; }

open -a Terminal "$DEST/start.command"
for i in $(seq 1 90); do
  if curl -s "$URL/api/env" >/dev/null 2>&1; then
    echo "RUNNING: $URL"; exit 0
  fi
  sleep 2
done
echo "TIMEOUT: server not up after 3 minutes. Check the Terminal window for errors."
exit 1
