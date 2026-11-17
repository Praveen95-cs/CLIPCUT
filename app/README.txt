ClipCut — local AI clipping studio

START
  Double-click start.command   (or in Terminal:  bash ~/Movies/ClipCut/start.command)
  First run installs everything into this folder (needs internet, a few minutes).
  The first video also downloads the speech model once (~500 MB for "Balanced").
  It opens http://127.0.0.1:4747 in your browser. Keep the Terminal window open.

USE
  1. Drop a long video (or paste a YouTube link).
  2. Wait for transcription + clip picking. Clips come back ranked by score.
  3. Click a clip to preview. Pick aspect ratio, Fill / Fit+blur, caption style
     (Simple or Dynamic, incl. Podcast Stack), colour, position, size.
     Trim with the -1s / +1s buttons (clips max 60s).
     Script & captions: see each clip's script with timestamps, click a time to jump,
     fix any wrong word and press Enter - preview and export update.
  4. Export this clip, or Export all clips. Then Download MP4 or Download all (.zip).

CLIP PICKING
  If Claude Code (the `claude` command) is installed and signed in on this Mac,
  Claude reads the transcript and picks and scores the clips with your own Claude plan.
  Otherwise the built-in scorer is used (hooks, pacing, audio energy).
  Every clip is max 60 seconds and snaps to whole sentences: it starts at the
  beginning of a thought and ends after the last sentence is finished.
  Videos with no speech (gameplay) are clipped by loudest/most intense moments.

FILES
  data/<project>/exports/   finished MP4s
  fonts/                    caption fonts (add styles in captions.py)
