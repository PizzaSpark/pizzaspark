#!/usr/bin/env python3
"""Render the SVG cards the profile README shows, in light and dark.

    pip install fonttools
    python scripts/render.py            # everything
    python scripts/render.py --views    # refresh the profile-views pill only

The look matches the portfolio: cream paper, 2px ink borders with hard offset
shadows, Space Grotesk, a yellow accent, and pizza. GitHub shows README images
through <img>, which can't load webfonts, so each SVG embeds a subset of the
fonts it uses as a data URI.
"""

import base64
import html
import io
import json
import pathlib
import re
import sys
import urllib.request
from collections import defaultdict

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT.parent / "assets"
FONT_DIR = ROOT / ".fonts"
VIEWS = ROOT / "views.json"
LOGOS = json.loads((ROOT / "logos.json").read_text(encoding="utf-8"))

USERNAME = "PizzaSpark"
FONT_URLS = {
    "SpaceGrotesk.ttf": "https://github.com/google/fonts/raw/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf",
    "SpaceMono-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/spacemono/SpaceMono-Regular.ttf",
}

# Same tokens as the portfolio's index.css.
THEMES = {
    "light": dict(
        paper="#F7F5EE", grid="rgba(22,22,22,0.06)", surface="#FFFFFF",
        band="#E6E4DD", bar="#FACC00", bar_ink="#161616",
        ink="#161616", muted="rgba(22,22,22,0.72)", subtle="rgba(22,22,22,0.5)",
        line="rgba(22,22,22,0.14)", accent="#FACC00", accent_ink="#161616",
        border="#161616", shadow="#161616",
    ),
    "dark": dict(
        paper="#141412", grid="rgba(243,241,234,0.05)", surface="#1E1D1A",
        band="#22211D", bar="#2A2924", bar_ink="#F3F1EA",
        ink="#F3F1EA", muted="rgba(243,241,234,0.74)", subtle="rgba(243,241,234,0.5)",
        line="rgba(243,241,234,0.14)", accent="#FACC00", accent_ink="#161616",
        # Black shadows vanish on a dark page, so dark mode uses the accent.
        border="#F3F1EA", shadow="#FACC00",
    ),
}

# ------------------------------------------------------------------ content

PROFILE = dict(
    location="Philippines",
    name="SEANTI",
    tagline=("Full-stack engineer shipping", "HR platforms, AI-driven CRMs", "and web + mobile apps end to end."),
    now=[
        ("building", "HR platform @ Humanzlab"),
        ("stack", "React · Hono · Postgres"),
        ("mobile", "Kotlin · Swift · Flutter"),
        ("into", "cosplay & idols"),
        ("based", "Philippines"),
    ],
)

WORK = [
    dict(slug="humanzlab", title="Humanzlab HR System", tagline="Hiring and HR, end to end",
         tags=["React", "TanStack", "Cloudflare", "PostgreSQL", "Prisma", "Expo"], link=True),
    dict(slug="crm", title="AI-Based CRM", tagline="AI-assisted customer workflows",
         tags=["TypeScript", "React", "Supabase", "Redis", "QuickBooks"], link=False),
    dict(slug="sellout", title="Product Sellout System", tagline="Inventory and sellout tracking, web + mobile",
         tags=["Next.js", "Expo", "AWS", "PostgreSQL"], link=False),
]

STACK = [
    ("Languages", ["TypeScript", "JavaScript", "Python", "C#"]),
    ("Frameworks", ["React", "Vite", "Tailwind CSS", "TanStack", "HonoJS", "Elysia", "Express", ".NET"]),
    ("Databases", ["PostgreSQL", "MySQL", "MongoDB", "SQLite", "Redis", "Prisma", "Drizzle"]),
    ("Cloud & DevOps", ["Cloudflare", "AWS", "Azure", "Docker", "Vercel", "Railway", "Git", "GitHub"]),
    ("Mobile", ["Kotlin", "Swift", "Flutter", "KMP", "Expo", "React Native"]),
]

WIDTH = 880

