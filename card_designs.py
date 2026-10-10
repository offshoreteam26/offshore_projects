"""ELEGANT invitation DESIGNS - plain, classy wedding-card style (watercolor flowers, gold corners, navy & gold ...).

   floral     Watercolor Floral     white + mint wash, pink roses, script title
   goldcorner Gold Corners          white, gold ornament corners, serif capitals
   navygold   Navy & Gold           deep navy, gold lace edge, white script
   goldwash   Golden Watercolor     amber watercolor wash, big script title
   arch       Floral Arch           lavender, thin gold arch, soft lilies
   peach      Peach Bloom           peach watercolor, daisies and terracotta leaves
   toran      Marigold Toran        cream, marigold toran with tassels, green sprigs (traditional)

Everything is drawn in code (Pillow). Fonts are read from the card_assets folder (next to this file).
   render(style, content)  -> JPEG bytes of the invitation card
   pass_base(style)        -> same artwork with an empty centre panel (used by pass_card.py)
"""
import io, math, os, random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 2
W, H = 1024, 1536
PW, PH = W * SS, H * SS
PANEL = (130, 215, 894, 1395)            # empty centre area that pass_card.py draws on
HERE = os.path.dirname(os.path.abspath(__file__))
TAU = math.tau


# ───────────────────────────── fonts ─────────────────────────────
def _asset(name):
    for p in (os.path.join(HERE, "card_assets", name), os.path.join(HERE, "static", "fonts", name)):
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"Card font missing: '{name}'. Put it in the card_assets folder")


@lru_cache(maxsize=None)
def font(name, size, wght=None):
    f = ImageFont.truetype(_asset(name), max(8, int(round(size * SS))))
    if wght:
        try:
            f.set_variation_by_axes([wght])
        except Exception:
            pass
    return f


def montserrat(s, w=600): return font("Montserrat[wght].ttf", s, w)
def playfair(s, w=700):   return font("PlayfairDisplay[wght].ttf", s, w)
def cinzel(s, w=600):     return font("Cinzel[wght].ttf", s, w)
def corm(s, w=600):       return font("CormorantGaramond[wght].ttf", s, w)
def corm_i(s, w=500):     return font("CormorantGaramond-Italic[wght].ttf", s, w)
def vibes(s, w=None):     return font("GreatVibes-Regular.ttf", s)
def allura(s, w=None):    return font("Allura-Regular.ttf", s)


# ───────────────────────────── text helpers (1x px coordinates) ─────────────────────────────
def tw(text, f, tr=0.0):
    if not text:
        return 0.0
    base = f.getlength(text) if not tr else sum(f.getlength(c) for c in text)
    return base / SS + tr * (len(text) - 1)


def T(d, x, y, text, f, fill, tr=0.0, al="l"):
    """Draw text with baseline y. al = l / c / r."""
    w = tw(text, f, tr)
    x0 = x - (w / 2 if al == "c" else w if al == "r" else 0)
    if not tr:
        d.text((x0 * SS, y * SS), text, font=f, fill=fill, anchor="ls")
        return
    cx = x0 * SS
    for ch in text:
        d.text((cx, y * SS), ch, font=f, fill=fill, anchor="ls")
        cx += f.getlength(ch) + tr * SS


def wrap(text, f, maxw, tr=0.0):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if tw(trial, f, tr) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit(text, fontfn, maxw, max_lines, start, minimum, step=4, tr=0.0):
    """Biggest size (start..minimum) so the text fits maxw in at most max_lines. -> (lines, size, font)"""
    size = start
    while True:
        f = fontfn(size)
        lines = wrap(text, f, maxw, tr)
        if (len(lines) <= max_lines and all(tw(l, f, tr) <= maxw for l in lines)) or size <= minimum:
            return lines[:max_lines], size, f
        size -= step


def fit_pref1(text, fontfn, maxw, start, min1, start2, min2, step=3):
    """One line if it fits at >= min1, else two lines."""
    lines, size, f = fit(text, fontfn, maxw, 1, start, min1, step)
    if tw(text, f) <= maxw and len(wrap(text, f, maxw)) <= 1:
        return lines, size, f
    return fit(text, fontfn, maxw, 2, start2, min2, step)


def venue_parts(venue):
    head, _, rest = (venue or "").partition(",")
    return head.strip(), rest.strip()


# ───────────────────────────── image helpers ─────────────────────────────
def new():
    return Image.new("RGBA", (PW, PH), (0, 0, 0, 0))


def vgrad(stops):
    ys = np.linspace(0, 1, PH)
    col = np.stack([np.interp(ys, [p for p, _ in stops], [c[i] for _, c in stops]) for i in range(3)], axis=1)
    arr = np.broadcast_to(col[:, None, :], (PH, PW, 3)).astype("uint8")
    return Image.fromarray(arr, "RGB").convert("RGBA")


def grain(img, amt=4, seed=3):
    rng = np.random.default_rng(seed)
    a = np.asarray(img.convert("RGB")).astype("int16")
    a = np.clip(a + rng.normal(0, amt, (PH, PW, 1)), 0, 255).astype("uint8")
    return Image.fromarray(a, "RGB").convert("RGBA")


