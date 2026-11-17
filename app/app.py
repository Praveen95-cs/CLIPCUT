"""ClipCut — local AI clipping studio. Run with start.command (or: python app.py)."""
import json
import os
import queue
import re
import shutil
import threading
import time
import traceback
import uuid
import zipfile
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import media
import pick
from captions import POSITIONS, STYLES, build_groups, clip_words

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)

app = FastAPI()
app.mount("/fonts", StaticFiles(directory=os.path.join(ROOT, "fonts")), name="fonts")

JOBS = {}
LOCK = threading.Lock()
RENDER_Q = queue.Queue()
WORDS_CACHE = {}


def jdir(jid):
    return os.path.join(DATA, jid)


def save(job):
    with LOCK:
        tmp = os.path.join(jdir(job["id"]), "job.json.tmp")
        with open(tmp, "w") as f:
            json.dump(job, f)
        os.replace(tmp, os.path.join(jdir(job["id"]), "job.json"))


def load_all():
    for jid in os.listdir(DATA):
        p = os.path.join(DATA, jid, "job.json")
        if os.path.exists(p):
            try:
                with open(p) as f:
                    job = json.load(f)
                if job["status"] == "processing":
                    job["status"], job["message"] = "error", "Interrupted — the app was closed while processing."
                for r in job.get("renders", {}).values():
                    if r["status"] in ("queued", "rendering"):
                        r["status"] = "idle"
                JOBS[jid] = job
            except Exception:
                pass


def get(jid):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "Project not found")
    return job


def words_of(jid):
    if jid not in WORDS_CACHE:
        p = os.path.join(jdir(jid), "words.json")
        WORDS_CACHE[jid] = json.load(open(p)) if os.path.exists(p) else []
    return WORDS_CACHE[jid]


def slug(s):
    s = re.sub(r"[^\w\s-]", "", s).strip()
    return re.sub(r"\s+", "-", s)[:50] or "clip"


def new_job(name, settings):
    jid = uuid.uuid4().hex[:10]
    os.makedirs(os.path.join(jdir(jid), "exports"), exist_ok=True)
    job = {"id": jid, "name": name, "created": time.time(), "status": "processing", "stage": "upload",
           "progress": 0.0, "message": "Starting…", "settings": settings, "meta": {}, "clips": [],
           "renders": {}, "engine": "", "source": "", "log": []}
    JOBS[jid] = job
    return job


def analyze(job):
    jid = job["id"]
    d = jdir(jid)
    src = os.path.join(d, job["source"])
    st = job["settings"]

    def step(stage, msg, prog=0.0):
        job["stage"], job["message"], job["progress"] = stage, msg, prog

    try:
        step("probe", "Reading video…")
        meta = media.probe(src)
        if not meta["has_video"]:
            raise RuntimeError("No video track found in this file.")
        job["meta"] = meta
        words, en = [], []
        wav = os.path.join(d, "audio.wav")
        if meta["has_audio"]:
            step("audio", "Extracting audio…")
            media.extract_audio(src, wav)
            en = media.energy(wav, 0.5)
            step("transcribe", "Transcribing speech (first run downloads the speech model)…")

            def prog(p):
                job["progress"] = p
                job["message"] = "Transcribing speech… %d%%" % int(p * 100)

            words = media.transcribe(wav, st.get("model", "small"), st.get("language") or None,
                                     meta["duration"], prog)
        with open(os.path.join(d, "words.json"), "w") as f:
            json.dump(words, f)
        WORDS_CACHE[jid] = words
        job["word_count"] = len(words)

        step("pick", "Finding the best moments…")

        def log(m):
            job["message"] = m
            job["log"].append(m)

        clips, engine = pick.pick(words, en, 0.5, meta["duration"], st.get("length", "auto"),
                                  st.get("engine", "auto"), log)
        job["engine"] = engine
        step("frame", "Framing speakers…")
        wide = meta["width"] > meta["height"]
        out = []
        for i, c in enumerate(clips):
            c["id"] = "c%02d" % (i + 1)
            c["cx"] = media.face_center(src, c["start"], c["end"], meta) if wide else 0.5
            c["text"] = " ".join(w["w"] for w in clip_words(words, c["start"], c["end"]))[:600]
            out.append(c)
            job["progress"] = (i + 1) / max(1, len(clips))
        out.sort(key=lambda c: -c["score"])
        job["clips"] = out
        if os.path.exists(wav):
            os.remove(wav)
        job["status"], job["stage"], job["progress"] = "ready", "done", 1.0
        job["message"] = "%d clips found" % len(out)
    except Exception as ex:
        traceback.print_exc()
        job["status"] = "error"
        msg = str(ex)
        if "faster_whisper" in msg or "No module" in msg:
            msg = "Speech model is not installed. Close the app and run start.command again."
        job["message"] = msg[:400]
    save(job)


