"""Caption styles, word grouping and the Pillow caption renderer.

The same STYLES dict drives the browser preview (CSS) and the final render
(Pillow frames piped into ffmpeg), so what you see is what you export.
"""
import os
import re
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# size / emph_scale are fractions of the output width.
STYLES: Dict[str, dict] = {
    "clean": dict(
        name="Clean", kind="simple", font="Poppins-Bold", size=0.064, upper=False,
        words=4, chars=24, color="#FFFFFF", stroke=0.10, stroke_color="#000000",
        active=None, emph=False, anim="none", box=None, active_box=False, shadow=False,
    ),
    "boxed": dict(
        name="Boxed", kind="simple", font="Poppins-SemiBold", size=0.056, upper=False,
        words=5, chars=28, color="#FFFFFF", stroke=0, stroke_color="#000000",
        active=None, emph=False, anim="none", box="#000000CC", active_box=False, shadow=False,
    ),
    "karaoke": dict(
        name="Karaoke", kind="simple", font="Poppins-ExtraBold", size=0.060, upper=False,
        words=4, chars=22, color="#FFFFFF", stroke=0.10, stroke_color="#000000",
        active="accent", emph=False, anim="none", box=None, active_box=False, shadow=False,
    ),
    "beast": dict(
        name="Impact", kind="dynamic", font="Anton-Regular", size=0.092, upper=True,
        words=3, chars=16, color="#FFFFFF", stroke=0.09, stroke_color="#000000",
        active="accent", emph=False, anim="pop", box=None, active_box=False, shadow=True,
    ),
    "spotlight": dict(
        name="Spotlight", kind="dynamic", font="Poppins-ExtraBold", size=0.066, upper=True,
        words=3, chars=16, color="#FFFFFF", stroke=0.09, stroke_color="#000000",
        active=None, emph=False, anim="pop", box=None, active_box=True, shadow=False,
    ),
    "editorial": dict(
        name="Editorial Mix", kind="dynamic", font="Poppins-SemiBold", size=0.060, upper=False,
        words=4, chars=22, color="#FFFFFF", stroke=0, stroke_color="#000000",
        active=None, emph=True, emph_font="InstrumentSerif-Italic", emph_scale=1.75,
        emph_color="accent", emph_upper=False, stack=False, anim="reveal",
        box=None, active_box=False, shadow=True,
    ),
    "stack": dict(
        name="Type Stack", kind="dynamic", font="Poppins-Bold", size=0.046, upper=True,
        words=4, chars=20, color="#FFFFFF", stroke=0.08, stroke_color="#000000",
        active=None, emph=True, emph_font="Anton-Regular", emph_scale=2.6,
        emph_color="accent", emph_upper=True, stack=True, anim="pop",
        box=None, active_box=False, shadow=True,
    ),
    "oneword": dict(
        name="One Word", kind="dynamic", font="BebasNeue-Regular", size=0.15, upper=True,
        words=1, chars=14, color="#FFFFFF", stroke=0.06, stroke_color="#000000",
        active=None, emph=True, emph_font="BebasNeue-Regular", emph_scale=1.0,
        emph_color="accent", emph_upper=True, stack=False, anim="pop",
        box=None, active_box=False, shadow=True,
    ),
    "podcast": dict(
        name="Podcast Stack", kind="dynamic", font="InterDisplay-SemiBold", size=0.044, upper=False,
        words=5, chars=28, color="#FFFFFF", stroke=0, stroke_color="#000000",
        active=None, emph=True, emph_font="InterDisplay-Bold", emph_scale=2.8,
        emph_color="#FFFFFF", emph_upper=False, stack=True, layout="podcast", track=-0.035,
        emph_track=-0.055, anim="blur", box=None, active_box=False, shadow=True,
    ),
}

POSITIONS = {"top": 0.20, "middle": 0.50, "bottom": 0.74}

