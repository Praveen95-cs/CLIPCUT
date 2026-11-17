# ClipCut — Render deployment

## Deploy
1. Put this folder in a GitHub repository.
2. In Render, create a **New Web Service** from the repository.
3. Render will detect `render.yaml` / Dockerfile.
4. Use the included persistent disk so uploaded videos and generated clips survive restarts.
5. After deployment, open the `https://...onrender.com` URL.

## Notes
- First transcription can take longer because Faster-Whisper downloads the selected model.
- The app uses FFmpeg inside the Docker image.
- This deployment is intended for a paid Render instance because video processing and Whisper can exceed free-tier memory/CPU limits.