# -------------------------------------------------------------------- fonts


def font_file(name):
    path = FONT_DIR / name
    if not path.exists():
        FONT_DIR.mkdir(exist_ok=True)
        urllib.request.urlretrieve(FONT_URLS[name], path)
    return path


_static = {}


def static_font(face):
    """Bytes of one face: ("G", weight) for Space Grotesk, ("M", 400) for Space Mono."""
    if face not in _static:
        family, weight = face
        if family == "G":
            font = instancer.instantiateVariableFont(TTFont(font_file("SpaceGrotesk.ttf")), {"wght": weight})
        else:
            font = TTFont(font_file("SpaceMono-Regular.ttf"))
        buf = io.BytesIO()
        font.save(buf)
        _static[face] = buf.getvalue()
    return _static[face]


_metrics = {}


def measure(face, s, size, tracking=0.0):
    """Rendered width of s in px from the font's advance widths."""
    if face not in _metrics:
        font = TTFont(io.BytesIO(static_font(face)))
        _metrics[face] = (font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm)
    cmap, hmtx, upm = _metrics[face]
    units = sum(hmtx[cmap.get(ord(ch), ".notdef")][0] for ch in s)
    return units / upm * size + tracking * size * len(s)


def font_face_css(face, chars):
    font = TTFont(io.BytesIO(static_font(face)))
    opts = subset.Options()
    opts.flavor = "woff"
    opts.layout_features = ["kern"]
    opts.name_IDs = []
    sub = subset.Subsetter(opts)
    sub.populate(text="".join(sorted(chars)))
    sub.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    data = base64.b64encode(buf.getvalue()).decode()
    family = "G" if face[0] == "G" else "M"
    return f"@font-face{{font-family:{family};font-weight:{face[1]};src:url(data:font/woff;base64,{data}) format('woff')}}"


# -------------------------------------------------------------- svg builder


def esc(s):
    return html.escape(s, quote=True)


