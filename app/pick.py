"""Finds the best clips in a transcript.

Engine order: Claude (through the Claude Code CLI on this Mac, using your own
Claude login) -> built-in scoring (hooks, pacing, audio energy).
"""
import json
import math
import os
import re
import shutil
import subprocess
from typing import List, Optional, Tuple

MAX_LEN = 60.0  # hard cap: no clip is ever longer than this (seconds)
LENGTHS = {"auto": (20, 58), "short": (12, 32), "medium": (28, 58), "long": (42, 59)}

HOOKS = [
    "secret", "nobody", "no one", "never", "always", "mistake", "truth", "biggest", "worst", "best",
    "crazy", "insane", "wild", "shocking", "stop", "imagine", "here's", "heres", "the reason",
    "what if", "turns out", "you need", "you should", "most people", "the problem", "i realized",
    "changed my", "million", "billion", "money", "rich", "fail", "failed", "quit", "fired", "love",
    "hate", "scared", "afraid", "story", "lesson", "rule", "number one", "first time", "honestly",
    "believe", "wrong", "hack", "trick", "simple", "easy", "hard", "win", "lost", "oh my god", "what",
    "no way", "let's go", "lets go", "clutch", "unbelievable",
]
WEAK_START = {"and", "but", "so", "because", "or", "which", "then", "also", "yeah", "um", "uh", "like", "well"}
WEAK_END = {"and", "but", "so", "because", "or", "the", "a", "to", "of", "that", "which", "is"}


def find_claude() -> Optional[str]:
    home = os.path.expanduser("~")
    extra = [
        os.path.join(home, ".local/bin"), os.path.join(home, ".claude/local"), "/opt/homebrew/bin",
        "/usr/local/bin", os.path.join(home, ".bun/bin"), os.path.join(home, ".npm-global/bin"),
    ]
    path = os.pathsep.join([os.environ.get("PATH", "")] + extra)
    return shutil.which("claude", path=path)


def sentences(words: List[dict]) -> List[dict]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end = bool(re.search(r"[.!?]$", w["w"].strip()))
        gap = (nxt["s"] - w["e"]) if nxt else 9
        if end or gap > 0.8 or len(cur) >= 40:
            out.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"].strip() for x in cur),
                        "n": len(cur)})
            cur = []
    if cur:
        out.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"].strip() for x in cur),
                    "n": len(cur)})
    return out


def _energy_at(energy: List[float], step: float, s: float, e: float) -> float:
    if not energy:
        return 0.0
    a, b = int(s / step), max(int(s / step) + 1, int(e / step))
    seg = energy[a:b]
    return sum(seg) / len(seg) if seg else 0.0


def _title(text: str) -> str:
    t = re.split(r"(?<=[.!?])\s", text.strip())[0]
    t = t.strip(" .,")
    if len(t) > 64:
        t = t[:64].rsplit(" ", 1)[0] + "…"
    return t[:1].upper() + t[1:] if t else "Clip"


def score_window(sents: List[dict], i: int, j: int, energy, step, e_mean, e_std) -> Tuple[float, dict]:
    first, last = sents[i], sents[j]
    text = " ".join(s["text"] for s in sents[i:j + 1])
    low = text.lower()
    dur = last["e"] - first["s"]
    nwords = sum(s["n"] for s in sents[i:j + 1])
    hook_txt = " ".join(s["text"] for s in sents[i:i + 2]).lower()

    hook = 0.0
    if "?" in hook_txt:
        hook += 14
    hook += min(18, 6 * sum(1 for h in HOOKS if h in hook_txt))
    if re.search(r"\b\d", hook_txt):
        hook += 5
    if re.search(r"\byou\b|\byour\b", hook_txt):
        hook += 5
    fw = re.sub(r"[^a-z]", "", first["text"].split(" ")[0].lower()) if first["text"] else ""
    if fw in WEAK_START:
        hook -= 12
    if first["n"] <= 14:
        hook += 4

    body = min(16, 2.2 * sum(1 for h in HOOKS if h in low)) + min(6, 2 * low.count("?")) + min(6, 2 * low.count("!"))
    pace = nwords / max(dur, 1)
    flow = 10 - min(10, abs(pace - 2.9) * 5)
    en = 0.0
    if e_std > 0:
        en = max(-8, min(14, 7 * (_energy_at(energy, step, first["s"], last["e"]) - e_mean) / e_std))
    lw = re.sub(r"[^a-z]", "", last["text"].split(" ")[-1].lower())
    ending = 8 if re.search(r"[.!?]$", last["text"].strip()) else 0
    if lw in WEAK_END:
        ending -= 8
    total = 34 + hook + body + flow + en + ending
    return total, {"hook": hook, "flow": flow, "energy": en, "text": text}