def wash(img, cx, cy, rx, ry, color, alpha=170, seed=1, rough=0.6):
    """Watercolor patch: irregular soft blob with paper-like texture (done at 1/4 size for speed)."""
    q = 4
    w, h = PW // q, PH // q
    m = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(m)
    rng = random.Random(seed)
    for _ in range(8):
        jx, jy = rng.uniform(-0.3, 0.3) * rx, rng.uniform(-0.3, 0.3) * ry
        k = rng.uniform(0.5, 1.0)
        md.ellipse([(cx + jx - rx * k) * SS / q, (cy + jy - ry * k) * SS / q,
                    (cx + jx + rx * k) * SS / q, (cy + jy + ry * k) * SS / q], fill=rng.randint(110, 230))
    m = m.filter(ImageFilter.GaussianBlur(max(rx, ry) * SS / q * 0.2))
    a = np.asarray(m).astype("float32") / 255
    nz = np.random.default_rng(seed).random((h // 16 + 2, w // 16 + 2)).astype("float32")
    nz = np.asarray(Image.fromarray((nz * 255).astype("uint8")).resize((w, h), Image.BICUBIC)).astype("float32") / 255
    a = np.clip(a * (1 - rough / 2 + rough * nz) * alpha / 255 * 1.5, 0, 1)
    rgba = np.zeros((h, w, 4), dtype="uint8")
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = color
    rgba[..., 3] = (a * 255).astype("uint8")
    img.alpha_composite(Image.fromarray(rgba, "RGBA").resize((PW, PH), Image.BICUBIC))


def rrect(img, box, radius, fill=None, outline=None, width=2):
    lay = new()
    x0, y0, x1, y1 = box
    ImageDraw.Draw(lay).rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=radius * SS,
                                          fill=fill, outline=outline, width=int(width * SS))
    img.alpha_composite(lay)


def diamond(d, cx, cy, r, fill=None, outline=None, w=2):
    cx, cy, r = cx * SS, cy * SS, r * SS
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill, outline=outline, width=int(w * SS))


def divider(d, cx, y, col, half=120, gap=16, w=2):
    d.line([(cx - half) * SS, y * SS, (cx - gap) * SS, y * SS], fill=col, width=int(w * SS))
    d.line([(cx + gap) * SS, y * SS, (cx + half) * SS, y * SS], fill=col, width=int(w * SS))
    diamond(d, cx, y, 6, outline=col, w=w)


def divider_dot(d, cx, y, col, half=70, w=2):
    d.line([(cx - half) * SS, y * SS, (cx - 10) * SS, y * SS], fill=col, width=int(w * SS))
    d.line([(cx + 10) * SS, y * SS, (cx + half) * SS, y * SS], fill=col, width=int(w * SS))
    d.ellipse([(cx - 3.5) * SS, (y - 3.5) * SS, (cx + 3.5) * SS, (y + 3.5) * SS], fill=col)


def distribute(blocks, top, bottom, max_gap=60):
    total = sum(h for h, _ in blocks)
    n = len(blocks)
    gap = min((bottom - top - total) / max(n - 1, 1), max_gap)
    y = top + ((bottom - top) - (total + gap * (n - 1))) / 2
    for h, paint in blocks:
        paint(y)
        y += h + gap


# ───────────────────────────── botanical drawing ─────────────────────────────
GREENS = [(128, 160, 118), (156, 184, 140), (104, 142, 108), (176, 200, 158)]
ROSE_PINK = ((250, 205, 212), (241, 165, 182), (214, 112, 140))
ROSE_PEACH = ((254, 220, 200), (246, 176, 146), (226, 128, 98))


def leaf(d, x, y, ang, length, width, col, alpha=240):
    pts = [(t * length, math.sin(math.pi * t) * width / 2) for t in (i / 12 for i in range(13))]
    pts += [(t * length, -math.sin(math.pi * t) * width / 2) for t in (i / 12 for i in range(12, -1, -1))]
    ca, sa = math.cos(ang), math.sin(ang)
    d.polygon([((x + px * ca - py * sa) * SS, (y + px * sa + py * ca) * SS) for px, py in pts], fill=tuple(col) + (alpha,))
    d.line([x * SS, y * SS, (x + length * 0.85 * ca) * SS, (y + length * 0.85 * sa) * SS],
           fill=tuple(max(0, v - 30) for v in col) + (190,), width=max(1, int(1.5 * SS)))


def rose(d, x, y, r, pal, rng):
    light, mid, dark = pal
    rot = rng.uniform(0, TAU)
    for n, rs, col, off in ((8, 1.0, light, 0.0), (7, 0.78, mid, 0.4), (6, 0.56, mid, 0.1), (5, 0.36, dark, 0.3)):
        pr = r * rs * 0.52
        rim = tuple(int(v * 0.84) for v in col) + (255,)
        for k in range(n):
            a = rot + off + k * TAU / n
            px, py = x + math.cos(a) * r * rs * 0.55, y + math.sin(a) * r * rs * 0.55
            d.ellipse([(px - pr) * SS, (py - pr) * SS, (px + pr) * SS, (py + pr) * SS], fill=tuple(col) + (252,),
                      outline=rim, width=int(1.6 * SS))
    cr = r * 0.17
    d.ellipse([(x - cr) * SS, (y - cr) * SS, (x + cr) * SS, (y + cr) * SS], fill=tuple(dark) + (255,))
    for i in range(3):
        rr = cr * (0.5 + i * 0.5)
        d.arc([(x - rr) * SS, (y - rr) * SS, (x + rr) * SS, (y + rr) * SS], rng.randint(0, 120), rng.randint(220, 330),
              fill=tuple(int(v * 0.7) for v in dark) + (255,), width=int(1.6 * SS))


