"""PHAROS: the presentation Dr Sama gives at the pharmacovigilance inspection, Wednesday 18 November 2026.

Every slide carries her own points (her notes of 5, 8 and 9 November 2026), in the PHAROS identity: paper ground,
navy masthead, beacon gold as the one accent, square corners, hairline rules, flat colour only.

    python docs/presentation/build.py            -> docs/presentation/PHAROS Presentation.pptx (editable)
    powershell -File docs/presentation/export.ps1 -> embeds the fonts and writes "PHAROS Presentation.pdf"
"""
import re
from pathlib import Path

import yaml
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BRAND = ROOT / "web" / "public" / "brand"
OUT = HERE / "PHAROS Presentation.pptx"


def C(h):
    return RGBColor.from_string(h.lstrip("#").upper())


INK, PAPER, SURF, SURF2 = C("02224C"), C("F6F4EF"), C("FFFFFF"), C("EFECE4")
RULE, MUTED, SEA, BEACON, DEEP = C("D9D5CC"), C("5B6670"), C("1F4E5F"), C("E3A336"), C("8A5A0B")
SEA_T, BEACON_T = C("E7EEF0"), C("FBF1DE")
MAST_MUTED, MAST_RULE, MAST_RAISE, WHITE = C("B4C0CF"), C("23446F"), C("0B3163"), C("FFFFFF")
SERIF, SANS, MONO = "Noto Serif", "Noto Sans", "Consolas"

SW, SH = 13.333, 7.5
M = 0.65
CW = SW - 2 * M
DATE = "Wednesday 18 November 2026"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(SW), Inches(SH)
BLANK = prs.slide_layouts[6]
SLIDES = []


# ───────── drawing kit ─────────
def inch(v):
    return Inches(v)


def rect(s, x, y, w, h, fill=None, line=None, lw=0.75):
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, inch(x), inch(y), inch(w), inch(h))
    sh.shadow.inherit = False
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(lw)
    return sh


def hline(s, x1, y, x2, color=RULE, w=0.75):
    return rect(s, x1, y - w / 144, x2 - x1, w / 72, fill=color)


def vline(s, x, y1, y2, color=RULE, w=0.75):
    return rect(s, x - w / 144, y1, w / 72, y2 - y1, fill=color)


def arrow(s, x1, y1, x2, y2, color=INK, w=1.25):
    cn = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, inch(x1), inch(y1), inch(x2), inch(y2))
    cn.line.color.rgb = color
    cn.line.width = Pt(w)
    ln = cn.line._get_or_add_ln()
    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")
    return cn


def _fonts(run, face):
    rpr = run._r.get_or_add_rPr()
    for tag, f in (("a:latin", face), ("a:ea", "Yu Gothic"), ("a:cs", "Noto Naskh Arabic")):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", f)