def _starts_clean(sents: List[dict], i: int) -> bool:
    """Clip starts at the beginning of a thought: first sentence, or previous one ended properly."""
    fw = re.sub(r"[^a-z]", "", sents[i]["text"].split(" ")[0].lower()) if sents[i]["text"] else ""
    if fw in WEAK_START:
        return False
    return i == 0 or bool(re.search(r"[.!?]$", sents[i - 1]["text"].strip())) or \
        (sents[i]["s"] - sents[i - 1]["e"]) > 1.2


def _ends_clean(sents: List[dict], j: int) -> bool:
    t = sents[j]["text"].strip()
    lw = re.sub(r"[^a-z]", "", t.split(" ")[-1].lower()) if t else ""
    if lw in WEAK_END:
        return False
    return bool(re.search(r"[.!?]$", t)) or j == len(sents) - 1 or \
        (sents[j + 1]["s"] - sents[j]["e"]) > 1.2


def _complete(sents, i, j) -> bool:
    return _starts_clean(sents, i) and _ends_clean(sents, j)


def finalize(clips: List[dict], words: List[dict], duration: float) -> List[dict]:
    """Snap every clip to whole sentences, cap at MAX_LEN, add breathing room so no word is cut."""
    if not words:
        return [c for c in clips if c["end"] - c["start"] <= MAX_LEN]
    sents = sentences(words)
    starts = [k for k in range(len(sents)) if _starts_clean(sents, k)] or list(range(len(sents)))
    out = []
    for c in clips:
        s, e = float(c["start"]), float(c["end"])
        # start: the clean sentence start nearest to s (prefer not cutting into the first line)
        i = min(starts, key=lambda k: abs(sents[k]["s"] - s) + (0.5 if sents[k]["s"] > s + 0.5 else 0))
        # end: last clean sentence end that fits before e (+ a little slack) and within MAX_LEN
        limit = min(e + 1.5, sents[i]["s"] + MAX_LEN - 0.6)
        js = [k for k in range(i, len(sents)) if sents[k]["e"] <= limit and _ends_clean(sents, k)]
        if not js:
            js = [k for k in range(i, len(sents)) if sents[k]["e"] <= sents[i]["s"] + MAX_LEN - 0.6]
        if not js:
            continue
        j = js[-1]
        if sents[j]["e"] - sents[i]["s"] < 8:
            continue
        prev_end = sents[i - 1]["e"] if i > 0 else 0.0
        next_start = sents[j + 1]["s"] if j + 1 < len(sents) else duration
        cs = max(prev_end, sents[i]["s"] - 0.15, 0.0)
        ce = min(next_start, sents[j]["e"] + 0.4, duration, cs + MAX_LEN)
        if any(not (ce <= o["start"] or cs >= o["end"]) for o in out):
            continue
        c = dict(c, start=round(cs, 2), end=round(ce, 2))
        out.append(c)
    return out


def pick_builtin(words, energy, step, duration, length="auto") -> List[dict]:
    lo, hi = LENGTHS.get(length, LENGTHS["auto"])
    e_mean = sum(energy) / len(energy) if energy else 0
    e_std = math.sqrt(sum((x - e_mean) ** 2 for x in energy) / len(energy)) if energy else 0
    cap = int(max(3, min(40, duration / 50)))
    cands = []
    if len(words) >= 40:
        sents = sentences(words)
        for i in range(len(sents)):
            for j in range(i, len(sents)):
                d = sents[j]["e"] - sents[i]["s"]
                if d > hi:
                    break
                if d >= lo:
                    if not _complete(sents, i, j):
                        continue
                    sc, info = score_window(sents, i, j, energy, step, e_mean, e_std)
                    cands.append((sc, sents[i]["s"], sents[j]["e"], info))
    if not cands:  # little or no speech (gameplay): follow the loud moments
        win = float(min(hi, max(lo, 30)))
        t = 0.0
        while t + win <= duration:
            en = _energy_at(energy, step, t, t + win)
            peak = max(energy[int(t / step):int((t + win) / step)] or [0])
            z = ((en - e_mean) / e_std if e_std else 0) + 0.5 * ((peak - e_mean) / e_std if e_std else 0)
            cands.append((50 + 12 * z, t, t + win, {"hook": 0, "flow": 0, "energy": z, "text": ""}))
            t += win / 4
    cands.sort(key=lambda c: -c[0])
    chosen = []
    for sc, s, e, info in cands:
        if len(chosen) >= cap:
            break
        if any(not (e <= cs - 1 or s >= ce + 1) for _sc, cs, ce, _i in chosen):
            continue
        chosen.append((sc, s, e, info))
    if not chosen:
        return []
    top = chosen[0][0]
    floor = min(c[0] for c in chosen)
    out = []
    for sc, s, e, info in chosen:
        rel = (sc - floor) / (top - floor) if top > floor else 1
        score = int(round(62 + 36 * rel))
        why = []
        if info["hook"] >= 14:
            why.append("strong opening hook")
        if info["energy"] >= 4 or (not info["text"] and info["energy"] > 0.8):
            why.append("high-energy audio")
        if info["flow"] >= 7:
            why.append("tight pacing")
        if not why:
            why.append("self-contained moment")
        out.append({"start": round(s, 2), "end": round(e, 2), "score": score,
                    "title": _title(info["text"]) if info["text"] else "High-energy moment",
                    "reason": ", ".join(why).capitalize() + "."})
    return out