def daisy(d, x, y, r, rng):
    rot = rng.uniform(0, TAU)
    for k in range(14):
        a = rot + k * TAU / 14
        leaf(d, x, y, a, r, r * 0.34, (255, 252, 246), 255)
        d.line([x * SS, y * SS, (x + math.cos(a) * r * 0.8) * SS, (y + math.sin(a) * r * 0.8) * SS],
               fill=(236, 214, 196, 160), width=int(1.2 * SS))
    cr = r * 0.26
    d.ellipse([(x - cr) * SS, (y - cr) * SS, (x + cr) * SS, (y + cr) * SS], fill=(255, 190, 64, 255))
    for k in range(9):
        a = k * TAU / 9
        d.ellipse([(x + math.cos(a) * cr * 0.6 - 2) * SS, (y + math.sin(a) * cr * 0.6 - 2) * SS,
                   (x + math.cos(a) * cr * 0.6 + 2) * SS, (y + math.sin(a) * cr * 0.6 + 2) * SS], fill=(226, 130, 40, 255))


def lily(d, x, y, r, rng):
    rot = rng.uniform(0, TAU)
    for ring, (rs, col, edge) in enumerate(((1.0, (248, 244, 252), (206, 192, 230)), (0.7, (238, 230, 248), (190, 172, 222)))):
        n = 8
        for k in range(n):
            a = rot + k * TAU / n + ring * TAU / 16
            leaf(d, x, y, a, r * rs, r * rs * 0.5, col, 245)
            d.line([x * SS, y * SS, (x + math.cos(a) * r * rs * 0.8) * SS, (y + math.sin(a) * r * rs * 0.8) * SS],
                   fill=edge + (200,), width=int(1.4 * SS))
    for k in range(10):
        a = k * TAU / 10
        px, py = x + math.cos(a) * r * 0.2, y + math.sin(a) * r * 0.2
        d.line([x * SS, y * SS, px * SS, py * SS], fill=(214, 170, 90, 255), width=int(1.4 * SS))
        d.ellipse([(px - 2.4) * SS, (py - 2.4) * SS, (px + 2.4) * SS, (py + 2.4) * SS], fill=(226, 150, 60, 255))


def sprig(d, x, y, ang, length, rng, cols, scale=1.0, tip=True, color=(110, 138, 100)):
    ex, ey = x + math.cos(ang) * length, y + math.sin(ang) * length
    d.line([x * SS, y * SS, ex * SS, ey * SS], fill=tuple(color) + (255,), width=max(2, int(3 * SS * scale)))
    n = rng.randint(3, 5)
    for j in range(1, n + 1):
        t = j / (n + 1)
        px, py = x + (ex - x) * t, y + (ey - y) * t
        for sd in (-1, 1):
            leaf(d, px, py, ang + sd * rng.uniform(0.55, 0.95), rng.uniform(46, 80) * scale, rng.uniform(20, 32) * scale, rng.choice(cols))
    if tip:
        leaf(d, ex, ey, ang, rng.uniform(50, 80) * scale, rng.uniform(22, 32) * scale, rng.choice(cols))


def cluster(lay, x, y, scale, seed, pal=ROSE_PINK, cols=GREENS, toward=(512, 768), flower="rose", spread=1.25):
    rng = random.Random(seed)
    d = ImageDraw.Draw(lay)
    base = math.atan2(toward[1] - y, toward[0] - x)
    for _ in range(15):
        sprig(d, x, y, base + rng.uniform(-spread, spread), rng.uniform(110, 230) * scale, rng, cols, scale)
    for ox, oy, k in ((0, 0, 1.0), (-0.9, 0.5, 0.8), (0.7, 0.85, 0.7), (0.5, -0.9, 0.62)):
        fx, fy = x + ox * 70 * scale, y + oy * 70 * scale
        rr = rng.uniform(62, 78) * scale * k
        if flower == "rose":
            rose(d, fx, fy, rr, pal, rng)
        elif flower == "daisy":
            daisy(d, fx, fy, rr * 0.95, rng)
        else:
            lily(d, fx, fy, rr * 1.15, rng)
    for _ in range(7):                                       # buds / berries
        a = rng.uniform(0, TAU)
        bx, by = x + math.cos(a) * rng.uniform(90, 190) * scale, y + math.sin(a) * rng.uniform(90, 190) * scale
        rr = rng.uniform(7, 12) * scale
        d.ellipse([(bx - rr) * SS, (by - rr) * SS, (bx + rr) * SS, (by + rr) * SS], fill=tuple(pal[1]) + (255,))


def gold_dots(img, seed, n, box, col=(214, 172, 84)):
    rng = random.Random(seed)
    lay = new()
    d = ImageDraw.Draw(lay)
    for _ in range(n):
        x, y, r = rng.uniform(box[0], box[2]), rng.uniform(box[1], box[3]), rng.uniform(1.2, 3.4)
        d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=tuple(col) + (rng.randint(110, 230),))
    img.alpha_composite(lay)