def render_worker():
    while True:
        jid, cid, opts = RENDER_Q.get()
        job = JOBS.get(jid)
        if not job:
            continue
        r = job["renders"].get(cid)
        clip = next((c for c in job["clips"] if c["id"] == cid), None)
        if not r or not clip or r.get("token") != opts["_token"]:
            continue
        try:
            r["status"], r["progress"] = "rendering", 0.0
            o = dict(opts)
            o["cx"] = clip.get("cx", 0.5)
            name = "%s_%s_%s.mp4" % (cid, slug(clip["title"]), o["aspect"].replace(":", "x"))
            outp = os.path.join(jdir(jid), "exports", name)
            for old in os.listdir(os.path.dirname(outp)):
                if old.startswith(cid + "_"):
                    os.remove(os.path.join(os.path.dirname(outp), old))

            def prog(p):
                r["progress"] = p

            media.render_clip(os.path.join(jdir(jid), job["source"]), outp, job["meta"], words_of(jid),
                              clip["start"], clip["end"], o, prog)
            r.update(status="done", progress=1.0, file=name, size=os.path.getsize(outp))
        except Exception as ex:
            traceback.print_exc()
            r.update(status="error", error=str(ex)[:300])
        save(job)


# ------------------------------------------------------------------ routes

@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-store"})


@app.get("/api/env")
def env():
    try:
        import faster_whisper  # noqa
        whisper = True
    except Exception:
        whisper = False
    return {"claude": bool(pick.find_claude()), "whisper": whisper, "styles": STYLES, "positions": POSITIONS,
            "aspects": media.ASPECTS}


def public(job, full=True):
    keys = ["id", "name", "created", "status", "stage", "progress", "message", "meta", "engine", "settings",
            "word_count"]
    out = {k: job.get(k) for k in keys}
    out["clip_count"] = len(job["clips"])
    if full:
        out["clips"] = job["clips"]
        out["renders"] = {k: {x: v[x] for x in v if x != "token"} for k, v in job["renders"].items()}
    return out


@app.get("/api/jobs")
def jobs():
    return sorted([public(j, False) for j in JOBS.values()], key=lambda j: -j["created"])


@app.get("/api/jobs/{jid}")
def job_get(jid: str):
    return public(get(jid))


@app.put("/api/upload")
async def upload(request: Request, name: str, model: str = "small", language: str = "", length: str = "auto",
                 engine: str = "auto"):
    ext = os.path.splitext(name)[1].lower() or ".mp4"
    if ext not in (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"):
        raise HTTPException(400, "Unsupported file type")
    job = new_job(os.path.splitext(name)[0], {"model": model, "language": language, "length": length,
                                             "engine": engine})
    job["source"] = "source" + ext
    with open(os.path.join(jdir(job["id"]), job["source"]), "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    save(job)
    threading.Thread(target=analyze, args=(job,), daemon=True).start()
    return {"id": job["id"]}


@app.post("/api/youtube")
async def youtube(request: Request):
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "Paste a full video link")
    job = new_job("YouTube video", body.get("settings") or {})
    job["stage"], job["message"] = "download", "Downloading video…"

    def run():
        try:
            import yt_dlp

            def hook(d):
                tot = d.get("total_bytes") or d.get("total_bytes_estimate")
                if d.get("status") == "downloading" and tot:
                    job["progress"] = d.get("downloaded_bytes", 0) / max(1, tot)

            opts = {"outtmpl": os.path.join(jdir(job["id"]), "source.%(ext)s"), "quiet": True, "noprogress": True,
                    "format": "bv*[height<=1080][vcodec^=avc]+ba[ext=m4a]/b[ext=mp4]/b",
                    "merge_output_format": "mp4", "ffmpeg_location": media.ffmpeg(), "progress_hooks": [hook],
                    "noplaylist": True}
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=True)
            job["name"] = (info.get("title") or "YouTube video")[:120]
            files = [f for f in os.listdir(jdir(job["id"])) if f.startswith("source.")]
            if not files:
                raise RuntimeError("Download produced no file")
            job["source"] = files[0]
            save(job)
            analyze(job)
        except Exception as ex:
            job["status"], job["message"] = "error", ("Download failed: " + str(ex))[:400]
            save(job)

    threading.Thread(target=run, daemon=True).start()
    return {"id": job["id"]}


@app.get("/media/{jid}/source")
def source(jid: str):
    job = get(jid)
    return FileResponse(os.path.join(jdir(jid), job["source"]))


@app.post("/api/jobs/{jid}/groups")
async def groups(jid: str, request: Request):
    b = await request.json()
    get(jid)
    st = STYLES.get(b.get("style"))
    if not st:
        return []
    return build_groups(clip_words(words_of(jid), float(b["start"]), float(b["end"])), st)