class Svg:
    def __init__(self, w, h, theme, title):
        self.w, self.h, self.t, self.title = w, h, THEMES[theme], title
        self.parts, self.css, self.defs = [], [], []
        self.used = defaultdict(set)

    def add(self, *parts):
        self.parts.extend(parts)

    def c(self, key):
        return self.t.get(key, key)

    def text(self, x, y, s, size=14, weight=400, mono=False, fill="ink", anchor="start",
             tracking=0.0, cls="", extra=""):
        face = ("M", 400) if mono else ("G", weight)
        self.used[face].update(s)
        family = "M" if mono else "G"
        ls = f' letter-spacing="{tracking * size:.2f}"' if tracking else ""
        c = f' class="{cls}"' if cls else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
                 f'font-weight="{weight}" fill="{self.c(fill)}" text-anchor="{anchor}"{ls}{c}{extra}>{esc(s)}</text>')
        return measure(face, s, size, tracking)

    def card(self, x, y, w, h, fill="surface", r=14, shadow=6, stroke=2.5):
        if shadow:
            self.add(f'<rect x="{x + shadow}" y="{y + shadow}" width="{w}" height="{h}" rx="{r}" fill="{self.c("shadow")}"/>')
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{self.c(fill)}" '
                 f'stroke="{self.c("border")}" stroke-width="{stroke}"/>')

    def grid_paper(self, x, y, w, h, r=14, step=28):
        pid = f"grid{len(self.defs)}"
        cid = f"clip{len(self.defs)}"
        self.defs.append(
            f'<pattern id="{pid}" width="{step}" height="{step}" patternUnits="userSpaceOnUse">'
            f'<path d="M {step} 0 L 0 0 0 {step}" fill="none" stroke="{self.c("grid")}" stroke-width="1"/></pattern>'
            f'<clipPath id="{cid}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/></clipPath>')
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="url(#{pid})" clip-path="url(#{cid})"/>')

    def eyebrow(self, x, y, label, line_to):
        w = self.text(x, y, label.upper(), size=12, weight=500, fill="subtle", tracking=0.18)
        self.add(f'<line x1="{x + w + 12:.1f}" y1="{y - 4}" x2="{line_to}" y2="{y - 4}" '
                 f'stroke="{self.c("line")}" stroke-width="1.5"/>')

    def pizza(self, x, y, size, cls=""):
        """The portfolio's outlined slice, top-left at (x, y)."""
        s = size / 64
        ink = self.c("border")
        c = f' class="{cls}"' if cls else ""
        self.add(
            f'<g{c}><g transform="translate({x} {y}) scale({s:.3f})" stroke="{ink}" stroke-linejoin="round">'
            '<path d="M7 17 L57 17 L32 66 Z" fill="#FFD84D" stroke-width="2.5"/>'
            '<path d="M4 17 Q32 1 60 17 Q60 23 55 23 Q32 11 9 23 Q4 23 4 17 Z" fill="#E7A04B" stroke-width="2.5"/>'
            '<circle cx="24" cy="31" r="4.6" fill="#E2483D" stroke-width="2"/>'
            '<circle cx="40" cy="33" r="4" fill="#E2483D" stroke-width="2"/>'
            '<circle cx="32" cy="47" r="3.6" fill="#E2483D" stroke-width="2"/>'
            '<path d="M44 23 q4 -1 5 3 q-4 1 -5 -3 Z" fill="#3F9A4B" stroke-width="1.5"/>'
            '</g></g>')

    def arrow(self, cx, cy, size=12, color="ink", diagonal=True, stroke=2):
        """A drawn arrow (→ or ↗), so it doesn't depend on font glyphs."""
        h = size / 2
        col = self.c(color)
        if diagonal:
            d = f"M{cx - h} {cy + h} L{cx + h} {cy - h} M{cx - h * 0.3} {cy - h} L{cx + h} {cy - h} L{cx + h} {cy + h * 0.3}"
        else:
            d = f"M{cx - h} {cy} L{cx + h} {cy} M{cx + h * 0.2} {cy - h * 0.75} L{cx + h} {cy} L{cx + h * 0.2} {cy + h * 0.75}"
        self.add(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{stroke}" '
                 'stroke-linecap="round" stroke-linejoin="round"/>')

    def logo(self, name, x, y, size=16):
        logo = LOGOS.get(name)
        s = size / 24
        if not logo:
            self.text(x + size / 2, y + size * 0.75, name[0], size=size * 0.8, weight=700, anchor="middle")
            return
        if logo["kind"] == "path":
            fill = logo["hex"]
            if luminance(fill) < 0.2 or luminance(fill) > 0.85:
                fill = self.c("ink")
            self.add(f'<path transform="translate({x} {y}) scale({s:.4f})" d="{logo["d"]}" fill="{fill}"/>')
        else:
            self.add(f'<g transform="translate({x} {y}) scale({s:.4f})" fill="none" stroke="{logo["hex"]}" '
                     f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{logo["inner"]}</g>')

    def render(self):
        fonts = "".join(font_face_css(face, chars) for face, chars in sorted(self.used.items()))
        css = fonts + "".join(self.css) + "@media (prefers-reduced-motion: reduce){*{animation:none!important}}"
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{esc(self.title)}">'
                f'<title>{esc(self.title)}</title><style>{css}</style><defs>{"".join(self.defs)}</defs>'
                + "".join(self.parts) + "</svg>")


def luminance(hex_color):
    n = int(hex_color.lstrip("#"), 16)
    r, g, b = (n >> 16) & 255, (n >> 8) & 255, n & 255
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


# ------------------------------------------------------------------- cards


