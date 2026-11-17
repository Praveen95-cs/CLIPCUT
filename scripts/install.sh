#!/bin/bash
# ClipCut installer. Copies the app to ~/ClipCut and sets up its Python environment.
# Usage: bash install.sh            (safe to re-run; keeps your projects)
SRC="$(cd "$(dirname "$0")/../app" && pwd)"
DEST="${CLIPCUT_HOME:-$HOME/ClipCut}"

if [ "$(uname)" != "Darwin" ]; then
  echo "NOT_MAC: ClipCut runs on macOS only. This shell is $(uname)."
  exit 2
fi

echo "==> Copying app to $DEST"
mkdir -p "$DEST"
rsync -a --exclude data --exclude .venv "$SRC/" "$DEST/" 2>/dev/null || cp -R "$SRC/." "$DEST/"
chmod +x "$DEST/start.command"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
find_py() {
  for c in python3.12 python3.11 python3.13 python3.10 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,9) <= sys.version_info[:2] <= (3,13) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

PY="$(find_py)"
if [ -z "$PY" ] && command -v brew >/dev/null 2>&1; then
  echo "==> Python 3.9-3.13 not found. Installing python@3.12 with Homebrew"
  brew install python@3.12 && PY="$(find_py)"
fi
if [ -z "$PY" ]; then
  echo "NEED_PYTHON: Install Python 3.12 from https://www.python.org/downloads/macos/ then run this again."
  exit 3
fi
echo "==> Using $($PY --version) ($PY)"

cd "$DEST" || exit 1
if [ ! -f .venv/ok ]; then
  echo "==> Installing libraries (3-5 minutes, one time only)"
  rm -rf .venv
  "$PY" -m venv .venv || { echo "FAIL: could not create .venv"; exit 4; }
  ./.venv/bin/python -m pip install -q --upgrade pip
  ./.venv/bin/python -m pip install -q -r requirements.txt || { echo "FAIL: pip install failed (check internet)"; exit 5; }
  ./.venv/bin/python -m pip install -q yt-dlp || echo "(yt-dlp failed: YouTube links off, file upload still works)"
  ./.venv/bin/python -c "import fastapi, uvicorn, faster_whisper, cv2, PIL, numpy, imageio_ffmpeg" || { echo "FAIL: import check"; exit 6; }
  touch .venv/ok
fi
echo "INSTALLED: $DEST"