def _clip_lines(words, start, end):
    """Editable script lines (sentences, max ~12 words) for a clip, with word indices."""
    idx = [i for i, w in enumerate(words) if start <= (w["s"] + w["e"]) / 2 <= end]
    lines, cur = [], []
    for k, i in enumerate(idx):
        cur.append(i)
        w = words[i]
        nxt = words[idx[k + 1]] if k + 1 < len(idx) else None
        if re.search(r"[.!?]$", w["w"].strip()) or (nxt and nxt["s"] - w["e"] > 0.8) or len(cur) >= 12 or not nxt:
            lines.append({"a": cur[0], "b": cur[-1], "t": round(max(0.0, words[cur[0]]["s"] - start), 2),
                          "e": round(words[cur[-1]]["e"] - start, 2),
                          "text": " ".join(words[j]["w"].strip() for j in cur)})
            cur = []
    return lines


@app.post("/api/jobs/{jid}/script")
async def script_get(jid: str, request: Request):
    b = await request.json()
    get(jid)
    return _clip_lines(words_of(jid), float(b["start"]), float(b["end"]))


@app.post("/api/jobs/{jid}/script/edit")
async def script_edit(jid: str, request: Request):
    """Replace words a..b with the edited text; timing is spread over the same span."""
    b = await request.json()
    job = get(jid)
    words = words_of(jid)
    a, z = int(b["a"]), int(b["b"])
    if not (0 <= a <= z < len(words)):
        raise HTTPException(400, "Line no longer matches the transcript, reload the clip")
    toks = [t for t in str(b.get("text", "")).split() if t]
    s0, e0 = words[a]["s"], words[z]["e"]
    new = []
    if toks:
        tot = sum(len(t) + 1 for t in toks)
        t = s0
        for tok in toks:
            d = (e0 - s0) * (len(tok) + 1) / tot
            new.append({"w": " " + tok, "s": round(t, 3), "e": round(t + d * 0.92, 3)})
            t += d
    words[a:z + 1] = new
    WORDS_CACHE[jid] = words
    with open(os.path.join(jdir(jid), "words.json"), "w") as f:
        json.dump(words, f)
    for c in job.get("clips", []):
        c["text"] = " ".join(w["w"].strip() for w in clip_words(words, c["start"], c["end"]))[:600]
    save(job)
    return {"ok": True}


@app.post("/api/jobs/{jid}/clips/{cid}")
async def clip_update(jid: str, cid: str, request: Request):
    job = get(jid)
    b = await request.json()
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip:
        raise HTTPException(404, "Clip not found")
    dur = job["meta"]["duration"]
    if "start" in b or "end" in b:
        s = max(0.0, min(float(b.get("start", clip["start"])), dur - 1))
        e = max(s + 1, min(float(b.get("end", clip["end"])), dur, s + pick.MAX_LEN))
        clip["start"], clip["end"] = round(s, 2), round(e, 2)
        clip["text"] = " ".join(w["w"] for w in clip_words(words_of(jid), s, e))[:600]
    if "title" in b:
        clip["title"] = str(b["title"])[:120]
    if "cx" in b:
        clip["cx"] = max(0.0, min(1.0, float(b["cx"])))
    save(job)
    return clip


@app.post("/api/jobs/{jid}/render")
async def render(jid: str, request: Request):
    job = get(jid)
    b = await request.json()
    opts = b.get("options") or {}
    if opts.get("aspect") not in media.ASPECTS:
        opts["aspect"] = "9:16"
    for cid in b.get("clips") or []:
        if not any(c["id"] == cid for c in job["clips"]):
            continue
        token = uuid.uuid4().hex
        job["renders"][cid] = {"status": "queued", "progress": 0.0, "token": token, "aspect": opts["aspect"]}
        RENDER_Q.put((jid, cid, dict(opts, _token=token)))
    return {"ok": True}


@app.get("/api/jobs/{jid}/download/{cid}")
def download(jid: str, cid: str):
    job = get(jid)
    r = job["renders"].get(cid)
    if not r or r.get("status") != "done":
        raise HTTPException(404, "Not rendered yet")
    return FileResponse(os.path.join(jdir(jid), "exports", r["file"]), filename=r["file"], media_type="video/mp4")


@app.get("/api/jobs/{jid}/zip")
def zip_all(jid: str):
    job = get(jid)
    files = [r["file"] for r in job["renders"].values() if r.get("status") == "done"]
    if not files:
        raise HTTPException(404, "Nothing exported yet")
    zp = os.path.join(jdir(jid), "clips.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(os.path.join(jdir(jid), "exports", f), f)
    return FileResponse(zp, filename=slug(job["name"]) + "-clips.zip", media_type="application/zip")


@app.delete("/api/jobs/{jid}")
def delete(jid: str):
    job = get(jid)
    if job["status"] == "processing":
        raise HTTPException(400, "Still processing")
    JOBS.pop(jid, None)
    WORDS_CACHE.pop(jid, None)
    shutil.rmtree(jdir(jid), ignore_errors=True)
    return {"ok": True}


@app.exception_handler(Exception)
async def on_error(_req, exc):
    return JSONResponse({"detail": str(exc)[:300]}, status_code=500)


load_all()
threading.Thread(target=render_worker, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "4747")), log_level="warning")