def hero(theme):
    p = PROFILE
    svg = Svg(WIDTH, 400, theme, f"{p['name']}, {p['location']}. " + " ".join(p["tagline"]))
    svg.card(4, 4, WIDTH - 14, 384, fill="paper", shadow=6)
    svg.grid_paper(4, 4, WIDTH - 14, 384)

    x = 44
    svg.eyebrow(x, 64, p["location"], 400)
    svg.text(x - 4, 168, p["name"], size=108, weight=700, tracking=-0.045)

    y = 222
    svg.text(x, y, p["tagline"][0], size=22, weight=500)
    w = measure(("G", 700), p["tagline"][1], 22)
    svg.add(f'<rect x="{x}" y="{y + 30 + 4}" width="{w:.1f}" height="5" rx="1" fill="{svg.c("accent")}" class="mark"/>')
    svg.text(x, y + 30, p["tagline"][1], size=22, weight=700)
    svg.text(x, y + 60, p["tagline"][2], size=22, weight=500)
    svg.css.append(".mark{transform-box:fill-box;transform-origin:left;animation:mark 1.2s cubic-bezier(.16,1,.3,1) .3s both}"
                   "@keyframes mark{from{transform:scaleX(0)}to{transform:scaleX(1)}}")

    # now.txt window
    wx, wy, ww, wh = 494, 152, 336, 196
    svg.card(wx, wy, ww, wh, fill="surface", shadow=5, r=12)
    svg.add(f'<path d="M{wx} {wy + 32} L{wx + ww} {wy + 32}" stroke="{svg.c("border")}" stroke-width="2.5"/>')
    svg.add(f'<path d="M{wx + 12} {wy + 1.25} H{wx + ww - 12} A10.75 10.75 0 0 1 {wx + ww - 1.25} {wy + 12} V{wy + 30.75} '
            f'H{wx + 1.25} V{wy + 12} A10.75 10.75 0 0 1 {wx + 12} {wy + 1.25} Z" fill="{svg.c("bar")}"/>')
    for i in range(3):
        svg.add(f'<circle cx="{wx + 18 + i * 15}" cy="{wy + 16}" r="4.5" fill="none" stroke="{svg.c("bar_ink")}" stroke-width="1.8"/>')
    svg.text(wx + 72, wy + 21, "now.txt", size=12, mono=True, fill="bar_ink")
    for i, (k, v) in enumerate(p["now"]):
        ly = wy + 62 + i * 25
        svg.text(wx + 22, ly, k, size=13, mono=True, fill="subtle")
        svg.text(wx + 112, ly, v, size=13, mono=True)
    cy = wy + 62 + len(p["now"]) * 25 - 12
    svg.add(f'<rect x="{wx + 22}" y="{cy}" width="8" height="15" fill="{svg.c("ink")}" class="caret"/>')
    svg.css.append(".caret{animation:blink 1.1s steps(1) infinite}@keyframes blink{50%{opacity:0}}")

    # floating slice + bits
    svg.pizza(708, 34, 84, cls="bob")
    svg.css.append(".bob{transform-box:fill-box;transform-origin:center;animation:bob 5s ease-in-out infinite}"
                   "@keyframes bob{0%,100%{transform:translateY(0) rotate(-8deg)}50%{transform:translateY(-8px) rotate(4deg)}}")
    for bx, by, s, op in ((640, 70, "01", 0.35), (812, 128, "1", 0.3), (600, 128, "0", 0.25)):
        svg.text(bx, by, s, size=16, mono=True, fill="subtle", extra=f' opacity="{op}"')
    return svg


def button(theme, label, kind):
    """Pill buttons under the hero. kind: 'primary' | 'out' | 'views'."""
    size = 15
    tw = measure(("G", 500), label, size)
    pad = 18
    if kind == "primary":
        w = pad + tw + 10 + 28 + 6
    elif kind == "out":
        w = pad + tw + 8 + 12 + pad
    else:
        w = pad + 10 + 8 + tw + pad
    w, h = round(w), 40
    svg = Svg(w + 5, h + 5, theme, label)
    svg.card(1.5, 1.5, w - 3, h - 3, fill="surface", r=(h - 3) / 2, shadow=3, stroke=2)
    if kind == "views":
        svg.add(f'<circle cx="{pad + 5}" cy="{h / 2}" r="5" fill="{svg.c("accent")}" stroke="{svg.c("border")}" stroke-width="1.5"/>')
        svg.text(pad + 18, h / 2 + 5.5, label, size=size, weight=500)
    else:
        svg.text(pad, h / 2 + 5.5, label, size=size, weight=500)
        if kind == "primary":
            cx = pad + tw + 10 + 14
            svg.add(f'<circle cx="{cx}" cy="{h / 2}" r="14" fill="{svg.c("accent")}"/>')
            svg.arrow(cx, h / 2, size=11, color="accent_ink", diagonal=False)
        else:
            svg.arrow(pad + tw + 8 + 6, h / 2, size=9, diagonal=True, stroke=1.8)
    return svg