def arch_pts(cx, top, r, bottom, n=60):
    cy = top + r
    pts = [(cx - r, bottom), (cx - r, cy)]
    for i in range(1, n):
        a = math.pi + math.pi * i / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts += [(cx + r, cy), (cx + r, bottom)]
    return pts


# ───────────────────────────── plain, classy text layout (shared by all designs) ─────────────────────────────
def _blocks(d, c, cfg, tscale, with_lead):
    cx = W / 2
    maxw = cfg.get("maxw", 640)
    ink, acc = cfg["ink"], cfg["acc"]
    B = []

    # eyebrow + ornament
    fn, sz, tr, col = cfg["eb"]
    eb = c["eyebrow"].upper() if cfg.get("eb_upper", True) else c["eyebrow"]
    f = fn(sz)
    while tw(eb, f, tr) > maxw + 80 and tr > 0.5:
        tr -= 0.5
    while tw(eb, f, tr) > maxw + 80 and sz > 12:
        sz -= 1
        f = fn(sz)
    B.append((sz + 8, lambda y, f=f, tr=tr, col=col, sz=sz, eb=eb: T(d, cx, y + sz, eb, f, col, tr, "c")))
    orn = cfg.get("orn", divider)
    B.append((22, lambda y: orn(d, cx, y + 11, acc)))

    # title (never drops words: gets smaller / uses up to 5 lines instead)
    t = cfg["title"]
    ttxt = c["event"].upper() if t.get("upper") else c["event"]
    tl, ts, tf = fit(ttxt, t["fn"], t.get("maxw", maxw), 5, int(t["start"] * tscale), max(30, int(t["min"] * tscale * 0.7)), 4,
                     tr=t.get("tr", 0))
    tlh = ts * t.get("lh", 1.0)
    B.append((tlh * len(tl) + t.get("pad", 8) * min(1.0, tscale + 0.3),
              lambda y, tl=tl, ts=ts, tf=tf, tlh=tlh, t=t: [T(d, cx, y + ts * t.get("asc", 0.85) + i * tlh, l, tf, t["color"], t.get("tr", 0), "c")
                                                          for i, l in enumerate(tl)]))

    # host
    h = cfg["host"]
    hl, hs, hf = fit(c["host"], h["fn"], maxw, 2, int(h["start"] * min(1.0, tscale + 0.2)), h["min"] - 6, 3)
    lab = h.get("label")
    hh = (30 if lab else 0) + hs * 1.18 * len(hl)

    def paint_host(y, hl=hl, hs=hs, hf=hf, lab=lab, h=h):
        yy = y
        if lab:
            T(d, cx, y + 20, lab, corm_i(26, 500), h.get("lab_col", acc), 1, "c")
            yy += 30
        for i, l in enumerate(hl):
            T(d, cx, yy + hs * 0.85 + i * hs * 1.18, l, hf, h["color"], h.get("tr", 0), "c")
    B.append((hh, paint_host))

    # lead text
    if with_lead and cfg.get("lead", True) and c.get("lead"):
        lf = corm_i(35, 500)
        ll = [x for x in c["lead"] if x.strip()]
        B.append((len(ll) * 42 + 6, lambda y, ll=ll, lf=lf: [T(d, cx, y + 31 + i * 42, l, lf, ink, 0, "c") for i, l in enumerate(ll)]))
    B.append((22, lambda y: orn(d, cx, y + 11, acc)))

    # details: DATE | TIME, then venue
    dfn, dsz, dtr, dcol = cfg["det"]
    dsz = int(dsz * min(1.0, tscale + 0.25))
    df = dfn(dsz)
    lines = []
    date_u = c["date"].upper()
    if c.get("time"):
        one = f"{date_u}   |   {c['time']}"
        if tw(one, df, dtr) <= maxw:
            lines.append((one, df, dtr, dcol))
        else:
            lines += [(l, df, dtr, dcol) for l in wrap(date_u, df, maxw, dtr)[:2]] + [(c["time"], df, dtr, dcol)]
    else:
        lines += [(l, df, dtr, dcol) for l in wrap(date_u, df, maxw, dtr)[:2]]
    if c.get("venue"):
        head, rest = venue_parts(c["venue"])
        vf, rf = dfn(dsz - 2), corm(dsz + 3, 600) if cfg.get("rest_serif", True) else dfn(dsz - 4)
        lines += [(l, vf, dtr, ink) for l in wrap(head.upper(), vf, maxw, dtr)[:4]]
        if rest:
            lines += [(l, rf, 0.6, ink) for l in wrap(rest, rf, maxw)[:3]]
    lh_d = dsz + 24
    B.append((len(lines) * lh_d + 6,
              lambda y, lines=lines, lh_d=lh_d: [T(d, cx, y + lh_d - 6 + i * lh_d, l, f_, col_, tr_, "c")
                                                 for i, (l, f_, tr_, col_) in enumerate(lines)]))

    # closing
    cl = " ".join(c["closing"])
    cf = corm_i(38, 500)
    while tw(cl, cf) > maxw + 60 and cf.size > 18 * SS:
        cf = corm_i(cf.size / SS - 2, 500)
    B.append((48, lambda y, cl=cl, cf=cf: T(d, cx, y + 36, cl, cf, ink, 0, "c")))
    return B


