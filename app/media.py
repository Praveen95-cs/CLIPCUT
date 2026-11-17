"""ffmpeg helpers: probe, audio, energy, transcription, face centring, rendering."""
import math
import os
import re
import shutil
import subprocess
import wave
from typing import Callable, List, Optional

import numpy as np

from captions import STYLES, CaptionRenderer, build_groups, clip_words

ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}
FPS = 30
_ffmpeg = None


def ffmpeg() -> str:
    global _ffmpeg
    if _ffmpeg:
        return _ffmpeg
    path = os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"])
    exe = shutil.which("ffmpeg", path=path)
    if not exe:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    _ffmpeg = exe
    return exe


def probe(path: str) -> dict:
    p = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace")
    err = p.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise RuntimeError("This file could not be read as a video.")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    v = re.search(r"Stream #.*Video:.*?[, ](\d{2,5})x(\d{2,5})", err)
    w, h = (int(v.group(1)), int(v.group(2))) if v else (0, 0)
    rot = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", err)
    if rot and abs(abs(float(rot.group(1))) - 90) < 1:
        w, h = h, w
    return {"duration": dur, "width": w, "height": h, "has_audio": bool(re.search(r"Stream #.*Audio:", err)),
            "has_video": bool(v)}


def extract_audio(src: str, wav: str):
    subprocess.run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", "1",
                    "-ar", "16000", "-c:a", "pcm_s16le", wav], check=True)


def energy(wav: str, step: float = 0.5) -> List[float]:
    out = []
    with wave.open(wav, "rb") as f:
        n = int(f.getframerate() * step)
        while True:
            buf = f.readframes(n)
            if not buf:
                break
            a = np.frombuffer(buf, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(a * a))) if len(a) else 0.0
            out.append(round(20 * math.log10(max(rms, 1.0)), 2))
    return out


def transcribe(wav: str, model: str, language: Optional[str], duration: float,
               progress: Callable[[float], None]) -> List[dict]:
    from faster_whisper import WhisperModel
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _info = wm.transcribe(wav, language=language or None, word_timestamps=True, vad_filter=True,
                                beam_size=3, condition_on_previous_text=False)
    words = []
    for s in segs:
        for w in (s.words or []):
            t = w.word.strip()
            if t:
                words.append({"w": t, "s": round(float(w.start), 3), "e": round(float(w.end), 3)})
        progress(min(1.0, s.end / max(duration, 1)))
    return words


def face_center(src: str, start: float, end: float, meta: dict) -> float:
    """Horizontal centre (0..1) of the main face in the clip; 0.5 if none found."""
    try:
        import cv2
        w, h = meta["width"], meta["height"]
        if not w or not h:
            return 0.5
        sw = 480
        sh = int(h * sw / w) // 2 * 2
        casc = cv2.CascadeClassifier(os.path.join(os.path.dirname(os.path.abspath(__file__)), "face.xml"))
        if casc.empty():
            return 0.5
        xs = []
        n = 6
        for i in range(n):
            t = start + (end - start) * (i + 0.5) / n
            p = subprocess.run([ffmpeg(), "-loglevel", "error", "-ss", "%.2f" % t, "-i", src, "-frames:v", "1",
                                "-vf", "scale=%d:%d" % (sw, sh), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                               capture_output=True, timeout=60)
            if len(p.stdout) != sw * sh:
                continue
            img = np.frombuffer(p.stdout, dtype=np.uint8).reshape(sh, sw)
            faces = casc.detectMultiScale(img, scaleFactor=1.15, minNeighbors=6, minSize=(36, 36))
            if len(faces):
                x, _y, fw, _fh = max(faces, key=lambda f: f[2] * f[3])
                xs.append((x + fw / 2) / sw)
        if len(xs) >= 2:
            return round(float(np.median(xs)), 3)
    except Exception:
        pass
    return 0.5


def crop_x(meta: dict, W: int, H: int, cx: float) -> float:
    """Fraction (0..1) for the crop offset so that the point cx is centred."""
    sw, sh = meta["width"], meta["height"]
    if not sw or not sh:
        return 0.5
    scale = max(W / sw, H / sh)
    full = sw * scale
    if full <= W + 1:
        return 0.5
    x = cx * full - W / 2
    return float(min(1.0, max(0.0, x / (full - W))))


def render_clip(src: str, out: str, meta: dict, words: List[dict], start: float, end: float, opts: dict,
                progress: Callable[[float], None], cancelled: Callable[[], bool] = lambda: False):
    W, H = ASPECTS.get(opts.get("aspect", "9:16"), ASPECTS["9:16"])
    dur = max(0.5, end - start)
    layout = opts.get("layout", "fill")
    style_id = opts.get("style", "none")
    if layout == "fit":
        vf = ("[0:v]fps=%d,split[a][b];"
              "[a]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=12:3,"
              "eq=brightness=-0.12,scale=%d:%d[bg];"
              "[b]scale=%d:%d:force_original_aspect_ratio=decrease[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]") % (
                  FPS, W // 4, H // 4, W // 4, H // 4, W, H, W, H)
    else:
        fx = crop_x(meta, W, H, float(opts.get("cx", 0.5)))
        vf = ("[0:v]fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,"
              "crop=%d:%d:(iw-%d)*%.4f:(ih-%d)/2,setsar=1[base]") % (FPS, W, H, W, H, W, fx, H)

    rend = None
    if style_id in STYLES:
        groups = build_groups(clip_words(words, start, end), STYLES[style_id])
        if groups:
            rend = CaptionRenderer(groups, style_id, W, H, accent=opts.get("accent", "#FFE600"),
                                   position=opts.get("position", "bottom"), scale=float(opts.get("scale", 1.0)))
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", "%.3f" % start, "-t", "%.3f" % dur,
           "-i", src]
    if rend:
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", "%dx%d" % (W, rend.strip_h), "-r", str(FPS), "-i", "-"]
        vf += ";[base][1:v]overlay=0:%d:eof_action=pass,format=yuv420p[v]" % rend.strip_y
    else:
        vf += ";[base]format=yuv420p[v]"
    cmd += ["-filter_complex", vf, "-map", "[v]", "-map", "0:a?", "-t", "%.3f" % dur, "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", out]
    log = open(out + ".log", "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if rend else subprocess.DEVNULL, stderr=log)
    try:
        if rend:
            n = int(math.ceil(dur * FPS))
            for i in range(n):
                if cancelled():
                    proc.kill()
                    raise RuntimeError("cancelled")
                try:
                    proc.stdin.write(rend.frame(i / FPS))
                except BrokenPipeError:
                    break
                if i % 15 == 0:
                    progress(i / n)
            try:
                proc.stdin.close()
            except Exception:
                pass
        code = proc.wait()
    finally:
        log.close()
    if code != 0 or not os.path.exists(out):
        with open(out + ".log", "r", errors="replace") as f:
            raise RuntimeError("ffmpeg failed: " + f.read()[-400:])
    os.remove(out + ".log")
    progress(1.0)