def work_head(theme):
    svg = Svg(WIDTH, 96, theme, "Selected work: three things worth opening")
    svg.eyebrow(4, 28, "Selected work", 360)
    svg.text(2, 70, "Three things worth opening", size=30, weight=700, tracking=-0.02)
    svg.add(f'<line x1="2" y1="94" x2="{WIDTH - 2}" y2="94" stroke="{svg.c("border")}" stroke-width="2"/>')
    return svg


def work_row(theme, i, item):
    svg = Svg(WIDTH, 118, theme, f"{i + 1:02d} {item['title']}: {item['tagline']}")
    num = f"{i + 1:02d}"
    svg.add(f'<text x="4" y="74" font-family="G" font-size="56" font-weight="700" fill="none" '
            f'stroke="{svg.c("ink")}" stroke-width="1.4" letter-spacing="-2">{num}</text>')
    svg.used[("G", 700)].update(num)
    svg.text(112, 44, item["title"], size=26, weight=700, tracking=-0.02)
    svg.text(112, 70, item["tagline"], size=16, fill="muted")
    svg.text(112, 96, " · ".join(t.upper() for t in item["tags"]), size=11, mono=True, fill="subtle", tracking=0.04)
    if item["link"]:
        svg.add(f'<circle cx="{WIDTH - 28}" cy="54" r="18" fill="{svg.c("surface")}" stroke="{svg.c("border")}" stroke-width="2"/>')
        svg.arrow(WIDTH - 28, 54, size=12, diagonal=True)
    svg.add(f'<line x1="2" y1="116" x2="{WIDTH - 2}" y2="116" stroke="{svg.c("line")}" stroke-width="1.5"/>')
    return svg