def _layout(img, c, cfg):
    d = ImageDraw.Draw(img)
    top, bottom, gap = cfg.get("region", (260, 1290, 46))
    for with_lead in (True, False):
        for tscale in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
            B = _blocks(ImageDraw.Draw(new()), c, cfg, tscale, with_lead)       # dry run: only measures
            if sum(h for h, _ in B) + 12 * (len(B) - 1) <= bottom - top:
                break
        else:
            continue
        break
    B = _blocks(d, c, cfg, tscale, with_lead)
    distribute(B, top, bottom, gap)


# ═════════════════════════════ 1. WATERCOLOR FLORAL ═════════════════════════════
def _bg_floral():
    img = Image.new("RGBA", (PW, PH), (253, 253, 252, 255))
    wash(img, 90, 1260, 560, 430, (176, 222, 208), 170, seed=2)
    wash(img, 950, 230, 420, 340, (192, 228, 220), 140, seed=3)
    wash(img, 930, 1380, 430, 260, (210, 236, 230), 130, seed=4)
    wash(img, 60, 120, 300, 220, (226, 242, 238), 120, seed=5)
    lay = new()
    cluster(lay, 915, 105, 1.0, 1, toward=(450, 700))
    cluster(lay, 100, 1440, 1.1, 2, toward=(560, 800))
    cluster(lay, 985, 1480, 0.7, 3, toward=(560, 800))
    img.alpha_composite(lay)
    ImageDraw.Draw(img).rectangle([46 * SS, 46 * SS, (W - 46) * SS, (H - 46) * SS], outline=(196, 160, 96, 160), width=2 * SS)
    gold_dots(img, 4, 40, (60, 60, 960, 1470))
    return grain(img, 3)


# ═════════════════════════════ 2. GOLD CORNERS ═════════════════════════════
GOLD = (190, 148, 66)


def _corner(d, x, y, sx, sy, col=GOLD):
    def P(px, py):
        return ((x + sx * px) * SS, (y + sy * py) * SS)
    for off, ln in ((0, 190), (16, 120)):
        d.line([P(off, off), P(ln, off)], fill=col, width=3 * SS)
        d.line([P(off, off), P(off, ln)], fill=col, width=3 * SS)
    pts = []
    for i in range(61):                                         # spiral curl
        t = i / 60
        r = 46 * (1 - t * 0.8)
        a = math.pi * (0.3 + 3.3 * t)
        pts.append(P(78 + math.cos(a) * r, 78 + math.sin(a) * r))
    d.line(pts, fill=col, width=3 * SS, joint="curve")
    for k, (px, py, ang) in enumerate(((130, 40, 0.0), (160, 40, 0.0), (40, 130, 1.57), (40, 160, 1.57), (96, 28, 0.5), (28, 96, 1.07))):
        a = ang if sx == 1 else math.pi - ang
        if sy == -1:
            a = -a
        leaf(d, x + sx * px, y + sy * py, a, 34, 14, col, 255)
    for px, py in ((200, 16), (16, 200), (118, 118)):
        (ax, ay), (bx, by) = P(px - 4, py - 4), P(px + 4, py + 4)
        d.ellipse([min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)], fill=col)


def _bg_goldcorner():
    img = Image.new("RGBA", (PW, PH), (255, 255, 255, 255))
    lay = new()
    d = ImageDraw.Draw(lay)
    for gx in range(0, W + 60, 60):                               # faint lattice
        for gy in range(0, H + 60, 60):
            diamond(d, gx + (30 if (gy // 60) % 2 else 0), gy, 3, fill=(236, 236, 236, 255))
    img.alpha_composite(lay)
    d = ImageDraw.Draw(img)
    for (x, y, sx, sy) in ((54, 54, 1, 1), (W - 54, 54, -1, 1), (W - 54, H - 54, -1, -1), (54, H - 54, 1, -1)):
        _corner(d, x, y, sx, sy)
    return grain(img, 2)


# ═════════════════════════════ 3. NAVY & GOLD ═════════════════════════════
GOLD_N = (216, 176, 92)


def _lace(d, y, down, col=GOLD_N):
    step = 46
    for i in range(-1, W // step + 2):
        cx = i * step + step / 2
        if down:
            d.arc([(cx - step / 2) * SS, (y - step / 2) * SS, (cx + step / 2) * SS, (y + step / 2) * SS], 0, 180, fill=col, width=3 * SS)
            d.arc([(cx - 15) * SS, (y - 15) * SS, (cx + 15) * SS, (y + 15) * SS], 0, 180, fill=col, width=2 * SS)
            d.ellipse([(cx - 3) * SS, (y + step / 2 - 10) * SS, (cx + 3) * SS, (y + step / 2 - 4) * SS], fill=col)
        else:
            d.arc([(cx - step / 2) * SS, (y - step / 2) * SS, (cx + step / 2) * SS, (y + step / 2) * SS], 180, 360, fill=col, width=3 * SS)
            d.arc([(cx - 15) * SS, (y - 15) * SS, (cx + 15) * SS, (y + 15) * SS], 180, 360, fill=col, width=2 * SS)
            d.ellipse([(cx - 3) * SS, (y - step / 2 + 4) * SS, (cx + 3) * SS, (y - step / 2 + 10) * SS], fill=col)
    d.line([0, y * SS, W * SS, y * SS], fill=col, width=3 * SS)


def _bg_navygold():
    img = vgrad([(0, (6, 38, 84)), (0.5, (4, 30, 70)), (1, (3, 22, 54))])
    lay = new()
    ImageDraw.Draw(lay).ellipse([(W / 2 - 520) * SS, (H / 2 - 620) * SS, (W / 2 + 520) * SS, (H / 2 + 620) * SS], fill=(40, 96, 170, 36))
    img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(120 * SS)))
    d = ImageDraw.Draw(img)
    _lace(d, 44, True)
    _lace(d, H - 44, False)
    for x in (74, W - 74):
        d.line([x * SS, 230 * SS, x * SS, (H - 230) * SS], fill=GOLD_N, width=2 * SS)
        diamond(d, x, 222, 7, fill=GOLD_N)
        diamond(d, x, H - 222, 7, fill=GOLD_N)
    d.rectangle([28 * SS, 28 * SS, (W - 28) * SS, (H - 28) * SS], outline=GOLD_N, width=2 * SS)
    # emblem
    cx, cy = W / 2, 170
    for r, w in ((46, 3), (36, 2)):
        d.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], outline=GOLD_N, width=w * SS)
    for k in range(8):
        a = k * TAU / 8
        leaf(d, cx, cy, a, 30, 13, GOLD_N, 255)
    d.ellipse([(cx - 5) * SS, (cy - 5) * SS, (cx + 5) * SS, (cy + 5) * SS], fill=GOLD_N)
    return grain(img, 3)