def tx(s, x, y, w, h, text, size=14, font=SANS, color=INK, bold=False, italic=False, align="l", anchor="t",
       ls=1.18, after=0, track=0, upper=False, accent=DEEP):
    """A text box. Paragraphs split on newlines; **bold** and {{accent}} inline."""
    tb = s.shapes.add_textbox(inch(x), inch(y), inch(w), inch(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[align]
        p.line_spacing = ls
        p.space_after = Pt(after)
        for part in re.split(r"(\*\*.+?\*\*|\{\{.+?\}\})", line):
            if not part:
                continue
            b, col = bold, color
            if part.startswith("**"):
                part, b = part[2:-2], True
            elif part.startswith("{{"):
                part, col = part[2:-2], accent
            r = p.add_run()
            r.text = part.upper() if upper else part
            f = r.font
            f.size, f.bold, f.italic, f.color.rgb = Pt(size), b, italic, col
            f.name = font
            _fonts(r, font)
            if track:
                r._r.get_or_add_rPr().set("spc", str(int(track * 100)))
    return tb


def micro(s, x, y, w, text, color=MUTED, size=8.5, align="l", track=1.6, bold=False):
    return tx(s, x, y, w, 0.25, text, size=size, font=MONO, color=color, align=align, track=track, upper=True,
              bold=bold)


def pic(s, name, x, y, w=None, h=None):
    return s.shapes.add_picture(str(BRAND / name), inch(x), inch(y), inch(w) if w else None, inch(h) if h else None)


def notes(s, text):
    s.notes_slide.notes_text_frame.text = text


ROMAN = ["", "I", "II", "III", "IV"]
ACT = [0]


def new_slide(ground=PAPER):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = ground
    # a quiet fade between slides when presented
    tr = etree.SubElement(s._element, qn("p:transition"))
    tr.set("spd", "med")
    etree.SubElement(tr, qn("p:fade"))
    SLIDES.append(s)
    return s


def beam(s, x0, y0, x1, top, bottom, color):
    """The beacon's beam: one flat wedge from a point to a vertical edge."""
    ff = s.shapes.build_freeform(int(Inches(x0)), int(Inches(y0)), scale=1.0)
    ff.add_line_segments([(int(Inches(x1)), int(Inches(top))), (int(Inches(x1)), int(Inches(bottom)))], close=True)
    sh = ff.convert_to_shape()
    sh.shadow.inherit = False
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    return sh


def progress(s, x_right, y, on_navy=False):
    """Four squares, one per part; the current part in beacon gold."""
    for k in range(4, 0, -1):
        x = x_right - (5 - k) * 0.2
        cur = k == ACT[0]
        rect(s, x, y, 0.12, 0.12, fill=BEACON if cur else (MAST_RULE if on_navy else RULE))


def chrome(s, section, title, sub=None):
    """Running head, title and foot of an inside slide. Returns the y under the title block."""
    pic(s, "pharos-logo.png", M, 0.34, h=0.46)
    progress(s, SW - M - 0.12, 0.36)
    section = re.sub(r"^\d+\s*·\s*", "", section)
    micro(s, SW - M - 8, 0.6, 8, f"Part {ROMAN[ACT[0]]}  ·  {section}", color=INK, align="r")
    hline(s, M, 0.98, SW - M, INK, 0.9)
    rect(s, M, 0.98, 1.05, 0.05, fill=BEACON)
    tx(s, M, 1.22, CW, 0.7, title, size=29, font=SERIF, color=INK, ls=1.05)
    y = 1.86
    if sub:
        tx(s, M, y, 10.6, 0.6, sub, size=13.5, color=MUTED, ls=1.25)
        y += 0.62
    # foot
    hline(s, M, 7.02, SW - M, RULE)
    micro(s, M, 7.12, 7, f"PHAROS  ·  Pharmacovigilance inspection  ·  {DATE}", size=7.5)
    pic(s, "sato-pharma.png", SW / 2 - 0.36, 7.08, h=0.27)
    return y


def card(s, x, y, w, h, fill=SURF, top=INK):
    rect(s, x, y, w, h, fill=fill, line=RULE, lw=0.5)
    rect(s, x, y, w, 0.035, fill=top)


def drawing_mark(s, x, y, w):
    micro(s, x, y, w, "A drawing, not real data", color=DEEP, size=7.5, align="r")


# ───────── catalogue facts, read from the repository ─────────
CAT = yaml.safe_load((ROOT / "collectors" / "sources.yaml").read_text(encoding="utf-8"))
REG = CAT["regulators"]
NICE = {"BFARM": "BfArM", "LU_DPM": "DPM", "SWISSMEDIC": "Swissmedic", "MEDSAFE": "Medsafe",
        "INFARMED": "Infarmed", "FIMEA": "Fimea", "UAE_MOHAP": "MOHAP", "UAE_EDE": "EDE", "CBG": "CBG-MEB",
        "IMA": "IMA", "HC": "Health Canada"}
LOCAL = {"Egypt", "Saudi Arabia", "Jordan", "United Arab Emirates"}
INTL = {"International", "International (literature)"}


def by_country(names):
    out = {}
    for r in REG:
        if r["country_name"] in names:
            e = out.setdefault(r["country_name"], {"ids": [], "langs": []})
            e["ids"].append(NICE.get(r["id"], r["id"]))
            e["langs"] += [lg for lg in r["languages"] if lg not in e["langs"]]
    return out


ref_names = sorted({r["country_name"] for r in REG} - LOCAL - INTL - {"European Union"})
REFS = {"European Union": by_country({"European Union"})["European Union"]} | by_country(set(ref_names))
LOCALS = by_country(LOCAL)
LANGS = sorted({lg for r in REG for lg in r["languages"]})
assert len(REFS) == 25, f"Dr Sama's 25 reference countries: the catalogue now gives {len(REFS)}"
assert len(LANGS) == 15, f"15 languages: the catalogue now gives {len(LANGS)}"
N = 20  # slides

# The four parts: their titles, Dr Sama's line for each, and the slides inside with their page numbers.
PARTS = [
    ("How we screen", "Screening in two passes, vertical and horizontal, in every reference.",
     [("PHAROS at a glance", 4), ("The two passes", 5), ("Ingredients", 6), ("Literature", 7), ("Sources", 8)]),
    ("The evidence", "Evidence that we searched, including when the result was negative.",
     [("Evidence for negative results", 10), ("The five-day clock", 11), ("Reports", 12)]),
    ("Cases and quality", "The ICSR database, and one CAPA plan for deviations and audits.",
     [("The ICSR database", 14), ("Quality", 15)]),
    ("Control", "Who can do what, what can never change, and where our SOP stands.",
     [("People and integrity", 17), ("SOP and master file", 18)]),
]
DIVIDER_PAGE = {1: 3, 2: 9, 3: 13, 4: 16}


def foot_navy(s):
    hline(s, M, 7.02, SW - M, MAST_RULE)
    micro(s, M, 7.12, 7, f"PHAROS  ·  Pharmacovigilance inspection  ·  {DATE}", size=7.5, color=MAST_MUTED)


def divider(act):
    """A part's opening: navy, the beam, the part's numeral, its title and the slides inside."""
    ACT[0] = act
    title, line, items = PARTS[act - 1]
    s = new_slide(INK)
    assert len(SLIDES) == DIVIDER_PAGE[act], (act, len(SLIDES))
    beam(s, 0.07, 3.15, SW, 0.55, 6.55, MAST_RAISE)
    rect(s, 0, 0, 0.07, SH, fill=BEACON)
    micro(s, M + 0.15, 0.62, 5, f"Part {ROMAN[act]} of IV", color=BEACON, size=8)
    progress(s, SW - M - 0.12, 0.66, on_navy=True)
    tx(s, M + 0.05, 1.05, 4.2, 2.6, ROMAN[act], size=150, font=SERIF, color=BEACON, ls=0.9)
    X = 4.75
    tx(s, X, 1.55, SW - X - M, 1.6, title, size=44, font=SERIF, color=WHITE, ls=1.02, anchor="b")
    tx(s, X, 3.3, SW - X - M - 0.5, 0.8, line, size=15, color=MAST_MUTED, ls=1.3)
    for k, (name, page) in enumerate(items):
        yy = 4.35 + k * 0.42
        hline(s, X, yy, SW - M, MAST_RULE)
        tx(s, X, yy + 0.09, 6, 0.3, name, size=12.5, color=WHITE)
        micro(s, SW - M - 1.0, yy + 0.13, 1.0, f"{page:02d}", color=BEACON, align="r", size=8)
    hline(s, X, 4.35 + len(items) * 0.42, SW - M, MAST_RULE)
    foot_navy(s)
    pic(s, "sato-pharma-reverse.png", SW - M - 0.72, 7.08, h=0.27)
    notes(s, f"Part {ROMAN[act]}: {title}. {line}")
    return s


# ═════════ 01 COVER: the identity of PHAROS ═════════
s = new_slide(PAPER)
pic(s, "pharos-logo-stacked.png", 0.55, 1.05, w=6.6)
micro(s, M, 6.95, 6.4, "Sato Pharma  ·  Pharmacovigilance", size=8)
rect(s, 7.55, 0, SW - 7.55, SH, fill=INK)
# the logo's beam carries on across the navy, flat
beam(s, 7.62, 2.05, SW, 0.0, 4.05, MAST_RAISE)
rect(s, 7.55, 0, 0.07, SH, fill=BEACON)
X, WW = 8.15, 4.6
micro(s, X, 0.85, WW, "Pharmacovigilance inspection  ·  18 November 2026", color=BEACON, size=8)
tx(s, X, 1.25, WW, 1.6, "The computerised system and database", size=33, font=SERIF, color=WHITE, ls=1.04)
tx(s, X, 2.95, WW, 0.9, "Literature screening, the regulatory watch and the ICSR database of our "
   "pharmacovigilance, in one system.", size=13.5, color=MAST_MUTED, ls=1.3)
hline(s, X, 4.02, X + WW, MAST_RULE)
micro(s, X, 4.2, WW, "The name", color=BEACON, size=8)
tx(s, X, 4.5, WW, 1.4, "Pharos was the lighthouse of Alexandria, the light that brought every ship safely into "
   "harbour. PHAROS keeps that watch for us: over the regulators of 25 reference countries, the "
   "medical literature and our own reports.", size=12.5, font=SERIF, italic=True, color=WHITE, ls=1.35)
micro(s, X, 6.02, WW, "Presented by", color=MAST_MUTED, size=7.5)
tx(s, X, 6.28, WW, 0.35, "Dr Sama Mosaad", size=15, bold=True, color=WHITE)
tx(s, X, 6.62, 3.4, 0.3, "Qualified Person for Pharmacovigilance", size=11, color=MAST_MUTED)
pic(s, "sato-pharma-reverse.png", SW - M - 0.95, 6.6, h=0.36)
notes(s, "PHAROS: Pharmaceutical Alerts & Regulatory Observation System. This is the computerised system and "
      "database item of today's inspection. It does the hardest task we have, the literature screening, and it "
      "now holds our ICSRs as a database. I adopted it on 8 November 2026 for literature screening and retired "
      "the Excel sheet I kept for positive and negative results.")

# ═════════ CONTENTS ═════════
s = new_slide()
pic(s, "pharos-logo.png", M, 0.34, h=0.46)
hline(s, M, 0.98, SW - M, INK, 0.9)
rect(s, M, 0.98, 1.05, 0.05, fill=BEACON)
micro(s, M, 1.3, 4, "Contents", color=DEEP, bold=True)
tx(s, M, 1.62, 3.9, 2.6, "Four parts, then the system itself", size=34, font=SERIF, color=INK, ls=1.05)
tx(s, M, 3.85, 3.6, 1.6, "The computerised system and database of Sato Pharma's pharmacovigilance, presented by "
   "the QPPV.", size=12.5, color=MUTED, ls=1.35)
RX = 5.2
for k, (title, _line, items) in enumerate(PARTS):
    yy = 1.3 + k * 1.22
    hline(s, RX, yy, SW - M, INK if k == 0 else RULE, 0.9 if k == 0 else 0.6)
    tx(s, RX, yy + 0.12, 0.9, 0.7, ROMAN[k + 1], size=30, font=SERIF, color=DEEP, ls=1.0)
    tx(s, RX + 1.0, yy + 0.16, 5.2, 0.4, title, size=18, font=SERIF, color=INK)
    tx(s, RX + 1.0, yy + 0.58, 5.6, 0.6, "  ·  ".join(n for n, _ in items), size=10.5, color=MUTED, ls=1.3)
    micro(s, SW - M - 1.2, yy + 0.24, 1.2, f"{DIVIDER_PAGE[k + 1]:02d}–{items[-1][1]:02d}", color=INK,
          align="r", size=8)
yy = 1.3 + 4 * 1.22
hline(s, RX, yy, SW - M, RULE, 0.6)
tx(s, RX + 1.0, yy + 0.16, 5.2, 0.4, "Live demonstration", size=18, font=SERIF, color=INK)
micro(s, SW - M - 1.2, yy + 0.24, 1.2, "19", color=INK, align="r", size=8)
hline(s, RX, yy + 0.7, SW - M, INK, 0.9)
hline(s, M, 7.02, SW - M, RULE)
micro(s, M, 7.12, 7, f"PHAROS  ·  Pharmacovigilance inspection  ·  {DATE}", size=7.5)
pic(s, "sato-pharma.png", SW / 2 - 0.36, 7.08, h=0.27)
notes(s, "Four parts: how the system screens, the evidence it keeps, the ICSR database and quality, and the "
      "control around it. Then I show the system itself.")

divider(1)

# ═════════ 02 AT A GLANCE ═════════
s = new_slide()
y = chrome(s, "01  ·  PHAROS at a glance", "One system for the screening we do every day")
figs = [("25", "reference countries", "their regulators watched for us, with our local references added"),
        ("15", "languages", "each authority read as it publishes; nothing is translated"),
        ("2", "passes", "by active ingredient, and by authority, so one covers what the other misses"),
        ("0", "results recorded too", "a search that found nothing is kept: the evidence for negative results")]
fw = (CW - 3 * 0.35) / 4
for i, (n, a, b) in enumerate(figs):
    x = M + i * (fw + 0.35)
    hline(s, x, 2.3, x + fw, INK, 1.1)
    tx(s, x, 2.38, fw, 1.0, n, size=58, font=SERIF, color=INK if n != "0" else DEEP, ls=1.0)
    micro(s, x, 3.42, fw, a, color=INK, size=8.5, bold=True)
    tx(s, x, 3.72, fw, 0.8, b, size=11.5, color=MUTED, ls=1.28)
ty = 4.55
hline(s, M, ty, SW - M, INK, 0.9)
colw = (CW - 0.5) / 2
micro(s, M, ty + 0.14, colw, "Before", color=MUTED)
micro(s, M + colw + 0.5, ty + 0.14, colw, "With PHAROS", color=DEEP, bold=True)
rows = [("Each reference searched by hand, one ingredient at a time.",
         "Every reference read on schedule, in its own language."),
        ("Positive results kept in an Excel sheet, with their PDFs.",
         "Every result recorded, positive and negative, daily and weekly."),
        ("No record of a search that found nothing.",
         "Each check kept with its date, its count and an archive copy."),
        ("ICSRs in an Excel log.", "ICSRs in a database, sent as E2B or as the CIOMS I form.")]
for k, (a, b) in enumerate(rows):
    yy = ty + 0.44 + k * 0.46
    tx(s, M, yy, colw, 0.4, a, size=12, color=MUTED)
    tx(s, M + colw + 0.5, yy, colw, 0.4, b, size=12, color=INK)
    hline(s, M, yy + 0.39, SW - M, RULE, 0.5)
notes(s, "Before PHAROS, positive results were documented in an Excel sheet with their PDFs. We were also expected "
      "to document negative results, and that was the hard part: how do you document that you found nothing? "
      "PHAROS checks, finds zero, and records the zero, in the daily and in the weekly report, for each active "
      "ingredient on its own or across all of them.")

# ═════════ 03 HOW WE SCREEN: two passes ═════════
s = new_slide()
y = chrome(s, "02  ·  How we screen", "Screening in two passes: vertical and horizontal",
           "The way the screening was always done by hand, now done by the system.")
ings = ["Levofloxacin", "Lornoxicam", "Guaifenesin", "Carvedilol", "Ivabradine"]
auths = ["EMA", "FDA", "MHRA", "BfArM", "ANSM", "PMDA", "EDA", "NCBI"]
gx, gy, lw_, cw_, rh = M, 2.95, 1.45, 0.62, 0.52
tw = lw_ + cw_ * len(auths)
# horizontal pass: one authority (column), everything it newly published
ci = 2
rect(s, gx + lw_ + ci * cw_, gy - 0.42, cw_, 0.42 + rh * len(ings), fill=SEA_T)
# vertical pass: one ingredient (row), searched in every reference
ri = 0
rect(s, gx, gy + ri * rh, tw, rh, fill=BEACON_T)
for j, a in enumerate(auths):
    micro(s, gx + lw_ + j * cw_, gy - 0.3, cw_, a, color=INK, size=7.5, align="c", track=0.8)
hline(s, gx, gy, gx + tw, INK, 0.9)
for i, n in enumerate(ings):
    yy = gy + i * rh
    tx(s, gx + 0.08, yy + 0.14, lw_, 0.3, n, size=11.5, color=INK, bold=(i == ri))
    hline(s, gx, yy + rh, gx + tw, RULE, 0.5)
    for j in range(len(auths)):
        on = i == ri or j == ci
        rect(s, gx + lw_ + j * cw_ + cw_ / 2 - 0.05, yy + rh / 2 - 0.05, 0.1, 0.1,
             fill=(DEEP if i == ri else SEA) if on else RULE)
for j in range(len(auths) + 1):
    vline(s, gx + lw_ + j * cw_, gy, gy + rh * len(ings), RULE, 0.5)
gb = gy + rh * len(ings)
rect(s, gx, gb + 0.22, 0.16, 0.16, fill=DEEP)
tx(s, gx + 0.26, gb + 0.18, 4.5, 0.3, "Vertical: one ingredient, every reference", size=10.5, color=INK)
rect(s, gx, gb + 0.52, 0.16, 0.16, fill=SEA)
tx(s, gx + 0.26, gb + 0.48, 4.5, 0.3, "Horizontal: one authority, everything new", size=10.5, color=INK)
micro(s, gx + tw - 4, gb + 0.24, 4, "Shown: a few ingredients and references", size=7, color=MUTED, track=1.0,
      align="r")
px, pw = 7.55, SW - M - 7.55
card(s, px, 2.55, pw, 1.95, top=DEEP)
micro(s, px + 0.28, 2.75, pw, "Vertical pass  ·  Ingredients tab", color=DEEP, bold=True)
tx(s, px + 0.28, 3.05, pw - 0.56, 1.4, "We take each active ingredient of our products and search it in every "
   "reference: the regulators of the 25 reference countries, and NCBI on its own for the studies. PHAROS tells "
   "us whether any source, anywhere, mentioned it.", size=12, color=INK, ls=1.3)
card(s, px, 4.7, pw, 1.95, top=SEA)
micro(s, px + 0.28, 4.9, pw, "Horizontal pass  ·  Sources tab", color=SEA, bold=True)
tx(s, px + 0.28, 5.2, pw - 0.56, 1.4, "We take each reference authority and look at everything it newly "
   "published: a round-up, a safety alert, a new PDF. We look by eye for anything that concerns us. This "
   "covers what the vertical search may miss.", size=12, color=INK, ls=1.3)
notes(s, "I screen in two passes, vertical and horizontal. Vertical: I take one active ingredient of our products "
      "(levofloxacin, lornoxicam, guaifenesin) and search it in every reference, with the 25 reference countries, "
      "and NCBI separately because it holds the studies. Even a very good automated search can have pitfalls. "
      "What compensates is the horizontal search: I take each reference authority and look at everything newly "
      "published, to see whether anything concerns us. The Ingredients tab does the vertical search; the Sources "
      "tab does the horizontal one.")

# ═════════ 04 INGREDIENTS ═════════
s = new_slide()
y = chrome(s, "03  ·  Ingredients  ·  the vertical pass", "Each active ingredient, in every language, with its group",
           "Many class notices never name the ingredient: “fluoroquinolones” and not “levofloxacin”.")
cx, cy, cwd, chh = M, 2.75, 6.55, 3.95
card(s, cx, cy, cwd, chh)
drawing_mark(s, cx, cy - 0.27, cwd)
micro(s, cx + 0.3, cy + 0.25, 3, "Active ingredient", size=7.5)
tx(s, cx + 0.3, cy + 0.48, 4, 0.5, "Levofloxacin", size=24, font=SERIF, color=INK)
micro(s, cx + cwd - 3.3, cy + 0.3, 3.0, "Ready", color=SEA, align="r", bold=True)
kv = [("ATC code", "J01MA12"), ("Pharmacotherapeutic group", "Fluoroquinolones")]
for k, (a, b) in enumerate(kv):
    yy = cy + 1.15 + k * 0.42
    hline(s, cx + 0.3, yy, cx + cwd - 0.3, RULE, 0.5)
    micro(s, cx + 0.3, yy + 0.12, 2.4, a, size=7.5)
    tx(s, cx + 2.75, yy + 0.08, cwd - 3.1, 0.3, b, size=11.5, color=INK)
yy = cy + 2.0
hline(s, cx + 0.3, yy, cx + cwd - 0.3, RULE, 0.5)
micro(s, cx + 0.3, yy + 0.12, 2.4, "Names, 15 languages", size=7.5)
names = ("levofloxacin  ·  lévofloxacine  ·  Levofloxacin  ·  levofloxacino  ·  levofloxacina  ·  "
         "levofloksacin  ·  levofloksasiini  ·  レボフロキサシン  ·  레보플록사신  ·  ليفوفلوكساسين")
tx(s, cx + 2.75, yy + 0.08, cwd - 3.1, 1.2, names, size=11.5, color=INK, ls=1.45)
hline(s, cx + 0.3, cy + chh - 0.62, cx + cwd - 0.3, RULE, 0.5)
tx(s, cx + 0.3, cy + chh - 0.45, cwd - 0.6, 0.3, "Every notice in any of these words, or in the group's "
   "words, is matched.", size=10.5, color=MUTED, italic=True)
px, pw = 7.65, SW - M - 7.65
pts = [("The group is searched with the ingredient",
        "A notice about fluoroquinolones counts for levofloxacin, though it never names it."),
       ("Ready, or what is still being prepared",
        "Its names, its group, the check of the past, the literature look-back and its labels."),
       ("Nothing screened is ever deleted",
        "An ingredient taken off the list is paused, and its record stays.")]
for k, (a, b) in enumerate(pts):
    yy = 2.75 + k * 1.35
    hline(s, px, yy, px + pw, INK, 0.9)
    tx(s, px, yy + 0.14, pw, 0.4, a, size=13, bold=True, color=INK, ls=1.15)
    tx(s, px, yy + 0.62, pw, 0.7, b, size=11.5, color=MUTED, ls=1.3)
notes(s, "Putting the ATC code and the names in all these languages is very good. What I asked for on top: the "
      "search by active ingredient must include its pharmacotherapeutic group, for example levofloxacin with the "
      "fluoroquinolones, because many signals come out for fluoroquinolones without the active ingredient being "
      "named at all. PHAROS searches both.")

# ═════════ 05 LITERATURE ═════════
s = new_slide()
y = chrome(s, "04  ·  Literature", "Literature: global references and local references",
           "Every search is logged with its date and its count, including a count of zero.")
colw = (CW - 0.5) / 2
for k, (head, col, items) in enumerate([
    ("Global references", DEEP, [("PubMed and PubMed Central", "Through NCBI: both databases, not PubMed alone."),
                                 ("Europe PMC", "The European literature database."),
                                 ("Cochrane", "Counted through PubMed and Europe PMC by journal."),
                                 ("Medscape", "Checked by hand, and the check recorded.")]),
    ("Local references", SEA, [("The Egyptian medical journals", "Required by the EDA: Al-Azhar, Ain Shams and the "
                                "others, each check recorded."),
                               ("Egypt  ·  the Egyptian Drug Authority", "DHPC letters, safety alerts, awareness "
                                "letters."),
                               ("Saudi Arabia, Jordan, the United Arab Emirates", "Kept, read in Arabic."),
                               ("Added by the QPPV", "A local reference is added from the Sources tab.")])]):
    x = M + k * (colw + 0.5)
    hline(s, x, 2.62, x + colw, col, 2.2)
    tx(s, x, 2.75, colw, 0.45, head, size=17, font=SERIF, color=INK)
    for j, (a, b) in enumerate(items):
        yy = 3.3 + j * 0.82
        tx(s, x, yy, colw, 0.3, a, size=12.5, bold=True, color=INK)
        tx(s, x, yy + 0.32, colw, 0.45, b, size=11, color=MUTED, ls=1.25)
        hline(s, x, yy + 0.74, x + colw, RULE, 0.5)
notes(s, "NCBI holds more than PubMed: there is PubMed and there is PubMed Central, and PHAROS searches both. The "
      "global references are PubMed, PMC, Europe PMC, Cochrane and Medscape. The local references are the "
      "Egyptian medical journals the EDA asks for. Saudi Arabia and the Emirates stay as they are. With the local "
      "references added, the report gives the negative results for all of them.")

# ═════════ 06 SOURCES ═════════
s = new_slide()
y = chrome(s, "05  ·  Sources  ·  the horizontal pass", "Every reference authority, everything newly published",
           f"Each authority is read in its own language: {len(LANGS)} languages, nothing translated.")
gx, gy, cols = M, 2.62, 5
tw_, th_, gap = 1.47, 0.78, 0.07
order = ["European Union"] + [n for n in ref_names]
for k, name in enumerate(order):
    e = REFS[name]
    x = gx + (k % cols) * (tw_ + gap)
    yy = gy + (k // cols) * (th_ + gap)
    rect(s, x, yy, tw_, th_, fill=SURF, line=RULE, lw=0.5)
    rect(s, x, yy, tw_, 0.03, fill=INK)
    tx(s, x + 0.1, yy + 0.1, tw_ - 0.15, 0.3, name.replace("United ", "U. ") if len(name) > 15 else name,
       size=10, bold=True, color=INK)
    micro(s, x + 0.1, yy + 0.42, tw_ - 0.15, " · ".join(e["ids"]), size=6.5, track=0.6, color=MUTED)
    micro(s, x + 0.1, yy + 0.58, tw_ - 0.15, " ".join(e["langs"]), size=6.5, track=0.8, color=DEEP)
rx = gx + cols * (tw_ + gap) + 0.3
rw = SW - M - rx
micro(s, rx, 2.62, rw, "Local authorities", color=SEA, bold=True)
for k, (name, e) in enumerate(sorted(LOCALS.items())):
    yy = 2.92 + k * 0.36
    tx(s, rx, yy, 2.9, 0.3, name, size=11, color=INK)
    micro(s, rx + rw - 1.4, yy + 0.04, 1.4, " · ".join(e["ids"]), size=7, align="r", track=0.6)
    hline(s, rx, yy + 0.33, rx + rw, RULE, 0.5)
micro(s, rx, 4.48, rw, "International", color=SEA, bold=True)
tx(s, rx, 4.76, rw, 0.3, "World Health Organization  ·  medical product alerts", size=11, color=INK)
hline(s, rx, 5.08, rx + rw, RULE, 0.5)
card(s, rx, 5.3, rw, 1.42, fill=SURF2, top=BEACON)
tx(s, rx + 0.22, 5.46, rw - 0.44, 1.2, "The QPPV adds, changes or removes a link herself. Where a site cannot be "
   "read automatically, PHAROS says so, gives the reason, and the page is checked by hand.", size=11, color=INK,
   ls=1.3)
notes(s, "The Sources tab is the horizontal search. I want every newly published item from each reference: every "
      "new round-up, safety alert or PDF. PHAROS tells me something new came out and I look whether it concerns "
      "us. It shows how many runs it made and what it found, and it keeps the links of each reference country in "
      "order. I can now add or change a link, and add our local references, myself.")

divider(2)

# ═════════ 07 EVIDENCE FOR NEGATIVE RESULTS ═════════
s = new_slide()
y = chrome(s, "06  ·  Evidence for negative results", "It searched, and it found zero: that is recorded",
           "Positive results were always documented. The evidence that a search found nothing is now kept too.")
# the report page itself, lying on a second page
cols_ = [("Active ingredient", 1.3), ("Authority", 1.85), ("What was read", 2.15), ("Read", 1.05),
         ("Result", 2.3)]
tw_t = sum(w for _, w in cols_)
shx, shy, shw, shh = M, 2.55, tw_t + 0.5, 4.3
rect(s, shx + 0.1, shy + 0.1, shw, shh, fill=SURF2, line=RULE, lw=0.5)
rect(s, shx, shy, shw, shh, fill=SURF, line=RULE, lw=0.5)
tx_ = shx + 0.25
pic(s, "pharos-logo.png", tx_, shy + 0.2, h=0.3)
micro(s, shx + shw - 4.25, shy + 0.2, 4, "A drawing, not real data", color=DEEP, size=7, align="r")
micro(s, shx + shw - 4.25, shy + 0.4, 4, "Weekly report  ·  page 3 of 12", size=7, align="r")
tx(s, tx_, shy + 0.62, tw_t, 0.35, "Screening log  ·  week of Sunday 8 November 2026", size=14, font=SERIF,
   color=INK)
ty_ = shy + 1.08
rect(s, tx_, ty_, tw_t, 0.32, fill=INK)
xx = tx_
for h_, w_ in cols_:
    micro(s, xx + 0.1, ty_ + 0.1, w_, h_, color=WHITE, size=6.5, track=1.0)
    xx += w_
data = [("Levofloxacin", "MHRA  ·  United Kingdom", "Drug Safety Update, alerts", "7 of 7 days", "Nothing found"),
        ("Levofloxacin", "PMDA  ·  Japan", "Safety notices, Japanese", "7 of 7 days", "Nothing found"),
        ("Levofloxacin", "NCBI  ·  PubMed, PMC", "Search, with its count", "7 of 7 days", "0 new papers"),
        ("Lornoxicam", "ANSM  ·  France", "Safety notices, French", "7 of 7 days", "1 notice: not ours"),
        ("Guaifenesin", "FDA  ·  United States", "Drug Safety Communications", "7 of 7 days", "Nothing found"),
        ("Carvedilol", "EDA  ·  Egypt", "DHPC letters, safety alerts", "7 of 7 days", "Nothing found")]
for i, row in enumerate(data):
    yy = ty_ + 0.32 + i * 0.4
    if i % 2:
        rect(s, tx_, yy, tw_t, 0.4, fill=PAPER)
    xx = tx_
    for j, ((_, w_), v) in enumerate(zip(cols_, row, strict=True)):
        neg = j == 4 and v[0] in "N0"
        if j == 4:
            rect(s, xx + 0.1, yy + 0.16, 0.08, 0.08, fill=SEA if neg else BEACON)
        tx(s, xx + (0.26 if j == 4 else 0.1), yy + 0.11, w_ - 0.15, 0.3, v, size=10,
           color=SEA if neg else INK, bold=(j == 4))
        xx += w_
    hline(s, tx_, yy + 0.4, tx_ + tw_t, RULE, 0.5)
fy = ty_ + 0.32 + len(data) * 0.4 + 0.2
micro(s, tx_, fy, 5, "SHA-256  9c41 7e0b 2a55 … 52d1", color=DEEP, size=7, track=1.0)
micro(s, tx_ + tw_t - 3.5, fy, 3.5, "Signed  ·  Reviewed by the QPPV", size=7, align="r", track=1.0)
px = shx + shw + 0.5
pw = SW - M - px
pts = [("Daily and weekly", "For every active ingredient on its own, and across all of them."),
       ("Weekly, never monthly", "Some findings must reach the authority within five days."),
       ("Kept, unchangeable", "Every page read has an archive copy that nothing can overwrite or delete.")]
for k, (a, b) in enumerate(pts):
    yy = 2.55 + k * 1.42
    hline(s, px, yy, px + pw, INK, 0.9)
    tx(s, px, yy + 0.14, pw, 0.35, a, size=12.5, bold=True, color=INK)
    tx(s, px, yy + 0.52, pw, 0.75, b, size=11, color=MUTED, ls=1.28)
notes(s, "They ask me for evidence: that I went in, searched, and the result was negative. Before, I archived the "
      "positives; the negatives had no record. This is the point that only a database could close. PHAROS "
      "searches the regulatory sources and produces the negative result, in the daily report and in the weekly "
      "report, for each active ingredient. It took the burden of archiving negative results off me. The report "
      "is weekly, not monthly, because some findings are reported within five days.")

# ═════════ 08 WHEN A FINDING CONCERNS US ═════════
s = new_slide()
y = chrome(s, "07  ·  When a finding concerns us", "From a finding to the authority, within five days",
           "The clock counts from the day PHAROS first showed the notice.")
steps = [("01", "A new notice", "Matched to the ingredient, its group or one of its names."),
         ("02", "Our decision", "Concerns us, or doesn't concern us, with who decided and when."),
         ("03", "The five-day clock", "Due at the Egyptian Drug Authority on day five; late is shown in red."),
         ("04", "Sent to the authority", "The date sent and the reference are recorded; the clock stops.")]
sw_ = (CW - 3 * 0.45) / 4
for k, (n, a, b) in enumerate(steps):
    x = M + k * (sw_ + 0.45)
    card(s, x, 2.62, sw_, 1.9, top=DEEP if k == 2 else INK)
    tx(s, x + 0.22, 2.78, 1, 0.5, n, size=22, font=SERIF, color=DEEP)
    tx(s, x + 0.22, 3.32, sw_ - 0.44, 0.35, a, size=13.5, bold=True, color=INK)
    tx(s, x + 0.22, 3.7, sw_ - 0.44, 0.8, b, size=11, color=MUTED, ls=1.28)
    if k < 3:
        arrow(s, x + sw_ + 0.06, 3.57, x + sw_ + 0.39, 3.57, INK, 1.25)
# the clock drawn to scale: day 0 to day 5
bx, by, bw = M, 5.25, CW
micro(s, bx, by - 0.38, 6, "The clock, drawn to scale", color=INK, bold=True, size=7.5)
dw = bw / 6
for d in range(6):
    rect(s, bx + d * dw, by, dw - 0.04, 0.34, fill=SEA_T if d < 3 else (BEACON_T if d < 5 else BEACON))
    micro(s, bx + d * dw + 0.1, by + 0.1, dw, f"Day {d}", color=INK, size=7.5, track=1.0)
rect(s, bx + 3 * dw - 0.04, by - 0.12, 0.05, 0.58, fill=INK)
tx(s, bx, by + 0.5, 3 * dw, 0.5, "Day 0: the day PHAROS first showed the notice", size=10.5, color=MUTED)
tx(s, bx + 3 * dw - 1.0, by + 0.5, 2.6, 0.5, "Sent on day 3: clock stopped", size=10.5, color=INK, bold=True,
   align="c")
tx(s, bx + 5 * dw - 0.4, by + 0.5, dw + 0.4, 0.5, "Day 5: due", size=10.5, color=DEEP, bold=True, align="r")
notes(s, "Some findings must be reported within five days, which is why the report is weekly and not monthly. "
      "When a finding concerns us, PHAROS counts the five days from the day it first showed the notice, shows "
      "what is due and what is late, and records the day we sent it to the Egyptian Drug Authority and its "
      "reference. A decision can be changed; it is never erased.")

# ═════════ 10 REPORTS ═════════
s = new_slide()
y = chrome(s, "09  ·  Reports", "Reports the inspector can hold",
           "Every report is a PDF with its Excel workbook, made by PHAROS from the same records.")
cards = [("Weekly report", "Every Sunday", ["Every active ingredient, every authority",
                                            "Every zero result, with what was read",
                                            "Decisions and what went to the authority",
                                            "Possible case reports with their due dates"]),
         ("PSUR pack", "On request, any interval", ["Regulatory actions by country",
                                                    "Label changes, compared with our label",
                                                    "Literature, case reports first",
                                                    "The screening log of the interval"]),
         ("Inspection pack", "On request", ["Coverage: every page and how it is read",
                                            "The screening log, decisions, sign-offs",
                                            "Reports to the authority",
                                            "Quality: deviations, audits, CAPA plan"])]
cwk = (CW - 2 * 0.4) / 3
for k, (a, when, items) in enumerate(cards):
    x = M + k * (cwk + 0.4)
    card(s, x, 2.62, cwk, 3.0)
    micro(s, x + 0.28, 2.82, cwk, when, color=DEEP, bold=True)
    tx(s, x + 0.28, 3.1, cwk - 0.5, 0.5, a, size=19, font=SERIF, color=INK)
    for j, it in enumerate(items):
        yy = 3.72 + j * 0.45
        hline(s, x + 0.28, yy, x + cwk - 0.28, RULE, 0.5)
        tx(s, x + 0.28, yy + 0.1, cwk - 0.56, 0.32, it, size=11, color=INK)
rect(s, M, 5.88, CW, 0.82, fill=INK)
rect(s, M, 5.88, 0.07, 0.82, fill=BEACON)
tx(s, M + 0.35, 6.02, CW - 0.6, 0.6, "Each file carries its SHA-256 fingerprint and can be signed as Reviewed or "
   "Approved. The history of every record is kept, and nobody can change it.", size=12.5, color=WHITE, ls=1.3,
   anchor="m")
notes(s, "Reports are weekly, not monthly. For the master file the report has to be weekly. A PSUR pack and an "
      "inspection pack can be asked for from the Reports tab, for any interval, and are built within hours. Each "
      "file has a fingerprint that proves it was not changed, and each can be signed.")

divider(3)

# ═════════ 09 THE ICSR DATABASE ═════════
s = new_slide()
y = chrome(s, "08  ·  Cases", "The ICSR database",
           "ICSRs were kept in an Excel log, an approved alternative while our numbers are low. "
           "Now every ICSR is in a database.")
steps = [("01", "New case", "Opened from the Cases tab, numbered, dated."),
         ("02", "The CIOMS form", "Dropped into the case; PHAROS reads it into the case's fields."),
         ("03", "Our product", "From the product list, with its strength: carvedilol with ivabradine."),
         ("04", "MedDRA coding", "From the company's MedDRA subscription, once its files are loaded."),
         ("05", "Sent", "As an E2B (R3) file; as the CIOMS I form until MedDRA arrives.")]
# left: the five steps, one under the other
lw5 = 5.75
for k, (n, a, b) in enumerate(steps):
    yy = 2.62 + k * 0.84
    hline(s, M, yy, M + lw5, INK if k == 0 else RULE, 0.9 if k == 0 else 0.5)
    tx(s, M, yy + 0.12, 0.7, 0.5, n, size=19, font=SERIF, color=DEEP, ls=1.0)
    tx(s, M + 0.75, yy + 0.12, lw5 - 0.75, 0.3, a, size=13, bold=True, color=INK)
    tx(s, M + 0.75, yy + 0.42, lw5 - 0.75, 0.4, b, size=10.5, color=MUTED, ls=1.25)
hline(s, M, 2.62 + 5 * 0.84, M + lw5, RULE, 0.5)
# right: the case as it stands in the database
cx5 = M + lw5 + 0.6
cw5 = SW - M - cx5
cy5 = 2.62
drawing_mark(s, cx5, cy5 - 0.3, cw5)
rect(s, cx5, cy5, cw5, 4.2, fill=SURF, line=RULE, lw=0.5)
rect(s, cx5, cy5, cw5, 0.62, fill=INK)
rect(s, cx5, cy5 + 0.62, cw5, 0.04, fill=BEACON)
micro(s, cx5 + 0.25, cy5 + 0.13, 3, "Case", color=MAST_MUTED, size=7)
tx(s, cx5 + 0.25, cy5 + 0.3, 3, 0.3, "2026-0007", size=13, bold=True, color=WHITE)
micro(s, cx5 + cw5 - 3.25, cy5 + 0.24, 3, "Open  ·  non-serious", color=BEACON, size=7.5, align="r")
fields = [("Received", "Monday 9 November 2026  ·  CIOMS form, PDF"),
          ("Product", "Carvedilol 6.25 mg with ivabradine 5 mg"),
          ("Reaction", "Coded to a MedDRA preferred term"),
          ("Reporter", "Health care professional, Egypt"),
          ("Due", "Day 0: 9 Nov  ·  90 days: Sunday 7 February 2027")]
for k, (a, b) in enumerate(fields):
    yy = cy5 + 0.84 + k * 0.5
    micro(s, cx5 + 0.25, yy + 0.06, 1.4, a, size=7)
    tx(s, cx5 + 1.65, yy, cw5 - 1.9, 0.35, b, size=11, color=INK)
    hline(s, cx5 + 0.25, yy + 0.4, cx5 + cw5 - 0.25, RULE, 0.5)
micro(s, cx5 + 0.25, cy5 + 3.47, 2, "Send as", size=7)
for k, f in enumerate(["E2B (R3) file", "CIOMS I form"]):
    fx = cx5 + 1.65 + k * 1.75
    rect(s, fx, cy5 + 3.38, 1.6, 0.42, fill=SEA_T if k == 0 else BEACON_T, line=SEA if k == 0 else DEEP, lw=0.75)
    tx(s, fx, cy5 + 3.38, 1.6, 0.42, f, size=10.5, bold=True, color=SEA if k == 0 else DEEP, align="c",
       anchor="m")
notes(s, "The ICSRs. We were expected to have a database for them, but as our ICSRs are few, I kept an Excel sheet "
      "as an approved alternative. Now there is a Cases tab: New case, I put in the CIOMS form, it reads it, and "
      "with the MedDRA subscription it turns it into E2B, the format that goes straight into the global "
      "databases. The product list knows that a product can hold two active ingredients, carvedilol with "
      "ivabradine, and its strengths, so each case names the exact product. I will not show the old Excel sheet.")

# ═════════ 11 QUALITY ═════════
s = new_slide()
y = chrome(s, "10  ·  Quality", "A CAPA comes from a deviation, or from an audit",
           "Both end in one CAPA plan. PV-SOP-024, the Quality Management System, is the overview of both.")
bx_, bw_, bh_ = M, 4.15, 1.6
for k, (sop, a, b) in enumerate([
    ("PV-SOP-021", "Deviation", "A mistake happened. Level 1, 2 or 3; investigated; its root cause found; "
                                "approved by the QA manager."),
    ("PV-SOP-022", "Audit observation", "Internal, every last quarter, or external. Critical, major or minor; "
                                        "deadlines from day 1 to day 14.")]):
    yy = 2.55 + k * (bh_ + 0.25)
    card(s, bx_, yy, bw_, bh_)
    micro(s, bx_ + 0.25, yy + 0.2, 2, sop, color=DEEP, bold=True)
    tx(s, bx_ + 0.25, yy + 0.45, bw_ - 0.5, 0.4, a, size=16, font=SERIF, color=INK)
    tx(s, bx_ + 0.25, yy + 0.88, bw_ - 0.5, 0.7, b, size=10.5, color=MUTED, ls=1.25)
cx_, cyc, cw2, ch2 = 5.6, 3.2, 3.2, 1.75
for k in range(2):
    yy = 2.55 + k * (bh_ + 0.25) + bh_ / 2
    arrow(s, bx_ + bw_ + 0.05, yy, cx_ - 0.06, cyc + ch2 / 2 + (k - 0.5) * 0.6, INK, 1.25)
rect(s, cx_, cyc, cw2, ch2, fill=INK)
rect(s, cx_, cyc + ch2 - 0.05, cw2, 0.05, fill=BEACON)
micro(s, cx_ + 0.25, cyc + 0.25, cw2, "One plan", color=BEACON, bold=True)
tx(s, cx_ + 0.25, cyc + 0.5, cw2 - 0.5, 0.5, "The CAPA plan", size=21, font=SERIF, color=WHITE)
tx(s, cx_ + 0.25, cyc + 1.05, cw2 - 0.5, 0.6, "Corrective and preventive action, owner, due date, evidence.",
   size=10.5, color=MAST_MUTED, ls=1.25)
ex = cx_ + cw2 + 0.5
arrow(s, cx_ + cw2 + 0.06, cyc + ch2 / 2, ex - 0.06, cyc + ch2 / 2, INK, 1.25)
ew = SW - M - ex
card(s, ex, cyc, ew, ch2, top=SEA)
micro(s, ex + 0.25, cyc + 0.25, ew, "Until", color=SEA, bold=True)
tx(s, ex + 0.25, cyc + 0.5, ew - 0.5, 0.5, "Effective", size=21, font=SERIF, color=INK)
tx(s, ex + 0.25, cyc + 1.05, ew - 0.5, 0.6, "Not effective sends it back. A deviation closes when every CAPA "
   "of it is effective.", size=10.5, color=MUTED, ls=1.25)
hline(s, M, 6.25, SW - M, RULE, 0.5)
tx(s, M, 6.38, CW, 0.5, "The 07:00 morning message lists the CAPAs and audit deadlines that are due or late. "
   "Nothing is deleted; every step is kept in a history nobody can change.", size=11.5, color=INK)
notes(s, "To keep things organised: a CAPA comes from one of two places. Either a mistake happened, a deviation, "
      "and we make a CAPA plan to correct it; or an observation came out of an audit, and we make a CAPA for it. "
      "Each has its SOP, and both end in the same place: we prepare a CAPA. The QMS SOP is short; it is an "
      "overview of the same process written in the deviation and the audit SOPs.")

divider(4)

# ═════════ 12 PEOPLE, ACCESS, INTEGRITY ═════════
s = new_slide()
y = chrome(s, "11  ·  People and integrity", "Who can do what, and what can never change")
cols3 = [("People and roles", ["Each person signs in with their own account",
                               "Readers see everything and change nothing",
                               "Reviewers decide; administrators add people and sources",
                               "Linked people get the morning message on Telegram"]),
         ("Records that stay", ["Every page read is archived by its fingerprint",
                                "The archive cannot be overwritten or deleted",
                                "Every decision and change kept with who and when",
                                "An encrypted copy of the database every night"]),
         ("Where it opens", ["In the browser, on the laptop and the phone",
                             "Installs as an application on the taskbar",
                             "Every time shown in Cairo time",
                             "The handbook describes every screen"])]
cwk = (CW - 2 * 0.45) / 3
for k, (a, items) in enumerate(cols3):
    x = M + k * (cwk + 0.45)
    hline(s, x, 2.3, x + cwk, INK, 1.1)
    tx(s, x, 2.42, cwk, 0.45, a, size=18, font=SERIF, color=INK)
    for j, it in enumerate(items):
        yy = 3.08 + j * 0.86
        rect(s, x, yy + 0.1, 0.09, 0.09, fill=BEACON if k == 1 else INK)
        tx(s, x + 0.25, yy, cwk - 0.25, 0.7, it, size=12.5, color=INK, ls=1.25)
        hline(s, x, yy + 0.72, x + cwk, RULE, 0.5)
notes(s, "I installed it as an application and pinned it to my taskbar; on the phone it opens just as fast. Every "
      "person has a role; readers can see everything but change nothing. Everything PHAROS reads is archived and "
      "cannot be altered, and the history of every decision is kept.")

# ═════════ 13 WHERE IT STANDS ═════════
s = new_slide()
y = chrome(s, "12  ·  SOP and master file", "In use now; our SOP and master file follow",
           "The process is new, so it is not yet in the master file or an SOP. Until the new SOP is approved, the "
           "current one stands.")
tl = [("5 Nov 2026", "Defined", "The QPPV sets the two passes: vertical by ingredient, horizontal by authority."),
      ("8 Nov 2026", "Adopted", "For literature screening. The Excel sheets retired; the ICSRs move to the database."),
      ("9 Nov 2026", "Quality", "Deviations, audits and one CAPA plan, from PV-SOP-021, 022 and 024."),
      ("18 Nov 2026", "Today", "Presented as the computerised system and database."),
      ("Next", "Written in", "The literature-screening SOP and the PV master file describe PHAROS.")]
lx, ly = M, 3.35
hline(s, lx, ly, SW - M, INK, 1.1)
sw_ = CW / 5
for k, (d, a, b) in enumerate(tl):
    x = lx + k * sw_
    rect(s, x, ly - 0.09, 0.18, 0.18, fill=DEEP if a == "Today" else (SURF if d == "Next" else INK),
         line=INK if d == "Next" else None, lw=1)
    micro(s, x, ly - 0.55, sw_, d, color=DEEP if a == "Today" else MUTED, bold=a == "Today")
    tx(s, x, ly + 0.3, sw_ - 0.3, 0.4, a, size=17, font=SERIF, color=INK)
    tx(s, x, ly + 0.82, sw_ - 0.3, 1.3, b, size=11, color=MUTED, ls=1.3)
card(s, M, 5.8, CW, 0.78, fill=SURF2, top=BEACON)
tx(s, M + 0.3, 6.02, CW - 0.6, 0.8, "The PHAROS handbook describes each screen in words that can be "
   "lifted into the SOP and the master file.", size=12.5, color=INK, ls=1.3)
notes(s, "I will write the literature-screening SOP from the handbook: how the process was done, and how we now use "
      "the system. I cannot change the SOP before the inspection, as the inspector already holds the current one; "
      "so I present PHAROS as our upcoming literature-screening process, at the item of the computerised system "
      "and database. It is new, so it is not yet reflected in the master file or an SOP; that follows.")

# ═════════ 14 LIVE DEMONSTRATION ═════════
s = new_slide(PAPER)
pic(s, "pharos-logo-stacked.png", 0.75, 1.55, w=5.6)
rect(s, 7.0, 0, SW - 7.0, SH, fill=INK)
beam(s, 7.07, 2.4, SW, 0.6, 4.2, MAST_RAISE)
rect(s, 7.0, 0, 0.07, SH, fill=BEACON)
X, WW = 7.6, SW - 7.6 - M
micro(s, X, 0.85, WW, "Now, on the system itself", color=BEACON, size=8)
tx(s, X, 1.2, WW, 0.9, "Live demonstration", size=36, font=SERIF, color=WHITE)
tabs = [("Ingredients", "the vertical pass"), ("Sources", "the horizontal pass"),
        ("Reports", "the weekly report, the packs"), ("Cases", "the ICSR database"),
        ("Quality", "deviations, audits, CAPA")]
for k, (a, b) in enumerate(tabs):
    yy = 2.45 + k * 0.72
    hline(s, X, yy, X + WW, MAST_RULE)
    micro(s, X, yy + 0.24, 0.6, f"{k + 1:02d}", color=BEACON, size=8)
    tx(s, X + 0.65, yy + 0.15, 2.2, 0.4, a, size=17, font=SERIF, color=WHITE)
    tx(s, X + 2.45, yy + 0.21, WW - 2.45, 0.4, b, size=11.5, color=MAST_MUTED)
hline(s, X, 2.45 + 5 * 0.72, X + WW, MAST_RULE)
tx(s, X, 6.3, 3.6, 0.3, "Dr Sama Mosaad  ·  QPPV", size=12, bold=True, color=WHITE)
pic(s, "sato-pharma-reverse.png", SW - M - 0.95, 6.25, h=0.36)
micro(s, 0.75, 6.95, 6, "Sato Pharma  ·  Pharmacovigilance", size=8)
notes(s, "The laptop is connected to the projector. I show the system and its features after the data is in: "
      "the Ingredients and Sources tabs, a weekly report with its zero results, the Cases tab with our ICSRs, "
      "and the Quality tab.")

# ═════════ CLOSING ═════════
s = new_slide(PAPER)
pic(s, "pharos-logo-stacked.png", SW / 2 - 2.55, 0.55, w=5.1)
tx(s, M, 4.15, CW, 0.7, "Thank you", size=40, font=SERIF, color=INK, align="c")
micro(s, M, 4.95, CW, "Questions are welcome", color=DEEP, align="c", size=8.5)
hline(s, SW / 2 - 0.6, 5.42, SW / 2 + 0.6, BEACON, 2.2)
tx(s, M, 5.65, CW, 0.35, "Dr Sama Mosaad  ·  Qualified Person for Pharmacovigilance", size=13, color=INK,
   align="c")
micro(s, M, 6.05, CW, f"Sato Pharma  ·  Pharmacovigilance inspection  ·  {DATE}", align="c", size=7.5)
rect(s, 0, SH - 0.5, SW, 0.5, fill=INK)
rect(s, 0, SH - 0.53, SW, 0.035, fill=BEACON)
pic(s, "sato-pharma-reverse.png", SW / 2 - 0.42, SH - 0.42, h=0.32)
notes(s, "Thank you. I am glad to take any questions, and to show any part of the system again.")

# page numbers on the inside slides (not the cover, the parts' openings, the demonstration or the close)
SKIP = {1, *DIVIDER_PAGE.values(), N - 1, N}
for i, s in enumerate(SLIDES, start=1):
    if i not in SKIP:
        micro(s, SW - M - 2, 7.12, 2, f"{i:02d} / {N:02d}", size=7.5, align="r")
assert len(SLIDES) == N, len(SLIDES)
prs.save(OUT)
print("wrote", OUT, len(SLIDES), "slides")