STOP = set(
    "a an the and or but so if then than that this these those is are was were be been being am "
    "i you he she it we they me him her us them my your his its our their of to in on at for with "
    "from by as about into over after before up down out off not no yes do does did have has had "
    "will would can could should may might just really very like also too there here what when "
    "where who how why which because while im ive youre dont its thats gonna wanna got get "
    "know think going one all some any more most much many".split()
)


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def clip_words(words: List[dict], start: float, end: float) -> List[dict]:
    """Words inside [start, end], timed relative to the clip start."""
    out = []
    for w in words:
        mid = (w["s"] + w["e"]) / 2
        if mid < start or mid > end:
            continue
        out.append({"w": w["w"].strip(), "s": max(0.0, w["s"] - start), "e": min(end, w["e"]) - start})
    return [w for w in out if w["w"]]


def build_groups(words: List[dict], style: dict) -> List[dict]:
    """Chunk words into caption groups and mark one emphasis word per group."""
    max_w, max_c = style["words"], style["chars"]
    groups, cur, chars = [], [], 0
    for i, w in enumerate(words):
        gap = w["s"] - cur[-1]["e"] if cur else 0
        too_long = cur and (len(cur) >= max_w or chars + len(w["w"]) + 1 > max_c)
        if cur and (too_long or gap > 0.6 or re.search(r"[.!?]$", cur[-1]["w"])):
            groups.append(cur)
            cur, chars = [], 0
        cur.append(dict(w))
        chars += len(w["w"]) + 1
    if cur:
        groups.append(cur)

    out = []
    for gi, g in enumerate(groups):
        nxt = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else None
        g_end = g[-1]["e"] + 0.45
        if nxt is not None:
            g_end = min(g_end, nxt)
        ws = []
        for w in g:
            txt = w["w"]
            if style["kind"] == "dynamic":
                txt = re.sub(r"[.,;:]+$", "", txt)
            txt = txt.strip('"“”')
            if not txt:
                continue
            ws.append({"t": txt, "s": round(w["s"], 3), "e": round(w["e"], 3), "emph": False})
        if not ws:
            continue
        if style.get("emph"):
            best, best_score = 0, -1.0
            for i, w in enumerate(ws):
                n = _norm(w["t"])
                sc = len(n) + (2 if any(c.isdigit() for c in n) else 0) + i * 0.1
                if n in STOP or len(n) < 3:
                    sc = 0.0 + i * 0.01
                if sc > best_score:
                    best, best_score = i, sc
            ws[best]["emph"] = True
            if style.get("layout") == "podcast":
                ws = _merge_hero(ws, best)
        for w in ws:
            up = style.get("emph_upper") if w["emph"] else style["upper"]
            if up:
                w["t"] = w["t"].upper()
        out.append({"s": round(g[0]["s"], 3), "e": round(max(g_end, g[0]["s"] + 0.2), 3), "words": ws})
    return out


_HERO_PRE = {"a", "an", "the"}
_HERO_POST = {"me", "it", "up", "out", "you", "us", "them", "him", "her", "on", "in"}


def _merge_hero(ws: List[dict], h: int) -> List[dict]:
    """Glue tiny helper words onto a short hero so it reads 'tell me' / 'a story'."""
    hero = dict(ws[h])
    lo, hi = h, h
    if h > 0 and _norm(ws[h - 1]["t"]) in _HERO_PRE:
        lo = h - 1
    if (hi + 1 < len(ws) and _norm(ws[hi + 1]["t"]) in _HERO_POST and len(_norm(hero["t"])) <= 5):
        hi = hi + 1
    if lo == hi:
        return ws
    hero["t"] = " ".join(w["t"] for w in ws[lo:hi + 1])
    hero["s"], hero["e"] = ws[lo]["s"], ws[hi]["e"]
    return ws[:lo] + [hero] + ws[hi + 1:]


# ---------------------------------------------------------------- renderer

_font_cache: Dict[tuple, ImageFont.FreeTypeFont] = {}


def _font(name: str, px: int) -> ImageFont.FreeTypeFont:
    key = (name, px)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(os.path.join(FONT_DIR, name + ".ttf"), px)
    return _font_cache[key]


def _rgba(hex_color: str):
    h = hex_color.lstrip("#")
    if len(h) == 6:
        h += "FF"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))