# ═════════════════════════════ 4. GOLDEN WATERCOLOR ═════════════════════════════
def _bg_goldwash():
    img = Image.new("RGBA", (PW, PH), (255, 253, 247, 255))
    wash(img, 512, 40, 760, 330, (246, 190, 64), 230, seed=7, rough=0.8)
    wash(img, 250, 120, 420, 220, (250, 214, 110), 160, seed=8)
    wash(img, 880, 160, 360, 200, (240, 168, 46), 140, seed=9)
    wash(img, 512, 1500, 780, 300, (246, 190, 64), 220, seed=10, rough=0.8)
    wash(img, 760, 1440, 420, 210, (250, 214, 110), 150, seed=11)
    wash(img, 160, 1420, 380, 200, (240, 168, 46), 140, seed=12)
    gold_dots(img, 3, 70, (0, 0, W, 330), (206, 150, 40))
    gold_dots(img, 5, 70, (0, 1210, W, H), (206, 150, 40))
    return grain(img, 5)


# ═════════════════════════════ 5. FLORAL ARCH ═════════════════════════════
def _bg_arch():
    img = vgrad([(0, (244, 242, 253)), (1, (234, 230, 248))])
    wash(img, 120, 140, 420, 340, (214, 204, 240), 150, seed=21)
    wash(img, 940, 1400, 460, 340, (222, 212, 244), 150, seed=22)
    lay = new()
    cluster(lay, 70, 90, 1.05, 31, pal=ROSE_PINK, cols=[(150, 172, 150), (176, 196, 170), (128, 152, 132)], toward=(520, 700), flower="lily")
    cluster(lay, 985, 1475, 1.1, 32, cols=[(150, 172, 150), (176, 196, 170), (128, 152, 132)], toward=(500, 800), flower="lily")
    cluster(lay, 45, 1490, 0.75, 33, cols=[(150, 172, 150), (176, 196, 170)], toward=(520, 800), flower="lily")
    img.alpha_composite(lay)
    d = ImageDraw.Draw(img)
    g = (190, 150, 80, 255)
    for r, w, off in ((372, 4, 0), (358, 2, 14)):
        pts = arch_pts(W / 2, 180 + off, r, 1380 - off)
        d.line([(x * SS, y * SS) for x, y in pts] + [(pts[0][0] * SS, pts[0][1] * SS)], fill=g, width=w * SS, joint="curve")
    return grain(img, 3)


# ═════════════════════════════ 6. PEACH BLOOM ═════════════════════════════
LEAVES_T = [(214, 120, 84), (232, 156, 108), (198, 98, 70), (240, 186, 140)]


def _bg_peach():
    img = vgrad([(0, (255, 244, 236)), (1, (254, 228, 216))])
    wash(img, 150, 120, 520, 330, (255, 208, 182), 190, seed=41, rough=0.8)
    wash(img, 900, 320, 380, 300, (255, 220, 200), 150, seed=42)
    wash(img, 512, 1500, 760, 320, (255, 200, 170), 200, seed=43, rough=0.8)
    lay = new()
    d = ImageDraw.Draw(lay)
    rng = random.Random(44)
    for sx, ang in ((90, -1.35), (240, -1.5), (400, -1.62), (560, -1.5), (720, -1.62), (880, -1.74), (990, -1.9)):
        sprig(d, sx, H + 24, ang, rng.uniform(150, 250), rng, LEAVES_T, 1.0, color=(190, 110, 80))
    for fx, fy, fr in ((130, 1420, 56), (330, 1380, 62), (520, 1440, 52), (710, 1390, 64), (900, 1425, 58), (40, 1330, 42), (990, 1330, 44)):
        daisy(d, fx, fy, fr, rng)
    for sx, ang in ((-10, 0.35), (60, 0.7)):
        sprig(d, sx, -20, ang, rng.uniform(200, 280), rng, LEAVES_T, 1.0, color=(190, 110, 80))
    for sx, ang in ((W + 10, math.pi - 0.45), (W - 60, math.pi - 0.8)):
        sprig(d, sx, -20, ang, rng.uniform(170, 240), rng, LEAVES_T, 0.9, color=(190, 110, 80))
    daisy(d, 60, 150, 48, rng)
    daisy(d, 985, 210, 40, rng)
    img.alpha_composite(lay)
    return grain(img, 4)