PROMPT = """You are an expert short-form video editor (Reels / Shorts / TikTok).
Below is a timestamped transcript of a long video ({mins} minutes). Each line is `[start_seconds] text`.

Find EVERY segment that would work as a standalone viral short. Return as many as are truly good (aim for roughly {target}, fewer if the material is weak, more if it is rich). Rules:
- Each clip must be {lo}-{hi} seconds long. NEVER longer than 60 seconds.
- Only pick segments with real substance: a clear point, story, insight, opinion or punchline. Skip small talk, intros, outros, ads/sponsor reads, "as I said earlier" references and rambling.
- It must START at the beginning of a sentence and of a thought, on a strong hook (a claim, question, surprise or tension). Never start mid-sentence or with "and / but / so / because".
- It must END only after the thought is fully finished: the last sentence is complete and the point or punchline has landed. Never stop mid-sentence or mid-story. If a story needs more than 60 seconds, pick a shorter self-contained part of it instead.
- It must make sense with zero context from the rest of the video.
- Clips must not overlap.
- start must be the timestamp of the clip's first line. end must be the timestamp of the line right after the clip's last line.
- Before answering, re-read each clip's first and last line and fix any that start or end mid-thought.

Score each clip 0-100 for virality (hook strength, emotional pull, clarity, payoff, shareability). Be honest: use the full range.

Reply with ONLY a JSON array, no prose, no code fence:
[{{"start": 12.4, "end": 51.0, "score": 91, "title": "max 60 char scroll-stopping title", "reason": "one sentence on why this works"}}]

TRANSCRIPT:
{transcript}
"""


def pick_claude(words, duration, length="auto", timeout=600) -> List[dict]:
    exe = find_claude()
    if not exe:
        raise RuntimeError("Claude Code CLI not found")
    lo, hi = LENGTHS.get(length, LENGTHS["auto"])
    sents = sentences(words)
    lines = ["[%.1f] %s" % (s["s"], s["text"]) for s in sents]
    lines.append("[%.1f] (end)" % duration)
    prompt = PROMPT.format(mins=int(duration / 60) or 1, target=int(max(3, min(30, duration / 75))),
                           lo=lo, hi=hi, transcript="\n".join(lines))
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([env.get("PATH", ""), os.path.dirname(exe), "/opt/homebrew/bin", "/usr/local/bin"])
    p = subprocess.run([exe, "-p", "--output-format", "text"], input=prompt, capture_output=True,
                       text=True, timeout=timeout, env=env, cwd=os.path.expanduser("~"))
    if p.returncode != 0:
        raise RuntimeError("Claude CLI failed: " + (p.stderr or p.stdout)[-300:])
    m = re.search(r"\[.*\]", p.stdout, re.S)
    if not m:
        raise RuntimeError("Claude returned no clip list")
    raw = json.loads(m.group(0))
    out = []
    for c in raw:
        try:
            s, e = float(c["start"]), float(c["end"])
        except Exception:
            continue
        s = min((w["s"] for w in words), key=lambda x: abs(x - s))
        ends = [w["e"] for w in words if w["e"] <= e + 0.3 and w["e"] > s + 5]
        e = max(ends) if ends else e
        if e - s < 6 or e - s > MAX_LEN + 8:
            continue
        if any(not (e <= o["start"] or s >= o["end"]) for o in out):
            continue
        out.append({"start": round(s, 2), "end": round(e, 2),
                    "score": int(max(1, min(99, float(c.get("score", 70))))),
                    "title": str(c.get("title", "Clip"))[:90], "reason": str(c.get("reason", ""))[:240]})
    if not out:
        raise RuntimeError("Claude returned no usable clips")
    out.sort(key=lambda c: -c["score"])
    return out


def pick(words, energy, step, duration, length="auto", engine="auto", log=lambda m: None) -> Tuple[List[dict], str]:
    if engine in ("auto", "claude") and len(words) >= 40:
        try:
            if find_claude():
                log("Claude is reading the transcript…")
                got = finalize(pick_claude(words, duration, length), words, duration)
                if got:
                    got.sort(key=lambda c: -c["score"])
                    return got, "Claude"
                raise RuntimeError("no complete clips")
            if engine == "claude":
                log("Claude CLI not found, using built-in scoring")
        except Exception as ex:  # fall back, never fail the job on the picker
            log("Claude picker failed (%s), using built-in scoring" % str(ex)[:120])
    got = pick_builtin(words, energy, step, duration, length)
    if len(words) >= 40:
        got = finalize(got, words, duration)
    else:
        got = [dict(c, end=min(c["end"], c["start"] + MAX_LEN)) for c in got]
    return got, "Built-in scoring"
