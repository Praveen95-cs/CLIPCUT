#!/bin/bash
# ClipCut launcher — double-click, or run:  bash start.command
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$HOME/.claude/local:/opt/homebrew/bin:/usr/local/bin:$HOME/.bun/bin:$PATH"
PORT=4747

if curl -s "http://127.0.0.1:$PORT/api/env" >/dev/null 2>&1; then
  echo "ClipCut is already running."; open "http://127.0.0.1:$PORT"; exit 0
fi

PY=""
for c in python3.12 python3.11 python3.13 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3 is needed. Opening the download page — install it, then run this again."
  open "https://www.python.org/downloads/macos/"; read -r -p "Press Enter to close."; exit 1
fi

if [ ! -f .venv/ok ]; then
  echo "First run: setting up (2-4 minutes, one time only)…"
  "$PY" -m venv .venv || { echo "Could not create the Python environment."; read -r; exit 1; }
  ./.venv/bin/python -m pip install -q --upgrade pip
  ./.venv/bin/python -m pip install -q -r requirements.txt || { echo "Install failed — check your internet and run again."; read -r; exit 1; }
  ./.venv/bin/python -m pip install -q yt-dlp || echo "(YouTube links unavailable on this Python; file upload works.)"
  touch .venv/ok
fi

echo ""
echo "  ClipCut is running →  http://127.0.0.1:$PORT"
echo "  Keep this window open. Close it to stop the app."
echo ""
( sleep 2; open "http://127.0.0.1:$PORT" ) &
PORT=$PORT ./.venv/bin/python app.py