# ═════════════════════════════ 7. MARIGOLD TORAN ═════════════════════════════
def _marigold(d, x, y, r, rng):
    x, y, r = x * SS, y * SS, r * SS
    for k in range(10):
        a = k * TAU / 10
        px, py = x + math.cos(a) * r * 0.62, y + math.sin(a) * r * 0.62
        d.ellipse([px - r * 0.42, py - r * 0.42, px + r * 0.42, py + r * 0.42], fill=rng.choice([(244, 150, 30), (252, 170, 36)]) + (255,))
    d.ellipse([x - r * 0.6, y - r * 0.6, x + r * 0.6, y + r * 0.6], fill=(255, 196, 56, 255))
    d.ellipse([x - r * 0.25, y - r * 0.25, x + r * 0.25, y + r * 0.25], fill=(216, 104, 16, 255))


def _bg_toran():
    img = vgrad([(0, (255, 252, 243)), (1, (252, 245, 228))])
    wash(img, 512, 1480, 760, 330, (196, 230, 228), 170, seed=51)
    wash(img, 90, 1000, 260, 420, (214, 238, 232), 120, seed=52)
    lay = new()
    d = ImageDraw.Draw(lay)
    rng = random.Random(53)
    d.rectangle([0, 0, W * SS, 62 * SS], fill=(252, 204, 66, 255))
    n = 8
    seg = W / n
    for i in range(n):
        cx, r = i * seg + seg / 2, seg / 2
        d.pieslice([(cx - r) * SS, (62 - r) * SS, (cx + r) * SS, (62 + r) * SS], 0, 180, fill=(252, 204, 66, 255), outline=(236, 158, 40, 255), width=3 * SS)
        r2 = r * 0.66
        d.pieslice([(cx - r2) * SS, (62 - r2) * SS, (cx + r2) * SS, (62 + r2) * SS], 0, 180, fill=(255, 228, 130, 255))
        for k in (-0.55, 0, 0.55):
            px = cx + k * r * 0.9
            py = 62 + math.sqrt(max(r * r - (k * r * 0.9) ** 2, 0))
            ln = 46 if k == 0 else 34
            d.line([px * SS, py * SS, px * SS, (py + ln) * SS], fill=(236, 158, 40, 255), width=2 * SS)
            d.ellipse([(px - 6) * SS, (py + ln) * SS, (px + 6) * SS, (py + ln + 20) * SS], fill=(240, 120, 160, 255))
        _marigold(d, cx + r, 62, 14, rng)
    for side in (-1, 1):
        x0 = 36 if side == 1 else W - 36
        for yy in range(210, 900, 120):
            sprig(d, x0, yy, (0.25 if side == 1 else math.pi - 0.25), rng.uniform(70, 120), rng, GREENS, 0.8)
        d.line([x0 * SS, 200 * SS, x0 * SS, 900 * SS], fill=(110, 138, 100, 255), width=3 * SS)
    img.alpha_composite(lay)
    return grain(img, 3)


# ═════════════════════════════ per-design text settings ═════════════════════════════
def _serif_caps(s): return corm(s, 600)