def _tlen(f, txt: str, track: float) -> float:
    """Text width with extra tracking (px per gap)."""
    return f.getlength(txt) + track * max(0, len(txt) - 1)


def _text(d, x: float, base: float, txt: str, f, fill, track: float = 0.0, sw: int = 0, sf=None):
    if not track:
        d.text((x, base), txt, font=f, anchor="ls", fill=fill, stroke_width=sw, stroke_fill=sf)
        return
    for i, ch in enumerate(txt):
        cx = x + f.getlength(txt[:i]) + track * i
        d.text((cx, base), ch, font=f, anchor="ls", fill=fill, stroke_width=sw, stroke_fill=sf)


def _dark_on(hex_color: str) -> str:
    r, g, b, _ = _rgba(hex_color)
    return "#0B0B0B" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#FFFFFF"


class CaptionRenderer:
    """Renders caption frames for one clip as RGBA strips (width x strip_h)."""

    def __init__(self, groups: List[dict], style_id: str, width: int, height: int,
                 accent: str = "#FFE600", position: str = "bottom", scale: float = 1.0):
        self.groups = groups
        self.st = STYLES[style_id]
        self.W, self.H = width, height
        self.accent = accent
        self.scale = scale
        self.strip_h = int(height * 0.40) // 2 * 2
        cy = POSITIONS.get(position, 0.74) * height
        self.strip_y = int(min(max(cy - self.strip_h / 2, 0), height - self.strip_h))
        self.blank = bytes(self.W * self.strip_h * 4)
        self._layouts: Dict[int, dict] = {}
        self._cache: Dict[tuple, bytes] = {}
        self._gi = 0

    def _col(self, c: Optional[str]) -> str:
        return self.accent if c == "accent" else (c or "#FFFFFF")

    def _layout(self, gi: int) -> dict:
        if gi in self._layouts:
            return self._layouts[gi]
        if self.st.get("layout") == "podcast":
            self._layouts[gi] = self._layout_podcast(gi)
            return self._layouts[gi]
        st, W = self.st, self.W
        base_px = max(10, int(st["size"] * W * self.scale))
        max_w = W * 0.88
        items = []
        for w in self.groups[gi]["words"]:
            if w["emph"] and st.get("emph"):
                px = int(base_px * st.get("emph_scale", 1.0))
                f = _font(st["emph_font"], px)
            else:
                px = base_px
                f = _font(st["font"], px)
            tw = f.getlength(w["t"])
            if tw > max_w:  # shrink a single over-wide word
                px = int(px * max_w / tw)
                f = _font(st["emph_font"] if (w["emph"] and st.get("emph")) else st["font"], px)
                tw = f.getlength(w["t"])
            items.append({"w": w, "font": f, "px": px, "tw": tw})
        space = base_px * 0.28
        lines, cur, cw = [], [], 0.0
        for it in items:
            solo = st.get("stack") and it["w"]["emph"]
            add = it["tw"] + (space if cur else 0)
            if cur and (cw + add > max_w or solo or (st.get("stack") and cur[-1]["w"]["emph"])):
                lines.append(cur)
                cur, cw, add = [], 0.0, it["tw"]
            cur.append(it)
            cw += add
        if cur:
            lines.append(cur)
        placed, y = [], 0.0
        total_w = 0.0
        for ln in lines:
            lw = sum(i["tw"] for i in ln) + space * (len(ln) - 1)
            asc = max(i["font"].getmetrics()[0] for i in ln)
            desc = max(i["font"].getmetrics()[1] for i in ln)
            lh = (asc + desc) * (0.86 if st.get("stack") else 0.98)
            x = (W - lw) / 2
            for i in ln:
                i["x"], i["base"] = x, y + asc
                x += i["tw"] + space
                placed.append(i)
            y += lh
            total_w = max(total_w, lw)
        off = (self.strip_h - y) / 2
        for i in placed:
            i["base"] += off
        lay = {"items": placed, "top": off, "h": y, "w": total_w, "base_px": base_px}
        self._layouts[gi] = lay
        return lay

    def _layout_podcast(self, gi: int) -> dict:
        """Small lead-in line (left-aligned) / big hero word / small tail line (right-aligned)."""
        st, W = self.st, self.W
        sp = max(10, int(st["size"] * W * self.scale))
        hp = int(sp * st["emph_scale"])
        ws = self.groups[gi]["words"]
        h = next((i for i, w in enumerate(ws) if w["emph"]), 0)
        fs = _font(st["font"], sp)
        tr_s = st.get("track", 0) * sp
        max_w = W * 0.84
        fh = _font(st["emph_font"], hp)
        tr_h = st.get("emph_track", 0) * hp
        hw = _tlen(fh, ws[h]["t"], tr_h)
        if hw > max_w:
            hp = int(hp * max_w / hw)
            fh = _font(st["emph_font"], hp)
            tr_h = st.get("emph_track", 0) * hp
            hw = _tlen(fh, ws[h]["t"], tr_h)
        space = fs.getlength(" ") * 0.85

        def line(idxs):
            out, x = [], 0.0
            for i in idxs:
                tw = _tlen(fs, ws[i]["t"], tr_s)
                out.append({"w": ws[i], "font": fs, "px": sp, "tw": tw, "track": tr_s, "dx": x})
                x += tw + space
            return out, max(0.0, x - space)

        pre, pw = line(range(0, h))
        post, qw = line(range(h + 1, len(ws)))
        hx = (W - hw) / 2
        margin = W * 0.06
        h_cap = fh.getbbox("H", anchor="ls")[1] * -1          # cap height of hero
        s_cap = fs.getbbox("H", anchor="ls")[1] * -1
        s_desc = fs.getmetrics()[1]
        h_desc = fh.getmetrics()[1]
        y = 0.0
        placed = []
        if pre:
            px0 = min(max(hx + hp * 0.03, margin), W - margin - pw)
            pb = s_cap
            for it in pre:
                it["x"], it["base"] = px0 + it["dx"], pb
                placed.append(it)
            y = pb + s_desc * 0.35 + h_cap * 0.06
        hb = y + h_cap
        placed.append({"w": ws[h], "font": fh, "px": hp, "tw": hw, "track": tr_h, "x": hx, "base": hb})
        y = hb + h_desc * 0.45
        if post:
            qx0 = max(min(hx + hw - qw - hp * 0.02, W - margin - qw), margin)
            qb = y + s_cap * 1.15
            for it in post:
                it["x"], it["base"] = qx0 + it["dx"], qb
                placed.append(it)
            y = qb + s_desc
        # keep original word order for reveal timing
        order = {id(w): i for i, w in enumerate(ws)}
        placed.sort(key=lambda it: order[id(it["w"])])
        off = (self.strip_h - y) / 2
        for it in placed:
            it["base"] += off
        return {"items": placed, "top": off, "h": y, "w": max(hw, pw, qw), "base_px": sp}

    def _draw(self, gi: int, active: int, shown: int, fx: Optional[Dict[int, float]] = None) -> Image.Image:
        st, lay = self.st, self._layout(gi)
        img = Image.new("RGBA", (self.W, self.strip_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        bp = lay["base_px"]
        if st["box"]:
            pad_x, pad_y = bp * 0.45, bp * 0.22
            x0 = (self.W - lay["w"]) / 2 - pad_x
            d.rounded_rectangle([x0, lay["top"] - pad_y, x0 + lay["w"] + 2 * pad_x, lay["top"] + lay["h"] + pad_y],
                                radius=bp * 0.28, fill=_rgba(st["box"]))
        draws = []
        for idx, it in enumerate(lay["items"]):
            if idx >= shown:
                continue
            w = it["w"]
            col = self._col(st["color"])
            if w["emph"] and st.get("emph"):
                col = self._col(st.get("emph_color"))
            if st["active"] and idx == active:
                col = self._col(st["active"])
            if st["active_box"] and idx == active:
                asc, desc = it["font"].getmetrics()
                px, py = bp * 0.16, bp * 0.02
                d.rounded_rectangle([it["x"] - px, it["base"] - asc * 0.86 - py,
                                     it["x"] + it["tw"] + px, it["base"] + desc * 0.55 + py],
                                    radius=bp * 0.18, fill=_rgba(self.accent))
                draws.append((it, _dark_on(self.accent), 0))
                continue
            draws.append((it, col, int(round(st["stroke"] * it["px"]))))
        fx = fx or {}
        idx_of = {id(it): i for i, it in enumerate(lay["items"])}
        settled = [x for x in draws if fx.get(idx_of[id(x[0])], 1.0) >= 1.0]
        moving = [x for x in draws if fx.get(idx_of[id(x[0])], 1.0) < 1.0]
        soft = st.get("anim") == "blur"
        if st["shadow"] and settled:
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(sh)
            a = 120 if soft else 170
            for it, _c, sw in settled:
                _text(sd, it["x"], it["base"] + bp * (0.05 if soft else 0.07), it["w"]["t"], it["font"],
                      (0, 0, 0, a), it.get("track", 0), sw, (0, 0, 0, a))
            sh = sh.filter(ImageFilter.GaussianBlur(bp * (0.22 if soft else 0.10)))
            img = Image.alpha_composite(sh, img)
            d = ImageDraw.Draw(img)
        for it, col, sw in settled:
            _text(d, it["x"], it["base"], it["w"]["t"], it["font"], _rgba(col), it.get("track", 0),
                  sw, _rgba(st["stroke_color"]))
        for it, col, sw in moving:  # blur-in: starts soft, grey and see-through, sharpens to white
            p = fx[idx_of[id(it)]]
            e = 1 - (1 - p) ** 2
            lay_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ld = ImageDraw.Draw(lay_img)
            r, g, b, _ = _rgba(col)
            k = 0.62 + 0.38 * e
            _text(ld, it["x"], it["base"], it["w"]["t"], it["font"],
                  (int(r * k), int(g * k), int(b * k), int(255 * (0.25 + 0.75 * e))), it.get("track", 0))
            rad = (1 - e) * it["px"] * 0.11
            if rad > 0.3:
                lay_img = lay_img.filter(ImageFilter.GaussianBlur(rad))
            img = Image.alpha_composite(img, lay_img)
        return img

    def frame(self, t: float) -> bytes:
        """RGBA bytes of the caption strip at clip time t."""
        gs = self.groups
        while self._gi < len(gs) and t >= gs[self._gi]["e"]:
            self._gi += 1
        if self._gi >= len(gs) or t < gs[self._gi]["s"]:
            return self.blank
        gi = self._gi
        g = gs[gi]
        ws = g["words"]
        active = -1
        for i, w in enumerate(ws):
            if t >= w["s"]:
                active = i
        shown = len(ws)
        if self.st["anim"] in ("reveal", "blur"):
            shown = active + 1
        if self.st["anim"] == "blur":
            dur = 0.26
            fx = {}
            for i in range(shown):
                a = t - ws[i]["s"]
                if a < dur:
                    fx[i] = round(max(0.0, a / dur) * 8) / 8  # 8 steps keeps the cache small
            key = (gi, -1, shown, tuple(sorted(fx.items())))
            if key not in self._cache:
                if len(self._cache) > 60:
                    self._cache.clear()
                self._cache[key] = self._draw(gi, -1, shown, fx).tobytes()
            return self._cache[key]
        key = (gi, active if (self.st["active"] or self.st["active_box"]) else -1, shown)
        age = t - g["s"]
        if self.st["anim"] == "pop" and age < 0.16:
            p = age / 0.16
            s = 0.78 + 0.22 * (1 - (1 - p) ** 3) + 0.05 * (4 * p * (1 - p))
            img = self._draw(gi, key[1], shown)
            nw, nh = int(self.W * s), int(self.strip_h * s)
            small = img.resize((nw, nh), Image.BILINEAR)
            out = Image.new("RGBA", img.size, (0, 0, 0, 0))
            out.paste(small, ((self.W - nw) // 2, (self.strip_h - nh) // 2))
            return out.tobytes()
        if key not in self._cache:
            if len(self._cache) > 40:
                self._cache.clear()
            self._cache[key] = self._draw(gi, key[1], shown).tobytes()
        return self._cache[key]