def stack(theme):
    chip_h, gap, label_w, x0, x1 = 32, 10, 168, 44, WIDTH - 50
    rows = []
    for label, skills in STACK:
        lines, cur, cx = [], [], x0 + label_w
        for s in skills:
            cw = 10 + 18 + 8 + measure(("G", 500), s, 14) + 12
            if cur and cx + cw > x1:
                lines.append(cur)
                cur, cx = [], x0 + label_w
            cur.append((s, cx, cw))
            cx += cw + gap
        lines.append(cur)
        rows.append((label, lines))

    top = 128
    body = sum(len(lines) * (chip_h + gap) - gap + 30 for _, lines in rows)
    h = top + body + 30
    alt = "What I build with. " + " ".join(f"{label}: {', '.join(skills)}." for label, skills in STACK)
    svg = Svg(WIDTH, h + 10, theme, alt)
    svg.card(4, 4, WIDTH - 14, h, fill="paper", shadow=6)
    svg.grid_paper(4, 4, WIDTH - 14, h)
    svg.eyebrow(x0, 52, "Toolbox", 400)
    svg.text(x0, 96, "What I build with", size=32, weight=700, tracking=-0.02)

    y = top
    for label, lines in rows:
        svg.add(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{svg.c("line")}" stroke-width="1.5"/>')
        y += 15
        svg.text(x0, y + 21, label.upper(), size=11, weight=500, fill="muted", tracking=0.16)
        for line in lines:
            for s, cx, cw in line:
                svg.card(cx, y, cw, chip_h, fill="surface", r=8, shadow=2, stroke=1.6)
                svg.logo(s, cx + 10, y + 7, 18)
                svg.text(cx + 36, y + 21, s, size=14, weight=500)
            y += chip_h + gap
        y += 15 - gap
    svg.add(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{svg.c("line")}" stroke-width="1.5"/>')
    return svg


def footer(theme):
    h = 210
    svg = Svg(WIDTH, h + 10, theme, "Let's build something. Open to roles, freelance builds and interesting problems; email is fastest.")
    svg.card(4, 4, WIDTH - 14, h, fill="band", shadow=6)
    svg.add(f'<circle cx="80" cy="40" r="150" fill="{svg.c("accent")}" opacity="0.18" clip-path="url(#fclip)"/>')
    svg.defs.append(f'<clipPath id="fclip"><rect x="4" y="4" width="{WIDTH - 14}" height="{h}" rx="14"/></clipPath>')
    svg.eyebrow(44, 52, "Contact", 400)
    svg.text(42, 100, "Let’s build something.", size=38, weight=700, tracking=-0.03)
    svg.text(44, 132, "Open to roles, freelance builds and interesting problems. Email is fastest.", size=15, fill="muted")
    svg.add(f'<line x1="44" y1="188" x2="{WIDTH - 50}" y2="188" stroke="{svg.c("subtle")}" stroke-width="1.5" stroke-dasharray="4 6"/>')
    svg.pizza(44, 150, 34, cls="walk")
    svg.css.append(
        # The slice trots to the far end, turns around and trots back.
        ".walk{transform-box:fill-box;transform-origin:center;animation:walk 14s linear infinite}"
        "@keyframes walk{0%{transform:translateX(0)}45%{transform:translateX(760px)}"
        "50%{transform:translateX(760px) scaleX(-1)}95%{transform:translateX(0) scaleX(-1)}100%{transform:translateX(0)}}")
    return svg


# ------------------------------------------------------------------- views


def read_views():
    """The stored count label, e.g. "1.6K" (older files hold a plain int)."""
    try:
        views = json.loads(VIEWS.read_text())["views"]
    except (FileNotFoundError, KeyError, ValueError):
        return "0"
    return f"{views:,}" if isinstance(views, int) else str(views)


def fetch_views():
    """Current count from komarev (the invisible counter image in the README).

    komarev abbreviates large counts ("1.6K") even with abbreviated=false, and
    only sends the rounded figure, so the label is kept as komarev prints it.
    """
    url = f"https://komarev.com/ghpvc/?username={USERNAME}&abbreviated=false"
    req = urllib.request.Request(url, headers={"User-Agent": "profile-readme-render"})
    svg = urllib.request.urlopen(req, timeout=20).read().decode()
    labels = re.findall(r">\s*(\d[\d,.]*[KMB]?)\s*<", svg)
    return labels[-1] if labels else read_views()


# -------------------------------------------------------------------- main


def write(name, svg):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(svg.render(), encoding="utf-8")


def render_views(views):
    for theme in THEMES:
        write(f"btn-views-{theme}.svg", button(theme, f"{views} profile views", "views"))


def main():
    if "--views" in sys.argv:
        views = fetch_views()
        # Font subsetting isn't byte-stable, so redrawing an unchanged count
        # would still produce a commit.
        if views == read_views() and all((OUT / f"btn-views-{t}.svg").exists() for t in THEMES):
            print(f"views unchanged ({views})")
            return
        VIEWS.write_text(json.dumps({"views": views}, indent=2) + "\n")
        render_views(views)
        return
    for theme in THEMES:
        write(f"hero-{theme}.svg", hero(theme))
        write(f"btn-site-{theme}.svg", button(theme, "Portfolio", "primary"))
        write(f"btn-linkedin-{theme}.svg", button(theme, "LinkedIn", "out"))
        write(f"btn-email-{theme}.svg", button(theme, "Email", "out"))
        write(f"work-head-{theme}.svg", work_head(theme))
        for i, item in enumerate(WORK):
            write(f"work-{item['slug']}-{theme}.svg", work_row(theme, i, item))
        write(f"stack-{theme}.svg", stack(theme))
        write(f"footer-{theme}.svg", footer(theme))
    render_views(read_views())


if __name__ == "__main__":
    main()