CFG = {
    "floral": dict(
        ink=(58, 72, 82), acc=(184, 142, 70), maxw=580, region=(280, 1305, 62),
        eb=(lambda s: corm(s, 600), 27, 6, (110, 120, 128)),
        title=dict(fn=allura, start=180, min=80, lines=3, color=(52, 66, 78), lh=0.98, asc=0.8, pad=36),
        host=dict(fn=lambda s: corm_i(s, 600), start=60, min=38, color=(58, 72, 82), label="hosted by", lab_col=(150, 120, 70)),
        det=(lambda s: corm(s, 700), 34, 3, (176, 132, 56)),
        panel=((255, 255, 255, 226), (200, 168, 104, 255)),
    ),
    "goldcorner": dict(
        ink=(38, 70, 80), acc=GOLD, maxw=600, region=(250, 1290, 66),
        eb=(lambda s: cinzel(s, 600), 23, 5, GOLD),
        title=dict(fn=lambda s: corm(s, 600), upper=True, start=140, min=60, lines=3, tr=6, color=(30, 62, 72), lh=1.05, asc=0.8, pad=14),
        host=dict(fn=lambda s: corm_i(s, 600), start=60, min=38, color=(38, 70, 80), label="hosted by", lab_col=GOLD),
        det=(lambda s: cinzel(s, 700), 32, 3, GOLD),
        panel=((255, 255, 255, 235), GOLD + (255,)),
    ),
    "navygold": dict(
        ink=(244, 238, 224), acc=GOLD_N, maxw=600, region=(260, 1290, 62),
        eb=(lambda s: corm(s, 600), 27, 6, GOLD_N),
        title=dict(fn=allura, start=180, min=80, lines=3, color=(255, 255, 255), lh=0.98, asc=0.8, pad=36),
        host=dict(fn=lambda s: corm_i(s, 600), start=60, min=38, color=GOLD_N, label=None),
        det=(lambda s: corm(s, 700), 35, 3, GOLD_N),
        panel=((6, 28, 62, 238), GOLD_N + (255,)),
    ),
    "goldwash": dict(
        ink=(60, 52, 46), acc=(200, 140, 40), maxw=600, region=(335, 1262, 62),
        eb=(lambda s: corm_i(s, 600), 36, 2, (190, 128, 36)),
        eb_upper=False,
        title=dict(fn=vibes, start=190, min=80, lines=3, color=(46, 40, 36), lh=0.98, asc=0.8, pad=36),
        host=dict(fn=lambda s: corm(s, 600), start=46, min=30, color=(60, 52, 46), tr=3, label=None),
        det=(lambda s: corm(s, 700), 35, 3, (190, 128, 36)),
        panel=((255, 253, 246, 232), (214, 160, 60, 255)),
    ),
    "arch": dict(
        ink=(76, 74, 104), acc=(180, 140, 76), maxw=520, region=(250, 1275, 58),
        eb=(lambda s: montserrat(s, 500), 20, 6, (110, 108, 140)),
        title=dict(fn=lambda s: cinzel(s, 500), upper=True, start=100, min=44, lines=3, tr=6, color=(84, 84, 116), lh=1.12, asc=0.82, pad=14, maxw=540),
        host=dict(fn=lambda s: corm_i(s, 600), start=54, min=34, color=(76, 74, 104), label="hosted by", lab_col=(180, 140, 76)),
        det=(lambda s: montserrat(s, 600), 23, 4, (150, 112, 52)),
        panel=((255, 255, 255, 220), (190, 150, 84, 255)),
    ),
    "peach": dict(
        ink=(122, 46, 46), acc=(200, 112, 72), maxw=600, region=(255, 1285, 62),
        eb=(lambda s: corm(s, 700), 28, 6, (150, 60, 56)),
        title=dict(fn=allura, start=180, min=80, lines=3, color=(130, 42, 44), lh=0.98, asc=0.8, pad=36),
        host=dict(fn=lambda s: corm(s, 700), start=46, min=30, color=(122, 46, 46), tr=3, label=None),
        det=(lambda s: corm(s, 700), 35, 3, (158, 62, 52)),
        panel=((255, 250, 245, 230), (214, 140, 100, 255)),
    ),
    "toran": dict(
        ink=(80, 60, 44), acc=(206, 150, 40), maxw=560, region=(280, 1290, 62),
        eb=(lambda s: corm(s, 700), 27, 6, (30, 120, 134)),
        title=dict(fn=allura, start=180, min=80, lines=3, color=(24, 136, 154), lh=0.98, asc=0.8, pad=36),
        host=dict(fn=lambda s: corm(s, 700), start=46, min=30, color=(80, 60, 44), tr=3, label=None),
        det=(lambda s: corm(s, 700), 35, 3, (190, 128, 30)),
        panel=((255, 252, 244, 232), (230, 176, 70, 255)),
    ),
}
_BG = {"floral": _bg_floral, "goldcorner": _bg_goldcorner, "navygold": _bg_navygold, "goldwash": _bg_goldwash,
       "arch": _bg_arch, "peach": _bg_peach, "toran": _bg_toran}
DESIGNS = list(CFG)
_CACHE = {}


def _backdrop(style):
    if style not in _CACHE:
        _CACHE[style] = _BG[style]()
    return _CACHE[style].copy()


def _jpeg(img):
    out = img.convert("RGB").resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=92, optimize=True)
    return buf.getvalue()


def render(style, content):
    """content = eyebrow, event, host, date, time, venue, lead (list), closing (list). -> JPEG bytes"""
    img = _backdrop(style)
    _layout(img, content, CFG[style])
    return _jpeg(img)


def pass_base(style):
    """RGB 1024x1536 artwork with an empty centre panel (for the guest pass)."""
    img = _backdrop(style)
    fill, line = CFG[style]["panel"]
    rrect(img, PANEL, 40, fill=fill, outline=line, width=3)
    rrect(img, [PANEL[0] + 12, PANEL[1] + 12, PANEL[2] - 12, PANEL[3] - 12], 30, outline=line[:3] + (140,), width=1.5)
    return img.convert("RGB").resize((W, H), Image.LANCZOS)


if __name__ == "__main__":
    import sys
    c = dict(eyebrow="YOU'RE INVITED TO", event=sys.argv[2] if len(sys.argv) > 2 else "Wedding Reception",
             host="Ramesh Kumar & Family", date="18 Oct 2026", time="5:00 PM",
             venue="TA Community Hall, Hyderabad", lead=["join us for an evening of", "love, laughter and good times"],
             closing=["We look forward to", "seeing you!"])
    for k in ([sys.argv[1]] if len(sys.argv) > 1 else DESIGNS):
        open(f"design_{k}.jpg", "wb").write(render(k, c))
        print("saved", k)