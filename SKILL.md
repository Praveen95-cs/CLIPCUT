---
name: clipcut
description: Install and launch ClipCut, a free local AI clipping studio for Mac (long video in, ranked captioned 9:16 short clips out). Use when the user says "install ClipCut", "set up ClipCut", "open/launch/start ClipCut", "run the clipping app", or wants to turn a long video or podcast into short clips with ClipCut.
---

# ClipCut — install and launch

ClipCut is a local web app. It runs on the user's Mac at http://127.0.0.1:4747.
This skill folder contains the full app (`app/`) and two scripts (`scripts/install.sh`, `scripts/launch.sh`).
`<skill_dir>` below means the folder this SKILL.md is in.

## 1. Check where you are running

Run `uname` in your shell.

- **Darwin (macOS)**: this is the user's Mac (Claude Code / Claude desktop Code tab). Continue to step 2.
- **Anything else** (for example Linux on claude.ai web): you cannot install apps on the user's Mac from here.
  Do not try. Tell the user, in 2-3 short lines:
  "ClipCut runs on your Mac. Open the Claude desktop app, go to the **Code** tab, pick any folder,
  and type **Install ClipCut**. (Or run `claude` in Terminal and type the same.)"
  Stop there.

## 2. Install (skip if already installed)

If `~/ClipCut/.venv/ok` exists and the user only asked to open it, go to step 3.

Otherwise run, with a long timeout (up to 10 minutes; the first install downloads ~400 MB of libraries):

```bash
bash "<skill_dir>/scripts/install.sh"
```

Read the last line:
- `INSTALLED: ...` → go to step 3.
- `NEED_PYTHON` → tell the user to install Python 3.12 from https://www.python.org/downloads/macos/ (the macOS 64-bit universal installer), then say "Install ClipCut" again. Stop.
- `NOT_MAC` → see step 1.
- `FAIL: ...` → show the error line, fix if obvious (internet, disk space), re-run once.

The script copies the app to `~/ClipCut` and never touches `~/ClipCut/data` (the user's projects), so re-running it is safe and also updates the app.

## 3. Launch

```bash
bash "<skill_dir>/scripts/launch.sh"
```

This opens ClipCut in its own Terminal window (so it keeps running after this chat ends) and waits until it answers.
On `RUNNING: http://127.0.0.1:4747` the browser opens automatically.

## 4. Tell the user (short)

- ClipCut is open at http://127.0.0.1:4747. Keep the Terminal window open; closing it stops the app.
- Drop a downloaded video file (better than a YouTube link: links often get blocked or come in low quality).
- The first video downloads the speech model once (~500 MB), so it is slower.
- Next time: say "Open ClipCut", or double-click `start.command` in the ClipCut folder in their home folder.

## Notes

- Clips are picked by Claude when the `claude` command (Claude Code) is installed and signed in on the Mac; otherwise by the built-in scorer. Both work.
- Mac only (Apple silicon or Intel). Needs about 2 GB free disk space.
- Port 4747. If something else uses it, `start.command` reports it in the Terminal window.
- If `<skill_dir>/app` is missing (skill synced without files), ask the user for the `clipcut-skill.zip` path, unzip it to a temp folder, and run `scripts/install.sh` from there.
