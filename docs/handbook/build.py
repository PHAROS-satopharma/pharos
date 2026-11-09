"""The PHAROS handbook, edition 4 (November 2026): the two-pass screening method, and what follows a finding.

Written for Dr Sama Mosaad (QPPV, administrator) so its pages can be lifted into her SOP and the
pharmacovigilance system master file. Every screen it describes is the app as it stands in November 2026:
Ingredients (the vertical pass, with readiness, case reports and our label), what follows a finding that concerns
us (the five-day clock to the Egyptian Drug Authority and the signal steps), Sources (the horizontal pass and the
literature references), Products and Cases, Reports (daily and weekly, fingerprints and signatures, packs on
request), Telegram, People and Me, and a page for the SOP (with deviations, audits and CAPA).

    python build.py ["PHAROS Handbook.pdf"]

Every page ends with check(), which stops the build when a page runs into its foot.
"""
import sys
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from kit import *

OUT = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("PHAROS Handbook.pdf"))
TOTAL = 22
BOTTOM = 19 * mm
report = []
DANGER = HexColor("#A8322D")
MARK = HexColor("#F6DC9F")
NAVY_RULE = HexColor("#23446F")

tiny = ParagraphStyle("tiny", parent=body, fontSize=8, leading=11, textColor=MUTED)
ink_tiny = ParagraphStyle("ink_tiny", parent=tiny, textColor=INK)
step_st = ParagraphStyle("step", parent=body, fontSize=8.5, leading=11.8, textColor=INK)
what_st = ParagraphStyle("what", parent=body, fontName="Serif-I", fontSize=9.6, leading=13.4, textColor=SEA)
cell_st = ParagraphStyle("cell", parent=body, fontSize=7.9, leading=10.6, textColor=INK)
cell_b = ParagraphStyle("cell_b", parent=cell_st, fontName="Sans-B")
ntitle = ParagraphStyle("ntitle", parent=body, fontName="Sans-B", fontSize=8.6, leading=11, textColor=INK)


PAGE = 0


def new_page(label_):
    """Start the next page: its paper, foot and page number."""
    global PAGE
    PAGE += 1
    page_furniture(c, PAGE, TOTAL, label_)


def check(page, y):
    report.append(f"page {page}: {round((y - BOTTOM) / mm, 1)} mm spare")
    if y < BOTTOM:
        raise SystemExit(f"page {page} overflows by {round((BOTTOM - y) / mm, 1)} mm")


def ptext(text, style, width):
    p = Paragraph(text, style)
    return p, p.wrap(width, 2000)[1]


def centred(c, text, font, size, y, color=INK):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawCentredString(W / 2, y, text)


def label(c, text, y, x=ML, color=INK):
    micro(c, text, x, y - 6, color=color, size=6.8)
    return y - 12


def tag(c, cx, cy, letter):
    c.setFillColor(INK)
    c.circle(cx, cy, 2.3 * mm, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.setFont("Sans-B", 7.4)
    c.drawCentredString(cx, cy - 2.6, letter)


def head(c, num, title, y, sub=None):
    """Section head inside a page: serif numeral, serif title, ink rule."""
    c.setFillColor(DEEP)
    c.setFont("Serif", 18)
    c.drawString(ML, y - 15, num)
    c.setFillColor(INK)
    c.setFont("Serif-B", 14)
    c.drawString(ML + (11 * mm if num else 0), y - 14, title)
    if sub:
        micro(c, sub, W - MR, y - 13, align="right")
    rule(c, ML, y - 20, W - MR, INK, 0.8)
    return y - 27


def steps(c, items, x, y, w, numw=6.5 * mm, gap=1.8 * mm, start=1):
    for i, t in enumerate(items, start):
        p, h = ptext(t, step_st, w - numw)
        c.setFillColor(DEEP)
        c.setFont("Serif-B", 10.5)
        c.drawString(x, y - 9.6, str(i))
        p.drawOn(c, x + numw, y - h)
        y -= h + gap
    return y


def frame(c, x, y, w, h):
    c.setFillColor(WHITE)
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.rect(x, y - h, w, h, stroke=1, fill=1)


def button(c, x, y, text, dark=True, size=6.8):
    """A button whose right edge is at x and top at y; returns its width."""
    w = pdfmetrics.stringWidth(text, "Sans-B", size) + 6 * mm
    c.setFillColor(INK if dark else WHITE)
    c.setStrokeColor(INK)
    c.setLineWidth(0.6)
    c.rect(x - w, y - 5.6 * mm, w, 5.6 * mm, stroke=0 if dark else 1, fill=1)
    c.setFillColor(WHITE if dark else INK)
    c.setFont("Sans-B", size)
    c.drawString(x - w + 3 * mm, y - 3.8 * mm, text)
    return w


def lbutton(c, x, y, text, dark=False, size=6.2, h=5 * mm):
    """A button whose LEFT edge is at x and top at y; returns its width."""
    w = pdfmetrics.stringWidth(text, "Sans-B", size) + 4.4 * mm
    c.setFillColor(INK if dark else WHITE)
    c.setStrokeColor(INK)
    c.setLineWidth(0.6)
    c.rect(x, y - h, w, h, stroke=0 if dark else 1, fill=1)
    c.setFillColor(WHITE if dark else INK)
    c.setFont("Sans-B", size)
    c.drawString(x + 2.2 * mm, y - h / 2 - size * 0.35, text)
    return w


def switch(c, x, y, on=True):
    c.setFillColor(SEA if on else RULE)
    c.rect(x, y, 6.4 * mm, 3.2 * mm, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.rect(x + (3.6 if on else 0.4) * mm, y + 0.4 * mm, 2.4 * mm, 2.4 * mm, stroke=0, fill=1)


def dot(c, x, y, color, hollow=False):
    if hollow:
        c.setStrokeColor(INK)
        c.setLineWidth(0.6)
        c.rect(x, y, 2 * mm, 2 * mm, stroke=1, fill=0)
    else:
        c.setFillColor(color)
        c.rect(x, y, 2 * mm, 2 * mm, stroke=0, fill=1)


def bars(c, x, y, w, color=RULE):
    c.setFillColor(color)
    c.rect(x, y, w, 1.6 * mm, stroke=0, fill=1)


def text(c, s, x, y, font="Sans", size=6.6, color=INK):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, s)
    return pdfmetrics.stringWidth(s, font, size)


def chip(c, x, y, s, size=5.6, fill=SURFACE2, color=INK):
    """A flat label (no border, no badge-on-badge); x, y is its lower left; returns its width."""
    w = pdfmetrics.stringWidth(s, "Sans-B", size) + 2.4 * mm
    c.setFillColor(fill)
    c.rect(x, y, w, 3.2 * mm, stroke=0, fill=1)
    text(c, s, x + 1.2 * mm, y + 0.95 * mm, "Sans-B", size, color)
    return w


def legend(c, items, y, cols):
    cw = CW / cols
    hmax = 0
    for i, (L, t, s) in enumerate(items):
        x = ML + i * cw
        tag(c, x + 2.3 * mm, y - 2.6 * mm, L)
        c.setFillColor(INK)
        c.setFont("Sans-B", 8.4)
        c.drawString(x + 7 * mm, y - 3.6 * mm, t)
        p, ph = ptext(s, tiny, cw - 9 * mm)
        p.drawOn(c, x + 7 * mm, y - 5 * mm - ph)
        hmax = max(hmax, 5 * mm + ph)
    return y - hmax


def notes_row(c, items, y, cols, gap=6 * mm, x0=ML, width=CW, style=tiny):
    """Columns, each under an ink rule: a bold title and a few lines."""
    cw = (width - gap * (cols - 1)) / cols
    hmax = 0
    for i, (t, s) in enumerate(items):
        x = x0 + i * (cw + gap)
        rule(c, x, y, x + cw, INK, 0.8)
        pt, th = ptext(t, ntitle, cw)
        pt.drawOn(c, x, y - 1.6 * mm - th)
        p, ph = ptext(s, style, cw)
        p.drawOn(c, x, y - 2.8 * mm - th - ph)
        hmax = max(hmax, 2.8 * mm + th + ph)
    return y - hmax


def table(c, rows, y, widths, header=None, x0=ML, styles=None, pad=1.5 * mm):
    """Rows of paragraphs under a micro header; a hairline under every row."""
    total = sum(widths)
    if header:
        x = x0
        for h_, w_ in zip(header, widths, strict=True):
            micro(c, h_, x, y - 5, size=5.8, spacing=0.8)
            x += w_
        y -= 3.4 * mm
        rule(c, x0, y, x0 + total, INK, 0.8)
    for row in rows:
        cells = []
        hmax = 0
        for k, (t, w_) in enumerate(zip(row, widths, strict=True)):
            st = (styles or [cell_st] * len(widths))[k]
            p, ph = ptext(t, st, w_ - 2.4 * mm)
            cells.append(p)
            hmax = max(hmax, ph)
        x = x0
        for p, w_ in zip(cells, widths, strict=True):
            p.drawOn(c, x, y - pad - p.height)
            x += w_
        y -= hmax + 2 * pad
        rule(c, x0, y, x0 + total, RULE)
    return y


def sub_head(c, title, y, aside=None):
    """A small head inside a section: bold title over a hairline."""
    c.setFillColor(INK)
    c.setFont("Serif-B", 11)
    c.drawString(ML, y - 10, title)
    if aside:
        micro(c, aside, W - MR, y - 9, align="right")
    rule(c, ML, y - 14, W - MR, RULE)
    return y - 19


def screen_sec(c, x, y, w, num, title, n=None):
    """A section head as the app draws it: number, title, count, hairline."""
    micro(c, f"{num}  {title}", x, y - 2.4 * mm, size=5.6, spacing=0.7, color=INK)
    if n is not None:
        micro(c, n, x + w, y - 2.4 * mm, size=5.6, spacing=0.7, align="right")
    rule(c, x, y - 3.6 * mm, x + w, RULE)
    return y - 6 * mm


def navy_band(c, y, title, lines, gap=6.4 * mm, size=10.2):
    band_h = 12 * mm + len(lines) * gap
    c.setFillColor(INK)
    c.rect(ML, y - band_h, CW, band_h, stroke=0, fill=1)
    c.setFillColor(BEACON)
    c.rect(ML, y - 1.1 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
    micro(c, title, ML + 7 * mm, y - 7 * mm, color=BEACON, size=6.8)
    ry = y - 13.5 * mm
    for i, t in enumerate(lines):
        c.setFillColor(BEACON)
        c.setFont("Serif-B", 10)
        c.drawString(ML + 7 * mm, ry - 1, str(i + 1))
        c.setFillColor(WHITE)
        c.setFont("Serif", size)
        c.drawString(ML + 14 * mm, ry - 1, t)
        ry -= gap
    return y - band_h


c = canvas.Canvas(OUT, pagesize=A4)
c.setTitle("The PHAROS Handbook")
c.setAuthor("Sato Pharma")
c.setSubject("Screening with PHAROS: the vertical pass by ingredient, the horizontal pass by authority, the "
             "five-day clock, the signal steps, the weekly report and the evidence for inspection")
c.setCreator("Sato Pharma")
c.setKeywords("PHAROS, pharmacovigilance, screening, safety notifications, weekly report, handbook")
c._doc.info.producer = "Sato Pharma"

# ═════════════════════════ PAGE 1 · COVER, NAME, ENGINE ═════════════════════════
new_page("The idea")
c.setStrokeColor(INK)
c.setLineWidth(0.7)
c.rect(5 * mm, 5 * mm, W - 10 * mm, H - 10 * mm, stroke=1, fill=0)
c.setStrokeColor(DEEP)
c.setLineWidth(0.3)
c.rect(6.4 * mm, 6.4 * mm, W - 12.8 * mm, H - 12.8 * mm, stroke=1, fill=0)
micro(c, "Sato Pharma  ·  Pharmacovigilance", ML, H - 16 * mm, color=INK)
micro(c, "Handbook  ·  Edition 4  ·  November 2026", W - MR, H - 16 * mm, align="right")
rule(c, ML, H - 19.5 * mm, W - MR, INK, 0.8)

lw = 84 * mm
lh = lw * 983 / 1520
c.drawImage(BRAND + "pharos-logo-stacked.png", W / 2 - lw / 2, H - 25 * mm - lh, width=lw, height=lw * 1024 / 1536,
            mask="auto")
y = H - 25 * mm - lh - 8 * mm
centred(c, "The PHAROS Handbook", "Serif-B", 30, y - 22)
y -= 33
centred(c, "Screening by ingredient and by authority, what follows a finding, and the record", "Serif-I", 12, y - 10,
        MUTED)
y -= 19
c.setFillColor(BEACON)
c.rect(W / 2 - 9 * mm, y - 1, 18 * mm, 1.1 * mm, stroke=0, fill=1)
y -= 10 * mm
centred(c, "Prepared for", "Serif-I", 9.5, y, MUTED)
centred(c, "Dr Sama Mosaad", "Script", 30, y - 13 * mm)
centred(c, "Qualified Person for Pharmacovigilance  ·  Administrator of PHAROS", "Sans", 8, y - 19.5 * mm, DEEP)
y -= 28 * mm

# where the name comes from
rule(c, ML, y, W - MR, INK, 0.8)
c.setFillColor(INK)
c.setFont("Serif-B", 14)
c.drawString(ML, y - 8.2 * mm, "Where the name PHAROS comes from")
micro(c, "Alexandria, Egypt", W - MR, y - 7.8 * mm, align="right")
y -= 14 * mm
lcw = 56 * mm
c.setFillColor(INK)
c.setFont("Serif", 34)
c.drawString(ML, y - 11 * mm, "Φάρος")
c.setFillColor(MUTED)
c.setFont("Serif-I", 8.6)
c.drawString(ML, y - 16.5 * mm, "Pharos, an island off Alexandria")
fy = y - 23.5 * mm
for v, lab in [("280 BC", "the lighthouse is built"), ("1,500+", "years it stood"), ("1 of 7", "ancient Wonders of the World")]:
    rule(c, ML, fy + 3.5 * mm, ML + lcw - 6 * mm, RULE)
    c.setFillColor(DEEP)
    c.setFont("Serif-B", 9.6)
    c.drawString(ML, fy - 0.8 * mm, v)
    c.setFillColor(MUTED)
    c.setFont("Sans", 7.2)
    c.drawString(ML + 16 * mm, fy - 0.8 * mm, lab)
    fy -= 6.8 * mm
c.setStrokeColor(RULE)
c.setLineWidth(0.6)
c.line(ML + lcw - 2 * mm, y, ML + lcw - 2 * mm, fy + 3 * mm)
sx_ = ML + lcw + 4 * mm
sw_ = W - MR - sx_
story = ParagraphStyle("story", parent=body, fontSize=8.8, leading=12.8)
sy = y
for t in [
    "Pharos was a small island off Alexandria. Around 280 BC a great lighthouse was built there. Its fire "
    "guided ships safely into the harbour for more than 1,500 years. Its name became the word for a "
    "lighthouse in many languages: <i>phare</i> in French, <i>faro</i> in Italian and Spanish.",
    "Our PHAROS does the same job. A lighthouse does not steer the ship. <b>It keeps the light on, so we "
    "never sail on in the dark.</b>",
]:
    sy = para(c, t, story, sx_, sy, sw_) - 2.4 * mm
sy = para(c, "The letters spell its full name: <b>Ph</b>armaceutical <b>A</b>lerts &amp; <b>R</b>egulatory "
             "<b>O</b>bservation <b>S</b>ystem.", ParagraphStyle("acr", parent=story, textColor=MUTED, fontSize=8.2),
          sx_, sy, sw_)
y = min(sy, fy) - 5.5 * mm

# the engine, in the navy band
eh = 46 * mm
c.setFillColor(INK)
c.rect(ML, y - eh, CW, eh, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(ML, y - 1.1 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
micro(c, "The engine  ·  it runs by itself, day and night", ML + 6 * mm, y - 7.5 * mm, color=BEACON, size=6.6)
eng = [("Read", "The 25 reference authorities and others, our mailbox, and the literature."),
       ("Keep", "Every new item and its PDFs, in its own language, in a locked archive."),
       ("Find", "Our ingredients and their drug classes, by every name, in every language."),
       ("Show", "On the Ingredients and Sources tabs, and in a Telegram message."),
       ("Report", "Each morning at 07:00 Cairo, the day before; each Sunday, the week. PDF and Excel.")]
ew = (CW - 12 * mm) / 5
for i, (t, s) in enumerate(eng):
    x = ML + 6 * mm + i * ew
    if i:
        c.setStrokeColor(NAVY_RULE)
        c.setLineWidth(0.6)
        c.line(x - 2 * mm, y - 13 * mm, x - 2 * mm, y - eh + 6 * mm)
    c.setFillColor(BEACON)
    c.setFont("Serif", 18)
    c.drawString(x, y - 20 * mm, str(i + 1))
    c.setFillColor(WHITE)
    c.setFont("Sans-B", 9.6)
    c.drawString(x, y - 26 * mm, t)
    p, ph = ptext(s, ParagraphStyle("e", parent=tiny, textColor=MAST_MUTED, fontSize=7.6, leading=10.4), ew - 5 * mm)
    p.drawOn(c, x, y - 28 * mm - ph)
y -= eh

# the contents, under the engine
y -= 3.6 * mm
micro(c, "Contents", ML, y - 2.4 * mm, color=INK, size=6.6)
y -= 4.6 * mm
contents = [("01", "How PHAROS screens", 2), ("02", "Ingredients", 3), ("03", "A finding concerns us", 9),
            ("04", "Sources", 11), ("05", "Cases and products", 15), ("06", "Reports and evidence", 18),
            ("07", "Telegram", 21), ("08", "People and Me", 21), ("09", "For the SOP", 22)]
ccw = (CW - 2 * 5 * mm) / 3
for i, (n, t, pg) in enumerate(contents):
    x = ML + (i % 3) * (ccw + 5 * mm)
    ry = y - (i // 3) * 5.4 * mm
    rule(c, x, ry, x + ccw, INK if i < 3 else RULE, 0.8 if i < 3 else 0.6)
    text(c, n, x, ry - 3.9 * mm, "Serif-B", 9, DEEP)
    text(c, t, x + 6.4 * mm, ry - 3.9 * mm, "Sans", 7.4)
    micro(c, str(pg), x + ccw, ry - 3.9 * mm, size=6.4, align="right")
y -= 3 * 5.4 * mm
rule(c, ML, y, W - MR, RULE)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 2 · THE METHOD ═════════════════════════
new_page("How PHAROS screens")
y = running_head(c, "01  ·  How PHAROS screens")
y = head(c, "01", "How PHAROS screens", y)
y = para(c, "PHAROS replaces the manual screen of regulatory safety information for the active ingredients we "
            "market. It reads, keeps and finds. A person reads what it found, and decides.", what_st, ML, y, CW) - 4 * mm

# the two passes: a grid on the left, the two passes on the right
gx, gy = ML, y
cols_ = ["Levofloxacin", "Lornoxicam", "Ingredient 3", "Ingredient 4"]
rows_ = ["Germany", "Japan", "United Kingdom", "Spain", "…", "Literature"]
lab_w = 25 * mm
cell_w = 15 * mm
cell_h = 6.2 * mm
gw = lab_w + cell_w * len(cols_)
gh = 9 * mm + cell_h * len(rows_)
frame(c, gx, gy, gw + 8 * mm, gh + 8 * mm)
ox, oy = gx + 4 * mm, gy - 4 * mm
# the vertical pass: one ingredient, every source
c.setFillColor(MARK)
c.rect(ox + lab_w, oy - gh, cell_w, gh, stroke=0, fill=1)
# the horizontal pass: one authority, everything it published
c.setFillColor(SURFACE2)
c.rect(ox, oy - 9 * mm - 2 * cell_h, gw, cell_h, stroke=0, fill=1)
c.setFillColor(MARK)
c.rect(ox + lab_w, oy - 9 * mm - 2 * cell_h, cell_w, cell_h, stroke=0, fill=1)
for j, n in enumerate(cols_):
    cx_ = ox + lab_w + j * cell_w
    c.saveState()
    c.translate(cx_ + cell_w / 2 - 1, oy - 8 * mm)
    c.rotate(28)
    text(c, n, 0, 0, "Sans-B" if j == 0 else "Sans", 5.8, INK if j == 0 else MUTED)
    c.restoreState()
for i, n in enumerate(rows_):
    ry_ = oy - 9 * mm - (i + 1) * cell_h
    text(c, n, ox, ry_ + 2.2 * mm, "Sans-B" if i == 1 else "Sans", 6.3, INK if i == 1 else MUTED)
    rule(c, ox, ry_, ox + gw, RULE)
    for j in range(len(cols_)):
        cx_ = ox + lab_w + j * cell_w
        if (i, j) in [(0, 0), (1, 0), (3, 1)]:
            c.setFillColor(INK)
            c.rect(cx_ + cell_w / 2 - 1 * mm, ry_ + cell_h / 2 - 1 * mm, 2 * mm, 2 * mm, stroke=0, fill=1)
# the arrows
c.setStrokeColor(DEEP)
c.setLineWidth(1)
ax_ = ox + lab_w + cell_w / 2
c.line(ax_ + 4.4 * mm, oy - 9.5 * mm, ax_ + 4.4 * mm, oy - gh + 1.5 * mm)
p2 = c.beginPath()
p2.moveTo(ax_ + 4.4 * mm, oy - gh + 0.4 * mm)
p2.lineTo(ax_ + 3.4 * mm, oy - gh + 2 * mm)
p2.lineTo(ax_ + 5.4 * mm, oy - gh + 2 * mm)
p2.close()
c.setFillColor(DEEP)
c.drawPath(p2, stroke=0, fill=1)
hy_ = oy - 9 * mm - 2 * cell_h + 1.2 * mm
c.line(ox + lab_w + 1 * mm, hy_, ox + gw - 1.5 * mm, hy_)
p3 = c.beginPath()
p3.moveTo(ox + gw - 0.4 * mm, hy_)
p3.lineTo(ox + gw - 2 * mm, hy_ + 1 * mm)
p3.lineTo(ox + gw - 2 * mm, hy_ - 1 * mm)
p3.close()
c.drawPath(p3, stroke=0, fill=1)
tag(c, ax_ + 4.4 * mm, oy - gh - 0.5 * mm - 2.6 * mm, "V")
tag(c, ox + gw + 2 * mm, hy_, "H")

px = gx + gw + 14 * mm
pw = W - MR - px
py = gy
for L, name, where, s in [
    ("V", "The vertical pass", "Ingredients tab",
     "<b>By ingredient.</b> Take one active ingredient and look in every source: the 25 reference authorities, the "
     "other authorities, and the literature (PubMed, PubMed Central and Europe PMC), for the days you choose. The question: "
     "did anyone, anywhere, mention it, and where? The search includes the ingredient's drug class, because many "
     "class-wide notices never name the ingredient."),
    ("H", "The horizontal pass", "Sources tab",
     "<b>By authority.</b> Take each authority and read everything it newly published, by eye: news, safety "
     "alerts, DHPC letters, new PDFs, whether or not it names our ingredients. It is the safety net for whatever "
     "the vertical pass misses."),
]:
    tag(c, px + 2.3 * mm, py - 3 * mm, L)
    c.setFillColor(INK)
    c.setFont("Serif-B", 11.5)
    c.drawString(px + 7 * mm, py - 4.2 * mm, name)
    micro(c, where, W - MR, py - 3.8 * mm, align="right", color=DEEP)
    rule(c, px, py - 6.6 * mm, W - MR, RULE)
    py = para(c, s, ink_tiny, px, py - 8 * mm, pw) - 5 * mm
y = min(py, gy - gh - 8 * mm) - 7 * mm

y = label(c, "The tabs", y)
y = notes_row(c, [
    ("Ingredients", "The watchlist, and for each ingredient its screen: every source, for the days you choose. "
                    "The vertical pass. It is the page PHAROS opens on."),
    ("Sources", "One card per country: the pages you check and what was published since you last looked. The "
                "horizontal pass. Its tab says how many items are new."),
    ("Products and Cases", "Our products, each with its ingredients and strengths. Each individual case report, "
                           "from its document to the authority (page 15)."),
    ("Reports", "The daily and weekly reports, PDF and Excel, with fingerprints and signatures; packs on request; "
                "the screening log."),
    ("People and Me", "People: who may sign in. Me, your name at the top right: Telegram, password, light or "
                      "dark."),
], y, 5, gap=4 * mm) - 6 * mm

y = label(c, "When PHAROS reads", y)
y = table(c, [
    ("Every 4 hours, day and night", "The authorities' news feeds, web pages and lists, and the pharmacovigilance "
                                     "mailbox, where the newsletters that come only by e-mail arrive."),
    ("Twice a day", "Sites that can only be read with a full browser, and the slower lists."),
    ("Four times a day", "The literature (PubMed, PubMed Central and Europe PMC), drug classes from the ATC code "
                         "and the check of the past (page 3). Early morning only: the large lists (EMA's, the EURD "
                         "list)."),
    ("Every Monday", "The label watch: changes to the product information (SPC) of products with our ingredients. "
                     "Then EMA's literature monitoring list."),
    ("Every day, from 07:00 Cairo", "Telegram. The reminder of findings due to the Egyptian Drug "
                                    "Authority and of signal steps due (page 9). After 09:00, the class digest, with "
                                    "the possible case reports, and the new items."),
    ("07:00 daily, 05:00 Sunday", "The daily report, for the day before. On Sunday, the weekly report, for the week "
                                  "that has just ended."),
], y, [52 * mm, CW - 52 * mm], header=["When", "What"], styles=[cell_b, cell_st]) - 6 * mm

y = label(c, "Good to know", y)
y = notes_row(c, [
    ("The week", "Weeks run Sunday to Saturday, Cairo time. Every date and time on screen and in the reports is "
                 "Cairo local time."),
    ("A site that refuses PHAROS", "PHAROS never forces its way in. Such a site is read from its e-mail "
                                   "newsletter, or its page is marked <b>Not read by the app — open it "
                                   "yourself</b>."),
    ("Titles as published", "Every title stays in its own language, exactly as the authority wrote it. A link "
                            "always opens the authority's own page, never a data feed."),
], y, 3) - 4 * mm
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 3 · INGREDIENTS: THE WATCHLIST AND DRUG CLASSES ═════════════════════════
new_page("Ingredients")
y = running_head(c, "02  ·  Ingredients")
y = head(c, "02", "Ingredients: the watchlist", y, sub="A drawing, not real data")
y = para(c, "Every active ingredient we watch, looked for under every name it carries, in each regulator's own "
            "language, and by the words of its drug class.", what_st, ML, y, CW) - 3 * mm
dw = CW * 0.56
sxs = ML + dw + 7 * mm
sws = W - MR - sxs
fh3 = 84.6 * mm
frame(c, ML, y, dw, fh3)
button(c, ML + dw - 4 * mm, y - 3.5 * mm, "Add ingredient", size=6.2)
micro(c, "Watchlist", ML + 4 * mm, y - 6.5 * mm, size=5.4, spacing=0.7, color=DEEP)
ix = ML + 4 * mm
iw = dw - 8 * mm
yy = y - 13.5 * mm
for lab, off in [("Ingredient", 0), ("Names looked for", 36), ("Confirmed", 66), ("Watched", 86)]:
    micro(c, lab, ix + off * mm, yy, size=5.2, spacing=0.7)
rule(c, ix, yy - 1.8 * mm, ix + iw, INK, 0.7)
yy -= 7 * mm
for name, atc, cls, n, confirmed, opened in [("Levofloxacin", "ATC J01MA12", "Fluoroquinolones", "38 names in 15 languages",
                                              False, True),
                                             ("Lornoxicam", "ATC M01AC05", "Oxicams, NSAID", "41 names in 15 languages",
                                              True, False)]:
    c.setStrokeColor(INK)
    c.setLineWidth(0.6)
    tx_ = ix + 0.4 * mm
    if opened:
        p4 = c.beginPath()
        p4.moveTo(tx_, yy + 2.2 * mm)
        p4.lineTo(tx_ + 2 * mm, yy + 2.2 * mm)
        p4.lineTo(tx_ + 1 * mm, yy + 0.6 * mm)
        p4.close()
    else:
        p4 = c.beginPath()
        p4.moveTo(tx_ + 0.4 * mm, yy + 2.4 * mm)
        p4.lineTo(tx_ + 0.4 * mm, yy + 0.4 * mm)
        p4.lineTo(tx_ + 2 * mm, yy + 1.4 * mm)
        p4.close()
    c.setFillColor(INK)
    c.drawPath(p4, stroke=0, fill=1)
    w_ = text(c, name, ix + 4 * mm, yy, "Sans-B", 7.4)
    rule(c, ix + 4 * mm, yy - 0.7 * mm, ix + 4 * mm + w_, INK, 0.4)
    text(c, f"{atc}  ·  {cls}", ix + 4 * mm, yy - 2.8 * mm, "Sans", 5.6, MUTED)
    text(c, n, ix + 36 * mm, yy, "Sans", 6.2)
    if confirmed:
        bars(c, ix + 66 * mm, yy, 14 * mm)
        text(c, "5 Nov 2026", ix + 66 * mm, yy - 2.8 * mm, "Mono", 5.4, MUTED)
    else:
        lbutton(c, ix + 66 * mm, yy + 3.2 * mm, "Confirm", size=5.8, h=4.4 * mm)
    switch(c, ix + 86 * mm, yy - 0.4 * mm, on=True)
    if opened:
        tag(c, ix + 25 * mm, yy + 1 * mm, "A")
        tag(c, ix + 80.5 * mm, yy + 1 * mm, "C")
        tag(c, ix + 95.5 * mm, yy + 1 * mm, "D")
    rule(c, ix, yy - 4.6 * mm, ix + iw, RULE)
    yy -= 9 * mm
    if opened:
        # the opened row: drug class, then names
        c.setFillColor(SURFACE2)
        c.rect(ix, yy - 37.6 * mm, iw, 40 * mm, stroke=0, fill=1)
        jx = ix + 3 * mm
        micro(c, "Drug class", jx, yy - 1 * mm, size=5.2, spacing=0.7, color=DEEP)
        yy -= 5 * mm
        text(c, "Fluoroquinolones (J01MA)", jx, yy, "Sans-B", 6.8)
        lbutton(c, ix + iw - 17 * mm, yy + 3 * mm, "Confirm", size=5.6, h=4.2 * mm)
        tag(c, ix + iw - 2.6 * mm, yy + 0.9 * mm, "B")
        yy -= 3.4 * mm
        text(c, "17 words in 12 languages  ·  from the ATC code", jx, yy, "Sans", 5.8, MUTED)
        yy -= 4.4 * mm
        for lang, term in [("German", "Fluorchinolon"), ("French", "fluoroquinolone"), ("Spanish", "fluoroquinolona")]:
            text(c, lang, jx, yy, "Mono", 5.4, MUTED)
            text(c, term, jx + 14 * mm, yy, "Sans", 6.2)
            text(c, "Test against archive", jx + 42 * mm, yy, "Sans-B", 5.4, SEA)
            yy -= 3.4 * mm
        yy -= 1.6 * mm
        micro(c, "Names looked for", jx, yy, size=5.2, spacing=0.7, color=DEEP)
        yy -= 4 * mm
        for lang, term, kind in [("English", "levofloxacin", "Ingredient name  ·  Word start"),
                                 ("Japanese", "レボフロキサシン", "Ingredient name  ·  Anywhere in the text"),
                                 ("English", "Tavanic", "Brand name  ·  Whole word only")]:
            text(c, lang, jx, yy, "Mono", 5.4, MUTED)
            if lang == "Japanese":
                bars(c, jx + 14 * mm, yy, 16 * mm)
            else:
                text(c, term, jx + 14 * mm, yy, "Sans", 6.2)
            text(c, kind, jx + 42 * mm, yy, "Sans", 5.6, MUTED)
            yy -= 3.4 * mm
        yy -= 3.6 * mm
label(c, "How to add an active ingredient", y, sxs)
steps(c, ["Press <b>Add ingredient</b>.",
          "Type its name in any language or spelling, at least three letters.",
          "Pick the right one from the list: each shows its ATC code. Then press <b>Confirm</b>, which carries its "
          "name and code.",
          "Check the names suggested for each language. Add brand names, remove wrong ones. <b>Never when it is</b> "
          "keeps look-alike drugs out.",
          "Press <b>Test against archive</b> on a name: how many stored notices contain it.",
          "Press <b>Save</b>. Nothing is saved before this. Its row then says Ready, or Still preparing (page 4).",
          "In the table, press <b>Confirm</b> to record that you checked it."],
      sxs, y - 12, sws)
y -= fh3 + 3.5 * mm
y = legend(c, [("A", "The name", "Opens the ingredient's screen."),
               ("B", "Drug class", "Its words in each language."),
               ("C", "Confirm", "Records your name and the date."),
               ("D", "Watched", "Off pauses it, keeping its names.")], y, 4) - 8 * mm

y = sub_head(c, "Drug class words", y, aside="From the ATC code until you confirm")
y = para(c, "Many safety notices speak of a whole class (fluoroquinolones, NSAIDs) and never name the ingredient. So "
            "each ingredient also carries its drug class: its ATC group (levofloxacin J01MA12 belongs to "
            "Fluoroquinolones, J01MA), with the words notices use for that class in each regulator's language. "
            "The next class run (four a day) makes the class from the ATC code. It reads <b>from the ATC code</b> until an "
            "administrator checks its words and presses <b>Confirm</b>.", ink_tiny, ML, y, CW) - 4 * mm
colw = (CW - 8 * mm) / 2
top = y
yl = steps(c, ["Press the triangle beside the ingredient's name, then click the class line to list its words "
               "by language.",
               "Press <b>Test against archive</b> beside a word: “12 archived notices contain it”."], ML, y, colw)
yr = steps(c, ["To add a word, choose its language, type it as notices write it, and press <b>Add word</b>. "
               "<b>Remove</b> takes a wrong word out.",
               "When the words are right, press <b>Confirm</b>. Your name and the date are recorded."],
           ML + colw + 8 * mm, top, colw, start=3)
y = min(yl, yr) - 6 * mm
y = notes_row(c, [
    ("In its own language", "A class word is looked for only in notices written in its language."),
    ("Marked By class", "A notice that names only the class goes to the daily digest, never an immediate "
                        "message. On screen it is marked <b>By class</b>."),
    ("The check of the past", "A new name or class word is also checked against every stored notice, whatever "
                              "its date. What it finds is marked <b>History</b> and sends no message."),
], y, 3) - 4 * mm
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 4 · INGREDIENTS: READY, AND THE JAPAN CODE ═════════════════════════
new_page("Ingredients")
y = running_head(c, "02  ·  Ingredients  ·  ready or still preparing")
y = head(c, "", "Any ingredient she adds is covered", y, sub="A drawing, not real data")
y = para(c, "Nothing more is asked after Save. Under its name, each ingredient's row says how far PHAROS has got in "
            "preparing it, and every part clears by itself.", what_st, ML, y, CW) - 3 * mm
fh = 70 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
tagx = ML + CW - 4.6 * mm
note_st = ParagraphStyle("rnote", parent=tiny, fontSize=6.6, leading=8.8)
yy = y - 6 * mm
micro(c, "Watchlist", ix, yy, size=5.4, spacing=0.7, color=DEEP)
rule(c, ix, yy - 2 * mm, ix + iw, INK, 0.7)
yy -= 7 * mm
for name, atc, ready, notes_, opened in [
    ("Lornoxicam", "ATC M01AC05  ·  Oxicams, NSAID", None,
     "4 label products in France, Spain, United Kingdom  ·  No Japan code yet, so Japan's label watch cannot find "
     "its package inserts  ·  PSUR every 3 years  ·  Literature not monitored by EMA  ·  Telegram: Sama Mosaad",
     False),
    ("Levofloxacin", "ATC J01MA12  ·  Fluoroquinolones",
     "Still preparing: check of the past running  ·  PubMed look-back running  ·  label watch on Monday (Spain)",
     "3 label products in France, Japan, United Kingdom  ·  Not on the EURD list  ·  Literature not monitored by "
     "EMA  ·  Telegram: Sama Mosaad", True),
]:
    tx_ = ix + 0.4 * mm
    p4 = c.beginPath()
    if opened:
        p4.moveTo(tx_, yy + 2.2 * mm)
        p4.lineTo(tx_ + 2 * mm, yy + 2.2 * mm)
        p4.lineTo(tx_ + 1 * mm, yy + 0.6 * mm)
    else:
        p4.moveTo(tx_ + 0.4 * mm, yy + 2.4 * mm)
        p4.lineTo(tx_ + 0.4 * mm, yy + 0.4 * mm)
        p4.lineTo(tx_ + 2 * mm, yy + 1.4 * mm)
    p4.close()
    c.setFillColor(INK)
    c.drawPath(p4, stroke=0, fill=1)
    w_ = text(c, name, ix + 4 * mm, yy, "Sans-B", 7.4)
    rule(c, ix + 4 * mm, yy - 0.7 * mm, ix + 4 * mm + w_, INK, 0.4)
    text(c, atc, ix + 6 * mm + w_, yy, "Sans", 5.8, MUTED)
    yy -= 5 * mm
    if ready is None:
        chip(c, ix + 4 * mm, yy - 0.9 * mm, "Ready", size=5.8, fill=SEA, color=WHITE)
    else:
        dot(c, ix + 4 * mm, yy - 0.3 * mm, BEACON)
        text(c, ready, ix + 7.2 * mm, yy, "Sans-B", 6.2)
        tag(c, tagx, yy + 1 * mm, "A")
    p, ph = ptext(notes_, note_st, iw - 8 * mm)
    p.drawOn(c, ix + 4 * mm, yy - 2 * mm - ph)
    if opened:
        tag(c, tagx, yy - 2.6 * mm, "B")
    yy -= 3.6 * mm + ph
    rule(c, ix, yy, ix + iw, RULE)
    yy -= 5 * mm
# the opened row: its Japan code
c.setFillColor(SURFACE2)
c.rect(ix, yy - 15.6 * mm, iw, 18.6 * mm, stroke=0, fill=1)
jx = ix + 3 * mm
w_ = text(c, "Japan code", jx, yy - 0.6 * mm, "Sans-B", 6.6)
text(c, "PMDA product code, for Japan's label watch", jx + w_ + 2.4 * mm, yy - 0.6 * mm, "Sans", 5.8, MUTED)
yy -= 4.8 * mm
w_ = text(c, "Now ", jx, yy, "Sans", 6.2)
w2 = text(c, "6241013", jx + w_, yy, "Mono", 6.2)
w3 = text(c, "  ·  ", jx + w_ + w2, yy, "Sans", 6.2, MUTED)
w4 = text(c, "its products on PMDA", jx + w_ + w2 + w3, yy, "Sans", 6.2, SEA)
rule(c, jx + w_ + w2 + w3, yy - 0.8 * mm, jx + w_ + w2 + w3 + w4, SEA, 0.4)
tag(c, tagx, yy + 1 * mm, "C")
yy -= 3 * mm
c.setStrokeColor(RULE)
c.setFillColor(WHITE)
c.rect(jx, yy - 5 * mm, 30 * mm, 5 * mm, stroke=1, fill=1)
text(c, "6241013", jx + 2 * mm, yy - 3.3 * mm, "Mono", 6)
bx = jx + 32 * mm
bx += lbutton(c, bx, yy, "Save", dark=True, size=6) + 1.6 * mm
lbutton(c, bx, yy, "Open the PMDA search", size=6)
tag(c, tagx, yy - 2.5 * mm, "D")
y -= fh + 3.5 * mm
y = legend(c, [("A", "The line", "Ready, or Still preparing."),
               ("B", "Under it", "Labels, EURD, EMA, Telegram."),
               ("C", "Japan code", "The one it has now."),
               ("D", "PMDA search", "Where the code is found.")], y, 4) - 6 * mm

y = label(c, "What the line says, and when it clears by itself", y)
y = table(c, [
    ("Ready", "Its names, its class words, the check of the past, the PubMed look-back and the label watch are all "
              "done, and someone receives its Telegram messages."),
    ("class words waiting", "It has an ATC code and no drug class yet. The next class run makes it (four a day)."),
    ("check of the past running, or waiting", "Its names are checked against every stored notice, whatever its "
                                              "date. It clears when every name is checked."),
    ("PubMed look-back running, or waiting", "PubMed abstracts are read 12 months back for its name. It clears "
                                             "after one to three literature runs; whole papers and class words "
                                             "keep filling in after it is Ready."),
    ("label watch on Monday (Spain)", "The countries whose label watch has not read since it was added. Monday's "
                                      "run reads them; a country with no product of it is an answer too."),
    ("nobody receives its Telegram messages yet", "Nobody with Telegram is subscribed to it. Dr Sama Mosaad receives "
                                                  "every ingredient's messages, so this clears the moment it is "
                                                  "saved."),
], y, [62 * mm, CW - 62 * mm], header=["What the row says", "What it means"], styles=[cell_b, cell_st]) - 4 * mm
y = para(c, "Under the line, and never holding Ready back: the label products found and where, the Japan code, the "
            "EURD list's PSUR frequency, data lock point and submission date, whether EMA's literature monitoring "
            "covers it, and who receives its messages. The weekly report repeats each line in section 01.",
         tiny, ML, y, CW) - 7 * mm

y = sub_head(c, "The Japan code", y, aside="Administrators")
y = para(c, "PMDA's search answers a form, not an address, so PHAROS cannot look a Japanese package insert up by "
            "name. One code per ingredient lets Japan's label watch find them. Without it the row says so; the "
            "ingredient is still watched everywhere else.", ink_tiny, ML, y, CW) - 4 * mm
top = y
yl = steps(c, ["Open the ingredient's row: the triangle beside its name. Under <b>Japan code</b>, press <b>Open the "
               "PMDA search</b>.",
               "Search the name, open the product, and copy the code from the end of its address: "
               "…/GeneralList/<b>6241013</b> for levofloxacin."], ML, y, colw)
yr = steps(c, ["Paste it and press <b>Save</b>. Seven characters; the 12-character YJ code is accepted and kept as "
               "the seven it starts with.",
               "The row shows <b>Now 6241013 · its products on PMDA</b>. Japan's label watch uses it at its next "
               "weekly run."], ML + colw + 8 * mm, top, colw, start=3)
y = min(yl, yr)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 5 · INGREDIENTS: THE INGREDIENT SCREEN ═════════════════════════
new_page("Ingredients")
y = running_head(c, "02  ·  Ingredients  ·  the vertical pass")
y = head(c, "", "One ingredient, every source", y, sub="A drawing, not real data")
y = para(c, "Click an ingredient's name. For the days you choose, the screen answers one question for every country: "
            "was it mentioned, and where?", what_st, ML, y, CW) - 3 * mm
fh = 92 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
tagx = ML + CW - 4.6 * mm
yy = y - 4 * mm
micro(c, "Ingredient", ix, yy - 2 * mm, size=5.4, spacing=0.7, color=DEEP)
text(c, "Levofloxacin", ix, yy - 8 * mm, "Serif-B", 13)
text(c, "ATC J01MA12  ·  Fluoroquinolones  ·  Looked for by 38 names in 15 languages and 17 class words in 12 "
        "languages", ix, yy - 12 * mm, "Sans", 6, MUTED)
lbutton(c, ix + iw - 22 * mm, yy - 1 * mm, "All ingredients", size=5.8)
yy -= 14.5 * mm
# the days
bx = ix
for k, p in enumerate(["This week", "Last week", "Last 30 days"]):
    bx += lbutton(c, bx, yy, p, dark=(k == 0), size=6) + 1.2 * mm
bx += 4 * mm
for lab in ["From", "To"]:
    text(c, lab.upper(), bx, yy - 3.3 * mm, "Mono", 5.2, MUTED)
    c.setStrokeColor(RULE)
    c.setFillColor(WHITE)
    c.rect(bx + 7 * mm, yy - 5 * mm, 20 * mm, 5 * mm, stroke=1, fill=1)
    text(c, "01/11/2026" if lab == "From" else "06/11/2026", bx + 8.5 * mm, yy - 3.3 * mm, "Mono", 5.6, INK)
    bx += 30 * mm
lbutton(c, bx, yy, "Show these days", size=6)
tag(c, tagx, yy - 2.5 * mm, "A")
yy -= 8 * mm
text(c, "Sun 1 Nov – Fri 6 Nov 2026", ix, yy, "Sans-B", 6.6)
text(c, "  ·  Cairo days, both included", ix + pdfmetrics.stringWidth("Sun 1 Nov – Fri 6 Nov 2026", "Sans-B", 6.6), yy,
     "Sans", 6.6, MUTED)
yy -= 5.5 * mm
text(c, "Mentioned in 1 of 29 countries  ·  25 nothing found  ·  3 to check by hand", ix, yy, "Serif-I", 8.6)
tag(c, tagx, yy + 1 * mm, "B")
yy -= 3.5 * mm
yy = screen_sec(c, ix, yy, iw, "01", "Her countries", "25")
# country blocks: a mention on the left, three short answers on the right
gw_ = (iw - 4 * mm) / 2
lx, rx = ix, ix + gw_ + 4 * mm
top = yy


def country_block(x, y_, w, name, answer, reads, color, h):
    c.setFillColor(color)
    c.rect(x, y_ - h, 0.9 * mm, h, stroke=0, fill=1)
    text(c, name, x + 3 * mm, y_ - 3.6 * mm, "Sans-B", 7.2)
    text(c, answer, x + 3 * mm, y_ - 7.2 * mm, "Sans-B", 6.2, DEEP if color == BEACON else INK)
    text(c, reads, x + 3 * mm, y_ - 10.4 * mm, "Sans", 5.6, MUTED)
    return y_ - h - 2.4 * mm


bh = 40 * mm
country_block(lx, top, gw_, "Germany", "Mentioned in 1 notice", "BfArM  ·  PEI — Read 84 times in these days", INK, bh)
my = top - 13.5 * mm
mx = lx + 3 * mm
mw = gw_ - 4 * mm
rule(c, mx, my + 1.2 * mm, mx + mw, RULE)
micro(c, "5 Nov 2026  ·  DHPC letter", mx, my - 1.6 * mm, size=5.2, spacing=0.6, color=MUTED)
chip(c, mx + 33 * mm, my - 2.6 * mm, "By class")
c.setFillColor(INK)
c.rect(mx, my - 6.4 * mm, mw * 0.92, 2 * mm, stroke=0, fill=1)
c.rect(mx, my - 9.6 * mm, mw * 0.55, 2 * mm, stroke=0, fill=1)
my -= 12.5 * mm
micro(c, "Matched", mx, my, size=5, spacing=0.6)
c.setFillColor(MARK)
c.rect(mx + 11.5 * mm, my - 0.9 * mm, 21.5 * mm, 3.4 * mm, stroke=0, fill=1)
text(c, "Fluorchinolon", mx + 12.5 * mm, my, "Sans-B", 6)
text(c, "German", mx + 35 * mm, my, "Sans", 5.4, MUTED)
my -= 5.2 * mm
dot(c, mx, my - 0.3 * mm, BEACON)
text(c, "No decision yet", mx + 3.2 * mm, my, "Sans-B", 6.2)
tag(c, mx + mw - 2 * mm, my + 1 * mm, "D")
my -= 2.6 * mm
bw_ = lbutton(c, mx, my, "Concerns us", size=6)
lbutton(c, mx + bw_ + 2 * mm, my, "Doesn't concern us", size=6)
tag(c, mx + mw - 2 * mm, my - 2.4 * mm, "E")
ry_ = top
for name, answer, reads, col in [
    ("Canada", "Not read in these days — check it by hand", "Health Canada — Not read in these days", BEACON),
    ("Spain", "1 of 42 reads failed — check it by hand", "AEMPS — Read 42 times in these days, 1 failed", BEACON),
    ("Japan", "Nothing found", "PMDA  ·  MHLW — Read 48 times in these days", SEA),
]:
    ry_ = country_block(rx, ry_, gw_, name, answer, reads, col, 12.6 * mm)
tag(c, tagx, top - 6 * mm, "C")
yy = top - bh - 3.5 * mm
yy = screen_sec(c, ix, yy, iw, "02", "Other authorities", "4")
y -= fh + 3.5 * mm
y = legend(c, [("A", "The days", "This week is the default."),
               ("B", "In one line", "How many countries, each answer."),
               ("C", "One country", "Her countries first."),
               ("D", "One notice", "Its title opens the authority's page."),
               ("E", "The decision", "Two buttons on every finding.")], y, 5) - 5 * mm

y = label(c, "The answer for each country", y)
y = table(c, [
    ("Mentioned in N notices", "The ingredient, or a word of its class, is in N notices of these days. Read each one "
                               "and record a decision."),
    ("Nothing found", "Every read of these days worked and every page of hers is read by the app. Nothing to do."),
    ("N of M reads failed — check it by hand", "Some reads failed, so nothing found is not a sure answer. Her pages "
                                               "open folded out: look at them yourself."),
    ("Not read in these days — check it by hand", "The app did not read this country in these days. Open her "
                                                  "pages and look."),
    ("A page of hers is not read by the app — check it by hand", "Nothing found where it reads, but one of her "
                                                                  "pages it cannot read. Open that page."),
], y, [68 * mm, CW - 68 * mm], header=["What the country says", "What it means"], styles=[cell_b, cell_st]) - 5 * mm

y = label(c, "How to record a decision", y)
top = y
yl = steps(c, ["Open the notice's title: it is the authority's own page. An e-mail with no page opens with "
               "<b>Read the e-mail</b>.",
               "Check the matched words. <b>By class</b> means only a class word matched.",
               "Press <b>Concerns us</b> or <b>Doesn't concern us</b>."], ML, y, colw)
yr = steps(c, ["Write why. For Doesn't concern us the reason is required; for Concerns us a comment is optional.",
               "Press <b>Record</b>. Your name and the time are saved, on every mention of that notice.",
               "To change it later, press <b>Change</b> and record a new decision. The earlier one is kept."],
           ML + colw + 8 * mm, top, colw, start=4)
y = min(yl, yr)
y = para(c, "Readers see the decisions; reviewers and administrators record them. A decision is never edited or "
            "deleted. <b>Concerns us</b> brings the five-day clock and the signal (pages 9 and 10).", tiny, ML, y, CW)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 6 · INGREDIENTS: LITERATURE AND LABEL CHANGES ═════════════════════════
new_page("Ingredients")
y = running_head(c, "02  ·  Ingredients  ·  literature")
y = head(c, "", "Literature: PubMed, PubMed Central and Europe PMC", y, sub="A drawing, not real data")
y = para(c, "At the foot of every ingredient's screen. PubMed, PubMed Central and Europe PMC are searched four times "
            "a day for the ingredient's English names, in titles and abstracts.",
         what_st, ML, y, CW) - 3 * mm
fh = 82 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
yy = screen_sec(c, ix, y - 4 * mm, iw, "04", "Literature", "58")
text(c, "58 papers in these days: 58 name the ingredient, 0 only its class  ·  24 in PubMed, 31 in PubMed "
        "Central, 41 in Europe PMC", ix, yy - 1 * mm, "Sans", 6.6)
tag(c, tagx, yy, "A")
yy -= 6 * mm
micro(c, "What the daily watch searches, and what it found", ix, yy, size=5, spacing=0.6)
yy -= 4 * mm
qx = [ix, ix + 62 * mm, ix + 84 * mm, ix + 112 * mm]
for lab, x_ in zip(["Search", "PubMed", "PubMed Central", "Europe PMC"], qx, strict=True):
    micro(c, lab, x_, yy, size=5, spacing=0.6)
rule(c, ix, yy - 1.6 * mm, ix + 134 * mm, INK, 0.6)
yy -= 5.4 * mm
for q, kind, a, b, e in [("levofloxacin", "name", "24", "31", "41")]:
    w_ = text(c, q, qx[0], yy, "Sans-B", 6.4)
    text(c, kind, qx[0] + w_ + 2 * mm, yy, "Sans", 5.6, MUTED)
    text(c, a, qx[1], yy, "Mono", 6.4)
    text(c, b, qx[2], yy, "Mono", 6.4)
    text(c, e, qx[3], yy, "Mono", 6.4)
    rule(c, ix, yy - 1.8 * mm, ix + 134 * mm, RULE)
    yy -= 5 * mm
tag(c, tagx, yy + 4.5 * mm, "B")
yy -= 1.5 * mm
lbutton(c, ix, yy, "Count on PubMed and PubMed Central now", size=6)
yy -= 8 * mm
for q, a, b in [("levofloxacin", "PubMed: 24", "PubMed Central: 31")]:
    text(c, q, ix, yy, "Sans-B", 6.4)
    w1 = text(c, a, ix + 40 * mm, yy, "Sans", 6.4, SEA)
    rule(c, ix + 40 * mm, yy - 0.8 * mm, ix + 40 * mm + w1, SEA, 0.4)
    w2 = text(c, b, ix + 62 * mm, yy, "Sans", 6.4, SEA)
    rule(c, ix + 62 * mm, yy - 0.8 * mm, ix + 62 * mm + w2, SEA, 0.4)
    yy -= 4.4 * mm
text(c, "Counted by publication date, as the two websites count them.", ix, yy, "Sans", 5.8, MUTED)
tag(c, tagx, yy + 3 * mm, "C")
yy -= 5 * mm
for jr, links, pre in [("Antimicrob Agents Chemother", ["PubMed", "PubMed Central", "Europe PMC"], False),
                       ("medRxiv", ["Europe PMC"], True)]:
    rule(c, ix, yy + 1.4 * mm, ix + iw, RULE)
    micro(c, "3 Nov 2026  ·  " + jr, ix, yy - 1.6 * mm, size=5, spacing=0.6)
    if pre:
        w_ = chip(c, ix + 62 * mm, yy - 2.6 * mm, "Preprint")
        text(c, "not peer reviewed", ix + 63.5 * mm + w_, yy - 1.6 * mm, "Sans", 5.4, MUTED)
    c.setFillColor(INK)
    c.rect(ix, yy - 5.4 * mm, iw * (0.55 if pre else 0.7), 1.9 * mm, stroke=0, fill=1)
    c.rect(ix, yy - 8 * mm, iw * (0.3 if pre else 0.4), 1.9 * mm, stroke=0, fill=1)
    lx_ = ix
    for ln in links:
        lx_ += text(c, ln, lx_, yy - 11 * mm, "Sans-B", 5.8, SEA) + 4 * mm
    yy -= 13 * mm
tag(c, tagx, yy + 12 * mm, "D")
lbutton(c, ix, yy - 0.5 * mm, "Show 8 more of 8", size=6)
y -= fh + 3.5 * mm
y = legend(c, [("A", "Stored papers", "Found by the daily watch."),
               ("B", "The searches", "What is searched, and what each found."),
               ("C", "Count now", "Live counts; each opens the same search."),
               ("D", "Papers", "50 at a time, each with its links.")], y, 4) - 6 * mm

y = label(c, "How the search is made", y)
y = table(c, [
    ("What", "Four times a day, for each watched ingredient: its English names, in titles and abstracts only. A "
             "drug class is searched only when its line says <b>In the literature search</b>; it starts as "
             "<b>Notices only</b>."),
    ("Where", "PubMed and PubMed Central (NCBI), and Europe PMC, which adds preprints, marked <b>Preprint</b>, not "
              "peer reviewed. Every page of results is read, by the day each database added the paper."),
    ("Once", "A paper found in two or three databases is kept once, with every link and the two decision buttons."),
    ("New words", "A new ingredient first reads the last 12 months. What that finds is marked <b>History</b>."),
    ("Telegram", "Papers are read here and in the weekly report, never sent one by one, so the authorities' notices "
                 "are not buried under them. Only a possible case report goes in the daily message (page 7)."),
    ("References", "Under the line, each literature reference: how it was screened in these days and what was "
                   "found (page 13)."),
], y, [30 * mm, CW - 30 * mm], styles=[cell_b, cell_st]) - 5 * mm

y = label(c, "How to see that PHAROS and NCBI agree", y)
top = y
yl = steps(c, ["Set the days with <b>From</b> and <b>To</b>, and press <b>Show these days</b>.",
               "Press <b>Count on PubMed and PubMed Central now</b>."], ML, y, colw)
yr = steps(c, ["Press a count. The same search, for the same days, opens on the NCBI website. The numbers are "
               "the same."], ML + colw + 8 * mm, top, colw, start=3)
y = min(yl, yr) - 1 * mm
y = para(c, "The stored papers can differ from the live counts: the daily watch reads by the day NCBI added a paper, "
            "the live counts go by publication date, as the websites count.", tiny, ML, y, CW) - 7 * mm

y = sub_head(c, "Label changes", y, aside="03 on the ingredient's screen")
y = para(c, "The weekly label watch reads the product information (SPC) of products with our ingredients. A change "
            "detected in the days you chose is listed under <b>Label changes</b>, with the sections that changed, "
            "what the originator added set against our own label (page 8), and the same two decision buttons.",
         ink_tiny, ML, y, CW) - 2 * mm
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 7 · INGREDIENTS: CASE REPORTS IN THE LITERATURE ═════════════════════════
new_page("Ingredients")
y = running_head(c, "02  ·  Ingredients  ·  case reports in the literature")
y = head(c, "", "Case reports in the literature", y, sub="A drawing, not real data")
y = para(c, "A paper that reports a case with one of our ingredients starts its own clock: a valid serious case "
            "reaches the Egyptian Drug Authority within 15 days, a non-serious one within 90.", what_st, ML, y,
         CW) - 3 * mm
fh = 66 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
tagx = ML + CW - 4.6 * mm
yy = screen_sec(c, ix, y - 4 * mm, iw, "04", "Literature", "312")
text(c, "312 papers in these days: 96 name the ingredient, 216 only its class  ·  24 in PubMed, 288 in PubMed "
        "Central  ·  2 possible case reports", ix, yy - 1 * mm, "Sans", 6.1)
tag(c, tagx, yy, "A")
yy -= 6 * mm
w_ = text(c, "Not monitored by EMA", ix, yy, "Sans-B", 6.6, DEEP)
text(c, "EMA does not read the literature for this ingredient: cases in the literature are ours to report.",
     ix + w_ + 3 * mm, yy, "Sans", 6, MUTED)
tag(c, tagx, yy + 1 * mm, "B")
yy -= 6.4 * mm
rule(c, ix, yy + 1.6 * mm, ix + iw, RULE)
micro(c, "3 Nov 2026  ·  J Med Case Rep", ix, yy - 1.6 * mm, size=5, spacing=0.6)
w_ = chip(c, ix + 40 * mm, yy - 2.6 * mm, "Possible case report", fill=MARK)
text(c, "PubMed lists it as a case report", ix + 42 * mm + w_, yy - 1.7 * mm, "Sans", 5.8, MUTED)
tag(c, tagx, yy - 1 * mm, "C")
c.setFillColor(INK)
c.rect(ix, yy - 6.4 * mm, iw * 0.74, 1.9 * mm, stroke=0, fill=1)
c.rect(ix, yy - 9 * mm, iw * 0.36, 1.9 * mm, stroke=0, fill=1)
yy -= 13 * mm
text(c, "day zero 3 Nov 2026  ·  15 days: 18 Nov  ·  90 days: 1 Feb 2027", ix, yy, "Sans-B", 6.4, DEEP)
tag(c, tagx, yy + 1 * mm, "D")
yy -= 4.4 * mm
w1 = text(c, "PubMed", ix, yy, "Sans-B", 5.8, SEA)
text(c, "PubMed Central", ix + w1 + 4 * mm, yy, "Sans-B", 5.8, SEA)
yy -= 5.2 * mm
dot(c, ix, yy - 0.3 * mm, BEACON)
text(c, "No decision yet", ix + 3.2 * mm, yy, "Sans-B", 6.2)
yy -= 2.6 * mm
bw_ = lbutton(c, ix, yy, "Concerns us", size=6)
lbutton(c, ix + bw_ + 2 * mm, yy, "Doesn't concern us", size=6)
tag(c, tagx, yy - 2.4 * mm, "E")
yy -= 8.4 * mm
rule(c, ix, yy + 1.6 * mm, ix + iw, RULE)
micro(c, "2 Nov 2026  ·  Antimicrob Agents Chemother", ix, yy - 1.6 * mm, size=5, spacing=0.6)
c.setFillColor(INK)
c.rect(ix, yy - 6.4 * mm, iw * 0.62, 1.9 * mm, stroke=0, fill=1)
y -= fh + 3.5 * mm
y = legend(c, [("A", "In one line", "How many look like case reports."),
               ("B", "EMA", "Whether EMA reads it for us."),
               ("C", "The flag", "And why it was raised."),
               ("D", "The dates", "From the day PHAROS found it."),
               ("E", "The decision", "As on every notice.")], y, 5) - 6 * mm

y = label(c, "How a paper is flagged", y)
y = table(c, [
    ("PubMed lists it as a case report", "Its PubMed publication type is Case Reports. For a paper PubMed Central "
                                         "alone found, PHAROS reads its PubMed record too."),
    ("Its title says so", "Its title says “case report”, “case series” or “a case of”."),
    ("It names the ingredient", "Either way, only a paper whose title or abstract names the ingredient is flagged."),
    ("Day zero, 15 days, 90 days", "Day zero is the Cairo day PHAROS first found the paper, never its publication "
                                   "date. 15 days for a valid serious case, 90 for a non-serious one."),
    ("Not monitored by EMA", "From EMA's medical literature monitoring list, read every Monday. When EMA does not "
                             "monitor the ingredient, its cases in the literature are ours to report."),
], y, [52 * mm, CW - 52 * mm], styles=[cell_b, cell_st]) - 6 * mm

# the daily message, drawn, beside what to do
dw = CW * 0.47
sxs = ML + dw + 7 * mm
sws = W - MR - sxs
mh = 34 * mm
frame(c, ML, y, dw, mh)
mx = ML + 4 * mm
my = y - 6 * mm
w_ = text(c, "PHAROS", mx, my, "Sans-B", 6.6)
text(c, "  ·  possible case reports  ·  4 Nov 2026", mx + w_, my, "Sans", 6.6, MUTED)
my -= 6 * mm
text(c, "Possible case reports (1)", mx, my, "Sans-B", 6.6)
my -= 4.6 * mm
text(c, "•", mx, my, "Sans", 6.6)
c.setFillColor(INK)
c.rect(mx + 3 * mm, my - 0.2 * mm, dw * 0.66, 1.8 * mm, stroke=0, fill=1)
my -= 4.2 * mm
text(c, "J Med Case Rep  ·  day zero 3 Nov 2026  ·  15 days: 18 Nov 2026", mx + 3 * mm, my, "Sans", 6)
my -= 4.2 * mm
w_ = text(c, "Open the ingredient", mx + 3 * mm, my, "Sans", 6, SEA)
rule(c, mx + 3 * mm, my - 0.8 * mm, mx + 3 * mm + w_, SEA, 0.4)
micro(c, "In the daily message, after 09:00 Cairo", ML + 4 * mm, y - mh + 3.6 * mm, size=5, spacing=0.6)
label(c, "What to do with a possible case report", y, sxs)
yr = steps(c, ["Open <b>PubMed</b> and read the paper. Is it a valid case for one of our products?",
               "Press <b>Concerns us</b>, with a comment, or <b>Doesn't concern us</b> with the reason. The decision "
               "shows on every paper of the same notice.",
               "Concerns us also brings the five-day clock and the signal under the decision (pages 9 and 10).",
               "A valid case: press <b>Open a case</b> on the paper. PHAROS fetches it from PubMed and fills "
               "in the case form, on <b>Cases</b> (page 16)."],
           sxs, y - 12, sws)
y = min(y - mh, yr) - 5 * mm
y = notes_row(c, [
    ("The daily message", "Each possible case report naming an ingredient is sent once, at the end of the class "
                          "digest. A paper found only by a class word, or by a look into the past, never is."),
    ("The weekly report", "Section 04 lists the possible case reports first, with day zero, both dates and the "
                          "decision. The summary counts those with no decision yet."),
], y, 2)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 8 · INGREDIENTS: OUR LABEL UNDER LABEL CHANGES ═════════════════════════
new_page("Ingredients")
y = running_head(c, "02  ·  Ingredients  ·  our label")
y = head(c, "", "Our label under Label changes", y, sub="A drawing, not real data")
y = para(c, "Each label change the label watch finds is set against our own approved label, sentence by sentence: "
            "what the originator added, and whether our label already says it.", what_st, ML, y, CW) - 3 * mm
fh = 84 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
tagx = ML + CW - 4.6 * mm
yy = screen_sec(c, ix, y - 4 * mm, iw, "03", "Label changes", "1")
# our label panel
c.setFillColor(SURFACE2)
c.rect(ix, yy - 11 * mm, iw, 12 * mm, stroke=0, fill=1)
text(c, "Our label", ix + 3 * mm, yy - 3.6 * mm, "Serif-B", 9)
text(c, "Lornox 8 mg tablets  ·  Leaflet approved by EDA, March 2024  ·  English  ·  9 sections", ix + 3 * mm,
     yy - 7.4 * mm, "Sans", 6.2)
text(c, "Uploaded by Sama Mosaad, 2 Nov 2026 11:40", ix + 3 * mm, yy - 10.2 * mm, "Sans", 5.6, MUTED)
lbutton(c, ix + iw - 20 * mm, yy - 2 * mm, "Replace", size=6)
tag(c, tagx, yy - 5 * mm, "A")
yy -= 16 * mm
# one change
micro(c, "Detected 3 Nov 2026  ·  Spain  ·  AEMPS", ix, yy, size=5.2, spacing=0.6)
chip(c, ix + 52 * mm, yy - 1 * mm, "Reference product")
tag(c, tagx, yy + 0.6 * mm, "B")
c.setFillColor(INK)
c.rect(ix, yy - 5 * mm, iw * 0.42, 2 * mm, stroke=0, fill=1)
text(c, "Sections 4.4, 4.8", ix + iw * 0.42 + 4 * mm, yy - 4.6 * mm, "Sans", 6, MUTED)
yy -= 10 * mm
text(c, "Our label (Lornox 8 mg tablets, Leaflet approved by EDA, March 2024): 1 covered, 1 partly, 1 missing", ix,
     yy, "Sans", 6.2)
chip(c, ix + 118 * mm, yy - 0.9 * mm, "1 of 3 added sentences not in our label", fill=DANGER, color=WHITE)
tag(c, tagx, yy + 1 * mm, "C")
yy -= 5.6 * mm
p6 = c.beginPath()
p6.moveTo(ix, yy + 2.2 * mm)
p6.lineTo(ix + 2 * mm, yy + 2.2 * mm)
p6.lineTo(ix + 1 * mm, yy + 0.6 * mm)
p6.close()
c.setFillColor(INK)
c.drawPath(p6, stroke=0, fill=1)
w_ = text(c, "Section 4.4", ix + 3.4 * mm, yy, "Sans-B", 6.4)
text(c, "3 added  ·  1 covered, 1 partly, 1 missing", ix + 6 * mm + w_, yy, "Sans", 6, MUTED)
yy -= 5.4 * mm
for st, fill, col, b1, ours in [("Our label says this", SURFACE2, INK, 0.62, 0.55),
                                ("Partly in our label", MARK, INK, 0.5, 0.44),
                                ("Not in our label", DANGER, WHITE, 0.56, 0)]:
    chip(c, ix + 3.4 * mm, yy - 1 * mm, st, fill=fill, color=col)
    c.setFillColor(INK)
    c.rect(ix + 36 * mm, yy - 0.6 * mm, (iw - 40 * mm) * b1, 1.8 * mm, stroke=0, fill=1)
    if ours:
        text(c, "Ours:", ix + 36 * mm, yy - 4.2 * mm, "Sans-B", 5.6, MUTED)
        bars(c, ix + 43 * mm, yy - 4.2 * mm, (iw - 47 * mm) * ours, HexColor("#C9C3B6"))
        yy -= 8 * mm
    else:
        yy -= 5 * mm
tag(c, tagx, yy + 16 * mm, "D")
yy -= 1.6 * mm
dot(c, ix, yy - 0.3 * mm, BEACON)
text(c, "No decision yet", ix + 3.2 * mm, yy, "Sans-B", 6.2)
yy -= 2.6 * mm
bw_ = lbutton(c, ix, yy, "Concerns us", size=6)
bw_ += lbutton(c, ix + bw_ + 2 * mm, yy, "Doesn't concern us", size=6)
lbutton(c, ix + iw - 44 * mm, yy, "Not the reference product", size=6)
tag(c, tagx, yy - 2.4 * mm, "E")
y -= fh + 3.5 * mm
y = legend(c, [("A", "Our label", "The version in use."),
               ("B", "The change", "Reference product first."),
               ("C", "In one line", "Covered, partly, missing."),
               ("D", "Each sentence", "Theirs, and our closest."),
               ("E", "The decision", "And the reference mark.")], y, 5) - 6 * mm

y = label(c, "How to upload our label", y)
top = y
yl = steps(c, ["On the ingredient's screen, under <b>Label changes</b>, press <b>Upload our label</b> (or "
               "<b>Replace</b>). Reviewers and administrators.",
               "Give the <b>Product</b> (name and strength), the <b>Version</b> (which approval) and the "
               "<b>Language</b> (en, ar, fr).",
               "Choose the PDF or text file, or paste the text. A PDF is read on this computer; only the sections "
               "found are saved."], ML, y, colw)
yr = steps(c, ["Check <b>Sections found</b>. At least one safety section, 4.1 to 4.9, is needed; each heading "
               "starts its own line.",
               "Press <b>Save this version</b>. It is compared with the label changes of the last year within 4 "
               "hours, on the next collection run. The version before stays on record."],
           ML + colw + 8 * mm, top, colw, start=4)
y = min(yl, yr) - 3 * mm
y = label(c, "The words beside each added sentence", y)
y = table(c, [
    ("Our label says this", "Three quarters or more of its words are in one sentence of ours, shown after Ours."),
    ("Partly in our label", "Some of its words are in one sentence of ours. Read both."),
    ("Not in our label", "Few or none of its words are in that section of ours."),
    ("Not compared", "Our label is in another language: labels are never compared across languages, so compare "
                     "them by eye. Or our label was just uploaded, and the next run compares it."),
], y, [44 * mm, CW - 44 * mm], styles=[cell_b, cell_st]) - 5 * mm
y = notes_row(c, [
    ("The reference product", "One product per ingredient, the originator's as a rule: <b>Mark as the reference "
                              "product</b>. Its changes come first, on screen and in the weekly report."),
    ("By the day it was found", "A change counts in the days it was detected, not on the date printed on the "
                                "label."),
    ("In the weekly report", "Under each ingredient, one line: “Our label: 2 covered, 1 partly, 1 missing”, or why "
                             "it was not compared."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 9 · A FINDING THAT CONCERNS US: THE FIVE-DAY CLOCK ═════════════════════════
new_page("When a finding concerns us")
y = running_head(c, "03  ·  When a finding concerns us  ·  the five-day clock")
y = head(c, "03", "The five-day clock to the authority", y, sub="A drawing, not real data")
y = para(c, "A finding that concerns us must reach the Egyptian Drug Authority within five days. PHAROS keeps "
            "that clock for each notice, in one line under its decision.", what_st, ML, y, CW) - 4 * mm

# the clock, drawn: seven Cairo days
th = 25 * mm
frame(c, ML, y, CW, th)
dx0 = ML + 10 * mm
dstep = (CW - 20 * mm) / 6
ly = y - 13 * mm
days_ = ["Sun 1", "Mon 2", "Tue 3", "Wed 4", "Thu 5", "Fri 6", "Sat 7"]
c.setFillColor(MARK)
c.rect(dx0, ly - 1.2 * mm, dstep * 5, 2.4 * mm, stroke=0, fill=1)
c.setFillColor(HexColor("#E9C9C6"))
c.rect(dx0 + dstep * 5, ly - 1.2 * mm, dstep, 2.4 * mm, stroke=0, fill=1)
rule(c, dx0, ly, dx0 + dstep * 6, INK, 0.8)
for k, d in enumerate(days_):
    x = dx0 + k * dstep
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.line(x, ly - 1.6 * mm, x, ly + 1.6 * mm)
    tw = pdfmetrics.stringWidth(d + " Nov", "Sans", 6)
    text(c, d + " Nov", x - tw / 2, ly - 5 * mm, "Sans-B" if k in (0, 5) else "Sans", 6, INK if k in (0, 5) else MUTED)
for k, t1, t2 in [(0, "Day zero", "PHAROS first showed the notice"), (2, "Concerns us", "recorded, clock running"),
                  (5, "Due", "day zero + 5")]:
    x = dx0 + k * dstep
    w1 = pdfmetrics.stringWidth(t1, "Sans-B", 6.4)
    w2 = pdfmetrics.stringWidth(t2, "Sans", 5.6)
    text(c, t1, x - 1 * mm if k == 0 else x - w1 / 2, ly + 6.4 * mm, "Sans-B", 6.4, DEEP)
    text(c, t2, x - 1 * mm if k == 0 else x - w2 / 2, ly + 3.2 * mm, "Sans", 5.6, MUTED)
text(c, "late", dx0 + dstep * 5.5 - pdfmetrics.stringWidth("late", "Sans-B", 6) / 2, ly - 9 * mm, "Sans-B", 6, DANGER)
y -= th + 5 * mm

# the decision with its clock, and the form
dw = CW * 0.5
fh = 58 * mm
frame(c, ML, y, dw, fh)
ix = ML + 4 * mm
iw = dw - 8 * mm
rtag = ML + dw - 2.4 * mm
yy = y - 6 * mm
dot(c, ix, yy - 0.3 * mm, SEA)
w_ = text(c, "Concerns us", ix + 3.2 * mm, yy, "Sans-B", 6.4)
text(c, "Sama Mosaad, 3 Nov 2026 10:12", ix + 5 * mm + w_, yy, "Sans", 5.8, MUTED)
yy -= 4.4 * mm
text(c, "Authority: due Fri 6 Nov, 3 days left", ix, yy, "Sans-B", 6.4, DEEP)
tag(c, rtag, yy + 1 * mm, "A")
yy -= 2.4 * mm
lbutton(c, ix, yy, "Change", size=5.8, h=4.4 * mm)
yy -= 6 * mm
lbutton(c, ix, yy, "Sent to the authority", size=6)
tag(c, rtag, yy - 2.4 * mm, "B")
yy -= 8 * mm
rule(c, ix, yy + 1.6 * mm, ix + iw, RULE)
text(c, "Sent to the Egyptian Drug Authority", ix, yy - 1.6 * mm, "Sans-B", 6.6)
yy -= 5 * mm
for lab_, val, w0 in [("Day sent", "05/11/2026", 26), ("Reference (optional)", "EDA/2026/0042", 34)]:
    micro(c, lab_, ix, yy - 1.2 * mm, size=4.8, spacing=0.5)
    c.setStrokeColor(RULE)
    c.setFillColor(WHITE)
    c.rect(ix + 26 * mm, yy - 3 * mm, w0 * mm, 4.4 * mm, stroke=1, fill=1)
    text(c, val, ix + 27.5 * mm, yy - 1.6 * mm, "Mono", 5.8)
    yy -= 5.8 * mm
micro(c, "Note (optional)", ix, yy - 1.2 * mm, size=4.8, spacing=0.5)
c.setStrokeColor(RULE)
c.setFillColor(WHITE)
c.rect(ix + 26 * mm, yy - 5 * mm, iw - 26 * mm, 6.4 * mm, stroke=1, fill=1)
tag(c, rtag, yy + 4.6 * mm, "C")
yy -= 8.6 * mm
lbutton(c, ix, yy, "Record: sent to the authority", dark=True, size=6)
label(c, "How to record that it was sent", y, ML + dw + 7 * mm)
steps(c, ["Press <b>Sent to the authority</b>. Reviewers and administrators see it while the clock runs or is "
          "late.",
          "Give the <b>Day sent</b>: from day zero to today, nothing else. A <b>Reference</b> (the authority's or "
          "our file number) and a <b>Note</b> are optional.",
          "Press <b>Record: sent to the authority</b>. The clock stops on every mention and paper of the notice, "
          "with “Recorded by” and the note under it."], ML + dw + 7 * mm, y - 12, W - MR - ML - dw - 7 * mm)
y -= fh + 3.5 * mm
y = legend(c, [("A", "The clock", "One line under the decision."),
               ("B", "Sent", "While it runs or is late."),
               ("C", "The form", "Day, reference, note.")], y, 3) - 6 * mm

y = label(c, "What the line under the decision says", y)
y = table(c, [
    ("Authority: due Fri 6 Nov, 3 days left", "The clock runs. On the day itself: “due today”."),
    ("Authority: late by 2 days (was due Fri 6 Nov)", "Past the due day and not sent yet."),
    ("Sent to the authority 5 Nov 2026 · ref EDA/2026/0042", "Recorded as sent: the clock has stopped."),
    ("Nothing", "The latest decision is not Concerns us."),
], y, [78 * mm, CW - 78 * mm], styles=[cell_b, cell_st]) - 5 * mm
y = notes_row(c, [
    ("Never forgotten", "A report is never changed or deleted. If the decision becomes Doesn't concern us the clock "
                        "goes off, but the report stays: Concerns us again finds the notice sent."),
    ("Withdrawing", "A report recorded by mistake: <b>Withdraw the report</b>, with the reason. It stays on record "
                    "as withdrawn, and the clock runs again from the same due day."),
    ("The morning reminder", "After 07:00 Cairo, every reviewer and administrator with Telegram gets one message: "
                             "the findings late or due within 2 days. Nothing when nothing is due."),
], y, 3) - 5 * mm
y = para(c, "Today is the Cairo day of the PHAROS server, never the phone's. The weekly report shows what was reported "
            "to the authority in the week, how many findings are due and late, and on each decision its due day and "
            "the day it was sent.", tiny, ML, y, CW) - 6 * mm
y = label(c, "Who does what after a decision", y)
y = table(c, [
    ("Reader", "Sees the decision, the clock line, the signal, its stages and its history. No buttons."),
    ("Reviewer", "Decides Concerns us or Doesn't concern us, records the report as sent or withdraws it, takes every "
                 "signal step, and uploads our label."),
    ("Administrator", "All a reviewer does, and asks for inspection packs (page 20)."),
], y, [30 * mm, CW - 30 * mm], styles=[cell_b, cell_st])
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 10 · A FINDING THAT CONCERNS US: THE SIGNAL STEPS ═════════════════════════
new_page("When a finding concerns us")
y = running_head(c, "03  ·  When a finding concerns us  ·  the signal steps")
y = head(c, "", "Signal steps inside the finding", y, sub="A drawing, not real data")
y = para(c, "A finding that concerns us is also a signal to take through validation, assessment and action. "
            "PHAROS opens it from the decision and keeps it under the finding, so nothing is filled in twice.",
         what_st, ML, y, CW) - 3 * mm
fh = 60 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
tagx = ML + CW - 4.6 * mm
yy = y - 6 * mm
dot(c, ix, yy - 0.3 * mm, SEA)
w_ = text(c, "Concerns us", ix + 3.2 * mm, yy, "Sans-B", 6.4)
w2 = text(c, "Sama Mosaad, 3 Nov 2026 10:12", ix + 5 * mm + w_, yy, "Sans", 5.8, MUTED)
text(c, "Sent to the authority 5 Nov 2026  ·  ref EDA/2026/0042", ix + 9 * mm + w_ + w2, yy, "Sans-B", 6.2, DEEP)
yy -= 6.4 * mm
rule(c, ix, yy + 2 * mm, ix + iw, RULE)
yy -= 2 * mm
w_ = text(c, "SIG-2026-001", ix, yy, "Mono", 6.6)
w2 = text(c, "Signal  ·  High priority", ix + w_ + 3 * mm, yy, "Sans-B", 6.6)
w3 = text(c, "Assess by Fri 4 Dec", ix + w_ + w2 + 8 * mm, yy, "Sans-B", 6.6, DEEP)
tag(c, tagx, yy + 1 * mm, "A")
yy -= 4.6 * mm
# the chain
lw_ = (iw - 3 * 2 * mm) / 4
for k, (n, t) in enumerate([("01", "Validate"), ("02", "Assess"), ("03", "Action"), ("04", "Closed")]):
    x = ix + k * (lw_ + 2 * mm)
    cur, done = k == 1, k < 1
    c.setFillColor(INK if cur else (SURFACE2 if done else WHITE))
    c.setStrokeColor(INK if cur else RULE)
    c.setLineWidth(0.6)
    c.rect(x, yy - 6 * mm, lw_, 6 * mm, stroke=0 if cur else 1, fill=1)
    text(c, n, x + 2.4 * mm, yy - 3.9 * mm, "Mono", 5.6, BEACON if cur else MUTED)
    text(c, t, x + 8 * mm, yy - 3.9 * mm, "Sans-B", 6.6, WHITE if cur else (INK if done else MUTED))
tag(c, tagx, yy - 3 * mm, "B")
yy -= 9.6 * mm
lbutton(c, ix, yy, "Record the assessment", dark=True, size=6)
tag(c, tagx, yy - 2.4 * mm, "C")
yy -= 8.4 * mm
micro(c, "Outcome", ix, yy - 1 * mm, size=4.8, spacing=0.5)
c.setStrokeColor(RULE)
c.setFillColor(WHITE)
c.rect(ix + 24 * mm, yy - 2.8 * mm, 46 * mm, 4.4 * mm, stroke=1, fill=1)
text(c, "Update our label", ix + 25.5 * mm, yy - 1.5 * mm, "Sans", 6)
micro(c, "Action due", ix + 76 * mm, yy - 1 * mm, size=4.8, spacing=0.5)
c.setFillColor(WHITE)
c.rect(ix + 94 * mm, yy - 2.8 * mm, 26 * mm, 4.4 * mm, stroke=1, fill=1)
text(c, "04/02/2027", ix + 95.5 * mm, yy - 1.5 * mm, "Mono", 5.8)
yy -= 5.8 * mm
micro(c, "The conclusion", ix, yy - 1 * mm, size=4.8, spacing=0.5)
c.setFillColor(WHITE)
c.rect(ix + 24 * mm, yy - 4.6 * mm, iw - 24 * mm, 6.2 * mm, stroke=1, fill=1)
yy -= 8.6 * mm
rule(c, ix, yy + 1.4 * mm, ix + iw, RULE)
yy -= 1.6 * mm
for what, who, why in [("Opened the signal", "Sama Mosaad  ·  3 Nov 2026 10:12",
                        "Opened when the notice was marked Concerns us"),
                       ("Validated  ·  High", "Sama Mosaad  ·  4 Nov 2026 09:30", None)]:
    w_ = text(c, what, ix, yy, "Sans-B", 6.2)
    text(c, who, ix + 34 * mm, yy, "Mono", 5.6, MUTED)
    if why:
        text(c, why, ix + 80 * mm, yy, "Sans", 5.8)
    else:
        c.setFillColor(INK)
        c.rect(ix + 80 * mm, yy - 0.2 * mm, 40 * mm, 1.8 * mm, stroke=0, fill=1)
    yy -= 4.4 * mm
tag(c, tagx, yy + 7 * mm, "D")
y -= fh + 3.5 * mm
y = legend(c, [("A", "The signal", "Its reference and next due day."),
               ("B", "The stages", "The current one lit."),
               ("C", "The next step", "One form, words required."),
               ("D", "The history", "Who, when, and what they wrote.")], y, 4) - 6 * mm

y = label(c, "The stages, and the step each one waits for", y)
y = table(c, [
    ("Validate", "<b>It is a signal</b>, with its priority and why; or <b>Not a signal</b>, with why, which closes "
                 "it. Due 30 days after it was opened."),
    ("Assess", "<b>Record the assessment</b>: the outcome and the conclusion. Refuted, Keep monitoring and No action "
               "needed close it. Update our label, Update the RMP, Send a DHPC and Report in the next PSUR open an "
               "action, with the day it is due. Due 30, 60 or 90 days after validation, by priority."),
    ("Action", "<b>Action done</b>: what was done, with its reference. It closes the signal."),
    ("Closed", "<b>Reopen</b>, with why."),
], y, [24 * mm, CW - 24 * mm], styles=[cell_b, cell_st]) - 5 * mm
y = notes_row(c, [
    ("Opened once", "Concerns us opens the signal, named after the notice, for its ingredient, by the person who "
                    "decided. Concerns us again later opens no second one."),
    ("If the decision changes", "Still at Validate with no step taken, Doesn't concern us closes it as not "
                                "validated: “Decision changed:” and the reason. Validated, it stays open."),
    ("Late, and the reminder", "Past the due day the line says <b>late</b>. The morning message lists the steps "
                               "late or due within 2 days, after the findings."),
], y, 3) - 5 * mm
y = para(c, "Every step needs words for the record and is never edited. If two people take a step at once, the "
            "second is refused and the screen reloads. Readers see the stages and the history, without buttons. A "
            "paper filed under a notice shows the same clock and steps. The weekly report gives each decision its "
            "signal and counts the signals open and the steps late.", tiny, ML, y, CW) - 6 * mm
y = label(c, "One signal, from the decision to the end", y)
top = y
yl = steps(c, ["<b>3 Nov.</b> Sama Mosaad marks the notice Concerns us. SIG-2026-001 opens at Validate, due 3 Dec, "
               "and the five-day clock shows under the decision.",
               "<b>4 Nov.</b> <b>It is a signal</b>, High priority, with why. Assess by 4 Dec."], ML, y, colw)
yr = steps(c, ["<b>20 Nov.</b> <b>Record the assessment</b>: Update our label, with the conclusion and the day the "
               "action is due.",
               "<b>The day it is done.</b> <b>Action done</b>, with what was done and its reference. The signal is "
               "closed; its history stays."], ML + colw + 8 * mm, top, colw, start=3)
y = min(yl, yr)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 11 · SOURCES ═════════════════════════
new_page("Sources")
y = running_head(c, "04  ·  Sources  ·  the horizontal pass")
y = head(c, "04", "Sources: every authority, by eye", y, sub="A drawing, not real data")
y = para(c, "One card per country, her 25 countries first, then other authorities: the pages you check, and "
            "everything its authorities published since you last looked.", what_st, ML, y, CW) - 3 * mm
fh = 92 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
# the tabs
x = ix
yy = y - 6 * mm
for i, n in enumerate(["Ingredients", "Sources", "Reports", "People"]):
    f = "Sans-B" if i == 1 else "Sans"
    w_ = text(c, n, x, yy, f, 7.2, INK if i == 1 else MUTED)
    if i == 1:
        c.setFillColor(BEACON)
        c.rect(x, yy - 2.6 * mm, w_, 0.8 * mm, stroke=0, fill=1)
        w_ += 1.5 * mm + chip(c, x + w_ + 1.5 * mm, yy - 0.9 * mm, "12 new", size=5.4, fill=BEACON)
        tag(c, x + w_ + 4.5 * mm, yy + 1 * mm, "A")
        w_ += 6 * mm
    x += w_ + 7 * mm
rule(c, ML, yy - 2.6 * mm, ML + CW, RULE)
yy -= 9 * mm
text(c, "Germany", ix, yy, "Serif-B", 11)
text(c, "BfArM  ·  PEI", ix + 20 * mm, yy, "Sans", 6.4, MUTED)
yy -= 3.4 * mm
rule(c, ix, yy, ix + iw, INK, 0.7)
yy -= 4.4 * mm
micro(c, "The pages you check", ix, yy, size=5.2, spacing=0.7, color=INK)
yy -= 4.6 * mm
for bw, kind, st, col in [(34, "DHPC", "Read by the app", SEA),
                          (28, "Safety notifications", "Read by the app", SEA),
                          (24, "Drug database", "Not read by the app — open it yourself", BEACON)]:
    bars(c, ix, yy, bw * mm, HexColor("#9DB3C7"))
    rule(c, ix, yy - 0.4 * mm, ix + bw * mm, SEA, 0.4)
    text(c, kind, ix + 48 * mm, yy, "Sans", 6, MUTED)
    dot(c, ix + 78 * mm, yy - 0.2 * mm, col)
    text(c, st, ix + 81 * mm, yy, "Sans-B" if col == BEACON else "Sans", 6.2)
    yy -= 4.6 * mm
tag(c, tagx, yy + 9 * mm, "B")
yy -= 2 * mm
rule(c, ix, yy + 1.6 * mm, ix + iw, RULE)
yy -= 3 * mm
w_ = text(c, "New since you last looked", ix, yy, "Sans-B", 7.6)
text(c, " (3)", ix + w_, yy, "Sans", 7.6, MUTED)
text(c, "since 4 Nov 2026 10:12, when you last looked", ix, yy - 3.6 * mm, "Sans", 5.8, MUTED)
button(c, ix + iw, yy + 3.4 * mm, "Mark as looked at", dark=False, size=6.2)
tag(c, tagx, yy + 0.6 * mm, "C")
yy -= 8.6 * mm
for d, typ, hit, b1, b2 in [("6 Nov 2026", "DHPC letter", True, 0.72, 0.38), ("5 Nov 2026", "Safety update", False,
                                                                                0.6, 0.0),
                            ("3 Nov 2026", "", False, 0.66, 0.3)]:
    micro(c, d + ("  ·  " + typ if typ else ""), ix, yy, size=5, spacing=0.6)
    if hit:
        chip(c, ix + 40 * mm, yy - 1 * mm, "Matches a watched ingredient", fill=MARK)
    c.setFillColor(SEA)
    c.rect(ix, yy - 4.4 * mm, iw * b1, 1.8 * mm, stroke=0, fill=1)
    if b2:
        c.rect(ix, yy - 7.2 * mm, iw * b2, 1.8 * mm, stroke=0, fill=1)
    yy -= 9.6 * mm if b2 else 7 * mm
tag(c, tagx, yy + 18 * mm, "D")
rule(c, ix, yy + 1.8 * mm, ix + iw, RULE)
yy -= 1.6 * mm
w_ = text(c, "This week's reading", ix, yy, "Sans-B", 7.2)
text(c, "84 checks  ·  7 new  ·  1 matched", ix + w_ + 4 * mm, yy, "Sans", 6.2, MUTED)
yy -= 5.4 * mm
bars(c, ix, yy, 30 * mm, HexColor("#9DB3C7"))
fx_ = ix + 52 * mm
for k, (lab, v, btn) in enumerate([("Checks", "42", False), ("Failed", "0", False), ("New", "3", True),
                                   ("Matched", "1", True), ("Last checked", "2 h ago", False)]):
    xx = fx_ + k * 15 * mm
    micro(c, lab, xx, yy + 2.2 * mm, size=4.6, spacing=0.4)
    if btn:
        c.setStrokeColor(INK)
        c.setLineWidth(0.6)
        c.setFillColor(WHITE)
        c.rect(xx, yy - 2 * mm, 7 * mm, 3.8 * mm, stroke=1, fill=1)
        text(c, v, xx + 2.4 * mm, yy - 0.9 * mm, "Sans-B", 6.2)
    else:
        text(c, v, xx, yy - 0.9 * mm, "Mono", 6.2)
switch(c, ix + iw - 7 * mm, yy - 1.2 * mm, on=True)
tag(c, tagx, yy, "E")
y -= fh + 3.5 * mm
y = legend(c, [("A", "The tab", "New items, all countries."),
               ("B", "Her pages", "Read by the app, or not."),
               ("C", "Mark as looked at", "The count starts again."),
               ("D", "New items", "Date, title as published."),
               ("E", "This week", "New and Matched open the items.")], y, 5) - 5 * mm

y = label(c, "The horizontal pass, country by country", y)
top = y
yl = steps(c, ["Open <b>Sources</b>. Its tab says how many items are new since you last looked.",
               "On each card, read <b>New since you last looked</b>: every item, with its date and its title in "
               "its own language. Open a title to read the authority's own page.",
               "An item marked <b>Matches a watched ingredient</b> is also on that ingredient's screen: record "
               "the decision there."], ML, y, colw)
yr = steps(c, ["Open each page marked <b>Not read by the app — open it yourself</b>, and look at it.",
               "Press <b>Mark as looked at</b>. The count starts again from now, for you only, for every authority "
               "of that country."], ML + colw + 8 * mm, top, colw, start=4)
y = min(yl, yr) - 3.5 * mm
y = label(c, "What the marks on her pages mean", y)
y = table(c, [
    ("Read by the app", "PHAROS reads the page and lists what is new on it."),
    ("Read by the app, by e-mail subscription", "The site refuses PHAROS, so its newsletter is read from the "
                                                "pharmacovigilance mailbox instead."),
    ("Partly read by the app", "PHAROS reads part of the page. Its note says what to look at by hand."),
    ("Not read by the app — open it yourself", "PHAROS cannot read it. Open it and look; the weekly report lists "
                                               "it under To check by hand."),
], y, [62 * mm, CW - 62 * mm], styles=[cell_b, cell_st]) - 4.5 * mm
y = notes_row(c, [
    ("Since when", "Since you last pressed Mark as looked at. The first time, since Sunday 00:00 Cairo. Never more "
                   "than 31 days back."),
    ("Items that came by e-mail", "An item with no web page opens with <b>Read the e-mail</b>. <b>Save the "
                                  "original e-mail</b> keeps the message."),
    ("For administrators", "<b>Read</b> switches a source off or on. <b>Technical details</b> shows each source's "
                           "address and last error. <b>Add a source</b> tests a link before saving it."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ EDITION 4 · DRAWING HELPERS FOR THE NEW PAGES ═════════════════════════
TONE = {"ok": SEA, "warning": BEACON, "danger": DANGER}
cell_s = ParagraphStyle("cell_s", parent=cell_st, fontSize=6.3, leading=8.4)
cell_sb = ParagraphStyle("cell_sb", parent=cell_s, fontName="Sans-B")


def status(c, x, y, tone, s, size=6):
    """A line as the app marks it: a square in the tone's colour, then the words."""
    dot(c, x, y - 0.2 * mm, TONE[tone])
    return 3.2 * mm + text(c, s, x + 3.2 * mm, y, "Sans" if tone == "ok" else "Sans-B", size)


def link(c, s, x, y, size=6.4, font="Sans-B"):
    w_ = text(c, s, x, y, font, size, SEA)
    rule(c, x, y - 0.8 * mm, x + w_, SEA, 0.4)
    return w_


def tools_right(c, xr, y, items, size=5.6):
    """Buttons ending at xr, on the baseline y, each (words, 'dark' | 'light' | 'quiet'). Returns the left edge."""
    x = xr
    for s, kind in reversed(items):
        if kind == "quiet":
            x -= pdfmetrics.stringWidth(s, "Sans-B", size)
            text(c, s, x, y, "Sans-B", size)
        else:
            x -= pdfmetrics.stringWidth(s, "Sans-B", size) + 4.4 * mm
            lbutton(c, x, y + 3 * mm, s, dark=kind == "dark", size=size, h=4.2 * mm)
        x -= 3 * mm
    return x


def tools_left(c, x, y, items, size=5.6):
    """Buttons starting at x, on the baseline y. Returns the right edge."""
    for s, kind in items:
        if kind == "quiet":
            x += text(c, s, x, y, "Sans-B", size)
        else:
            x += lbutton(c, x, y + 3 * mm, s, dark=kind == "dark", size=size, h=4.2 * mm)
        x += 3 * mm
    return x


def field(c, x, y, w, label_, value="", hint=None, placeholder=False, size=6):
    """A form field: its label over a white box holding its value (a placeholder in grey); y is the label's top."""
    micro(c, label_, x, y - 2 * mm, size=4.8, spacing=0.5, color=INK)
    c.setFillColor(WHITE)
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.rect(x, y - 7.8 * mm, w, 4.6 * mm, stroke=1, fill=1)
    if value:
        text(c, value, x + 1.4 * mm, y - 6.1 * mm, "Sans", size, MUTED if placeholder else INK)
    if hint:
        text(c, hint, x, y - 10.2 * mm, "Sans", 5.1, MUTED)
        return y - 11.6 * mm
    return y - 9.4 * mm


def page_title(c, x, y, eyebrow, title_):
    """The app's page head: a micro eyebrow over a serif title."""
    micro(c, eyebrow, x, y, size=5, spacing=0.7, color=DEEP)
    text(c, title_, x, y - 5.4 * mm, "Serif-B", 11)


# ═════════════════════════ PAGE 12 · SOURCES: LITERATURE REFERENCES ═════════════════════════
new_page("Sources")
y = running_head(c, "04  ·  Sources  ·  literature references")
y = head(c, "", "Literature references, Global and Local", y, sub="A drawing, not real data")
y = para(c, "The first card on Sources: where the literature is screened for every ingredient, and the negative "
            "result of each, week by week. Searched by the app, or checked by hand.", what_st, ML, y, CW) - 3 * mm
fh = 104 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
yy = y - 7.5 * mm
text(c, "Literature references", ix, yy, "Serif-B", 11)
yy -= 4.2 * mm
text(c, "Where the literature is screened for every ingredient, and the negative result of each, week by week.",
     ix, yy, "Sans", 6, MUTED)
yy -= 2.6 * mm
rule(c, ix, yy, ix + iw, INK, 0.7)
yy -= 5.6 * mm
kx = ix + 58 * mm
HAND = [("Checked: nothing found", "light"), ("Checked: found something", "quiet")]
ADMIN = [("Change", "quiet"), ("Remove", "quiet")]
SEARCHED = "Searched by the app — {} searches this week, last 7 Nov 2026, 20:41"
marks = {}
for title_, explain, add, rows in [
    ("Global", "The international literature databases.", "Add a global reference", [
        ("PubMed (NCBI)", False, "ok", SEARCHED.format(28)),
        ("PubMed Central (NCBI)", False, "ok", SEARCHED.format(28)),
        ("Europe PMC", False, "warning", SEARCHED.format(14) + "; 1 read failed"),
        ("Cochrane Database of Systematic Reviews", False, "ok", SEARCHED.format(42)),
        ("Medscape", True, "ok", "Checked by hand — Sama Mosaad, 5 Nov 2026, 11:20: nothing found")]),
    ("Local", "The Egyptian medical journals the Egyptian Drug Authority asks for.", "Add a local reference", [
        ("Al-Azhar Medical Journal", True, "danger", "Checked by hand — not checked this week"),
        ("Ain Shams Medical Journal", True, "warning",
         "Checked by hand — Sama Mosaad, 5 Nov 2026, 11:32: found — a review article, no case report")]),
]:
    marks[title_] = yy
    micro(c, title_, ix, yy, size=5.8, spacing=0.8, color=INK)
    text(c, explain, ix + 16 * mm, yy, "Sans", 5.8, MUTED)
    yy -= 6 * mm
    for name, hand, tone, st in rows:
        link(c, name, ix, yy)
        text(c, "By hand" if hand else "By the app", kx, yy, "Sans", 5.8, MUTED)
        tools_right(c, ix + iw, yy, (HAND if hand else []) + ADMIN)
        status(c, ix, yy - 3.9 * mm, tone, st, size=5.9)
        marks[name] = yy
        rule(c, ix, yy - 5.8 * mm, ix + iw, RULE)
        yy -= 9 * mm
    lbutton(c, ix, yy + 3.4 * mm, add, size=5.8, h=4.4 * mm)
    marks[add] = yy
    yy -= 6.4 * mm
tag(c, tagx, marks["Global"] + 0.8 * mm, "A")
tag(c, tagx, marks["Europe PMC"] - 3 * mm, "B")
tag(c, tagx, marks["Medscape"] - 3 * mm, "C")
tag(c, tagx, marks["Al-Azhar Medical Journal"] + 1 * mm, "D")
tag(c, tagx, marks["Add a local reference"] + 1.2 * mm, "E")
y -= fh + 3.5 * mm
y = legend(c, [("A", "Global and Local", "Two lists, in her order."),
               ("B", "By the app", "Its searches; a failed read shows."),
               ("C", "By hand", "Who checked, when, the answer."),
               ("D", "The two buttons", "Reviewers and administrators."),
               ("E", "Administrators", "Add, Change, Remove.")], y, 5) - 4 * mm

y = label(c, "Every week, the references checked by hand", y)
top = y
yl = steps(c, ["Open <b>Sources</b>. <b>Literature references</b> is the first card: how each reference was "
               "screened this week.",
               "Open each reference marked <b>By hand</b> (Medscape and the two Egyptian journals) and search it for "
               "every ingredient on the watchlist.",
               "Nothing found: press <b>Checked: nothing found</b>, then <b>Record: nothing found</b>. It asks twice "
               "because a recorded check can never be changed."], ML, y, colw)
yr = steps(c, ["Something found: press <b>Checked: found something</b>, write what was found (the article, its "
               "link or its reference) and press <b>Record the check</b>. Then assess it as a possible case "
               "(page 16).",
               "A line in red, <b>not checked this week</b>, is still to do. A line saying a read failed is not a "
               "negative result: search that database yourself."], ML + colw + 8 * mm, top, colw, start=4)
y = min(yl, yr) - 3.5 * mm
y = label(c, "Lines that ask for you", y)
y = table(c, [
    ("…; 1 read failed  ·  Not searched by the app this week yet", "A read of that database failed, or it was not "
                                                                   "searched yet: no negative result is claimed."),
    ("Checked by hand — not checked this week", "Nobody has recorded a check of it this week."),
], y, [70 * mm, CW - 70 * mm], styles=[cell_b, cell_st]) - 5 * mm
y = notes_row(c, [
    ("Every search logged", "Each search PHAROS sends is logged: the database, the words, the days and how many "
                            "records came back, 0 included. Nothing logged can be changed or deleted, by anyone."),
    ("Cochrane and Medscape", "Every Cochrane review is indexed in PubMed and Europe PMC, so the app's searches cover "
                              "it, counted by journal. Medscape refuses automatic access: it is checked by hand."),
    ("For administrators", "<b>Add a global reference</b> or <b>Add a local reference</b>: a name, a link, a note. A "
                           "reference you add is checked by hand. <b>Remove</b> takes it off the list; its checks "
                           "stay in the reports of their weeks."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 13 · SOURCES: EACH INGREDIENT, REFERENCE BY REFERENCE ═════════════════════════
new_page("Sources")
y = running_head(c, "04  ·  Sources  ·  literature references, for each ingredient")
y = head(c, "", "Each ingredient, reference by reference", y, sub="A drawing, not real data")
y = para(c, "On the ingredient's screen under 04 Literature, and in the reports: how each reference was screened in "
            "the days you chose, and what was found. The negative result is written, Nothing found, even in a week "
            "with no paper.", what_st, ML, y, CW) - 3 * mm
fh = 74 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
yy = screen_sec(c, ix, y - 4 * mm, iw, "04", "Literature", "3")
text(c, "3 papers in these days: 3 name the ingredient, 0 only its class  ·  3 in PubMed, 1 in PubMed Central, 0 in "
        "Europe PMC", ix, yy - 1 * mm, "Sans", 6.6)
yy -= 5.6 * mm
micro(c, "Literature references: how each was screened in these days, and what was found", ix, yy, size=5,
      spacing=0.6)
yy -= 1.4 * mm
BYAPP = "By the app — {} searches, last 7 Nov 2026, 20:41"
top_ = yy
yy = table(c, [
    ("<font color='#1F4E5F'><u>PubMed (NCBI)</u></font>  <font color='#5B6670'>Global</font>", BYAPP.format(28),
     "3 papers"),
    ("<font color='#1F4E5F'><u>PubMed Central (NCBI)</u></font>  <font color='#5B6670'>Global</font>",
     BYAPP.format(28), "1 paper"),
    ("<font color='#1F4E5F'><u>Europe PMC</u></font>  <font color='#5B6670'>Global</font>",
     BYAPP.format(14) + "; 1 read failed", "Not fully searched — check by hand"),
    ("<font color='#1F4E5F'><u>Cochrane Database of Systematic Reviews</u></font>  "
     "<font color='#5B6670'>Global</font>", BYAPP.format(42), "<b>Nothing found</b>"),
    ("<font color='#1F4E5F'><u>Medscape</u></font>  <font color='#5B6670'>Global</font>",
     "By hand — Sama Mosaad, 5 Nov 2026, 11:20", "<b>Nothing found</b>"),
    ("<font color='#1F4E5F'><u>Al-Azhar Medical Journal</u></font>  <font color='#5B6670'>Local</font>",
     "By hand — not checked in these days", "Not checked"),
    ("<font color='#1F4E5F'><u>Ain Shams Medical Journal</u></font>  <font color='#5B6670'>Local</font>",
     "By hand — Sama Mosaad, 5 Nov 2026, 11:32", "Found — a review article, no case report"),
], yy, [62 * mm, 58 * mm, iw - 120 * mm], header=["Reference", "Screened", "Found"], x0=ix,
    styles=[cell_sb, cell_s, cell_s], pad=1.1 * mm)
tag(c, tagx, top_ - 6.6 * mm, "A")
tag(c, tagx, top_ - 23 * mm, "B")
tag(c, tagx, yy + 4 * mm, "C")
y -= fh + 3.5 * mm
y = legend(c, [("A", "Searched by the app", "Its searches for this ingredient, and its papers."),
               ("B", "Not fully searched", "A read failed: no negative result claimed."),
               ("C", "Checked by hand", "The week's hand check, for every ingredient.")], y, 3) - 6 * mm

y = label(c, "What the Found column says", y)
y = table(c, [
    ("3 papers", "The ingredient's papers first found in these days by that database. For Cochrane, the papers "
                 "whose journal is the Cochrane Database of Systematic Reviews."),
    ("Nothing found", "Only when the ingredient's own name was searched in these days and no read of that database "
                      "failed. For a reference checked by hand: the hand check found nothing."),
    ("Not searched — check by hand", "The ingredient's name was not searched there in these days."),
    ("Not fully searched — check by hand", "A read of that database failed in these days."),
    ("Found — …  ·  Not checked", "A hand check found something, with what was written; or nobody recorded a check in "
                                  "these days. A check that found something speaks for the days, even when a later "
                                  "one found nothing."),
], y, [56 * mm, CW - 56 * mm], styles=[cell_b, cell_st]) - 7 * mm

y = sub_head(c, "The same lines in the reports", y, aside="Kept for the inspection")
y = notes_row(c, [
    ("The weekly and daily report", "Section 02 lists each reference with how it was screened; a gap is in bold. "
                                    "Section 04 gives each ingredient's references: Screened and Found, Nothing found "
                                    "in words. The Excel file has the sheet <b>Literature references</b>."),
    ("The PSUR pack", "§11 Literature carries each reference over the pack's days: how often it was searched or "
                      "checked by hand, and what was found. The Excel file has the sheet <b>§11 References</b>."),
    ("Nothing logged changes", "The search log and the hand checks can never be changed or deleted, by any role. A "
                               "reference removed later stays in the reports of the weeks it was checked."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 14 · SOURCES: FOR ADMINISTRATORS ═════════════════════════
new_page("Sources")
y = running_head(c, "04  ·  Sources  ·  for administrators")
y = head(c, "", "Her pages, her authorities, her sources", y, sub="A drawing, not real data")
y = para(c, "An administrator keeps Sources right herself: the pages on each country's card, an authority she checks "
            "by hand, the sources PHAROS reads, and the literature references.", what_st, ML, y, CW) - 3 * mm
fh = 111 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
yy = y - 6 * mm
page_title(c, ix, yy, "Screening", "Sources")
xr_ = tools_right(c, ix + iw, yy - 4.6 * mm, [("Add an authority", "light"), ("Add a source", "dark")], size=6)
switch(c, xr_ - 29 * mm, yy - 5.2 * mm, on=False)
text(c, "Technical details", xr_ - 21.6 * mm, yy - 4.6 * mm, "Sans", 6)
tag(c, tagx, yy - 3.6 * mm, "A")
yy -= 9.6 * mm
rule(c, ix, yy, ix + iw, INK, 0.7)
yy -= 5 * mm
text(c, "Add an authority", ix, yy, "Sans-B", 7.4)
tools_right(c, ix + iw, yy, [("Cancel", "quiet")])
yy -= 1.6 * mm
yy = para(c, "An authority you check by hand, with its first link. Its country then joins your list; add more links "
             "on its card. The app does not read a link you add: it says “open it yourself”, so a week with nothing "
             "found there is recorded as checked by you.",
          ParagraphStyle("pn", parent=tiny, fontSize=6.2, leading=8.4), ix, yy, iw) - 2.4 * mm
tag(c, tagx, yy + 6 * mm, "B")
f3 = (iw - 8 * mm) / 3
field(c, ix, yy, f3, "Authority", "A new authority…")
field(c, ix + f3 + 4 * mm, yy, f3, "Country", "Egypt", placeholder=True)
yy = field(c, ix + 2 * (f3 + 4 * mm), yy, f3, "Country code", "EG", hint="Two letters, as on its flag",
           placeholder=True)
field(c, ix, yy, 2 * f3 + 4 * mm, "Authority’s name", "Egyptian Drug Authority", placeholder=True)
yy = field(c, ix + 2 * (f3 + 4 * mm), yy, f3, "Short name", "", hint="Latin letters, such as EDA") - 1 * mm
micro(c, "Its first link", ix, yy - 1 * mm, size=5.2, spacing=0.7, color=DEEP)
yy -= 3 * mm
field(c, ix, yy, f3, "Name in the list", "Safety communications", placeholder=True)
field(c, ix + f3 + 4 * mm, yy, f3, "Link", "https://", placeholder=True)
yy = field(c, ix + 2 * (f3 + 4 * mm), yy, f3, "What it is", "Safety notifications")
yy -= 1.4 * mm
tools_left(c, ix, yy - 3 * mm, [("Add the authority", "dark"), ("Cancel", "quiet")], size=6)
yy -= 9 * mm
rule(c, ix, yy, ix + iw, RULE)
yy -= 6.4 * mm
text(c, "Egypt", ix, yy, "Serif-B", 11)
text(c, "EDA", ix + 13 * mm, yy, "Sans", 6.4, MUTED)
yy -= 3.4 * mm
rule(c, ix, yy, ix + iw, INK, 0.7)
yy -= 4.4 * mm
micro(c, "The pages you check", ix, yy, size=5.2, spacing=0.7, color=INK)
yy -= 4.8 * mm
bars(c, ix, yy, 30 * mm, HexColor("#9DB3C7"))
rule(c, ix, yy - 0.4 * mm, ix + 30 * mm, SEA, 0.4)
text(c, "Safety notifications", ix + 48 * mm, yy, "Sans", 6, MUTED)
status(c, ix + 76 * mm, yy, "warning", "Not read by the app — open it yourself", size=6)
tools_right(c, ix + iw, yy, [("Change", "quiet"), ("Remove", "quiet")])
tag(c, tagx, yy + 1 * mm, "C")
yy -= 3.4 * mm
yy -= 5 * mm
lbutton(c, ix, yy, "Add a link", size=5.8, h=4.4 * mm)
tag(c, tagx, yy - 2.2 * mm, "D")
y -= fh + 3.5 * mm
y = legend(c, [("A", "At the top", "An authority, or a source PHAROS reads."),
               ("B", "Add an authority", "Known, or new, with its first link."),
               ("C", "Each link", "Change it, or remove it."),
               ("D", "Add a link", "On any country's card.")], y, 4) - 6 * mm

y = label(c, "What an administrator changes on Sources", y)
y = table(c, [
    ("A page on a country's card", "<b>Add a link</b> at the foot of the card: the authority, its name in the list, "
                                   "the link, what it is (Safety notifications, DHPC, Drug database) and a note. "
                                   "<b>Change</b> and <b>Remove</b> on each link. A link she adds is not read by the "
                                   "app: it says <b>Not read by the app — open it yourself</b>. Removing a link the "
                                   "app also reads only takes it off her list; the app keeps reading it."),
    ("An authority", "<b>Add an authority</b>: one already known that has no links yet, or <b>A new authority…</b> "
                     "with its country, two-letter code, name and short name; then its first link. Its country joins "
                     "her list."),
    ("A source PHAROS reads", "<b>Add a source</b>: paste the link and press <b>Test this link</b>; PHAROS reads it "
                              "once and shows what it found before you save it. <b>Read</b> switches any source off "
                              "or on. A source added by hand can be changed or removed: one never read is deleted, "
                              "one already read is switched off and kept."),
    ("A literature reference", "<b>Add a global reference</b> or <b>Add a local reference</b>, <b>Change</b>, "
                               "<b>Remove</b> (page 12)."),
], y, [44 * mm, CW - 44 * mm], styles=[cell_b, cell_st]) - 6 * mm
y = notes_row(c, [
    ("Only administrators", "These buttons show to administrators only. Everyone else sees the same cards without "
                            "them."),
    ("In the audit log", "Every change to a link, an authority or a literature reference is written to the audit "
                         "log, with who made it and when."),
    ("Technical details", "The switch at the top shows each source's address and its last error."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 15 · CASES AND PRODUCTS: THE PRODUCT LIST ═════════════════════════
new_page("Cases and products")
y = running_head(c, "05  ·  Cases and products  ·  the product list")
y = head(c, "05", "Products: what a case is about", y, sub="A drawing, not real data")
y = para(c, "Our products, each with its active ingredients and strengths. A case is opened against the product and "
            "its strength; the literature, the label watch and the reports follow each ingredient.", what_st, ML, y,
         CW) - 3 * mm
fh = 122 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
yy = y - 6 * mm
page_title(c, ix, yy, "Watchlist", "Products")
tools_right(c, ix + iw, yy - 4.6 * mm, [("Add a product", "dark")], size=6)
tag(c, tagx, yy - 3.6 * mm, "A")
yy -= 10.4 * mm
yy = screen_sec(c, ix, yy, iw, "01", "Add a product") - 1 * mm
field(c, ix, yy, f3, "Product name", "Carvexa", hint="As it is registered, e.g. Carvexa")
field(c, ix + f3 + 4 * mm, yy, f3, "Marketing authorisation holder", "Sato Pharma")
yy = field(c, ix + 2 * (f3 + 4 * mm), yy, f3, "Dosage form", "film-coated tablet", hint="e.g. film-coated tablet")
micro(c, "Ingredients", ix, yy - 2.6 * mm, size=5.2, spacing=0.7, color=DEEP)
yy -= 7 * mm
x_ = ix
for n_, on_ in [("Carvedilol", True), ("Levofloxacin", False), ("Lornoxicam", False)]:
    switch(c, x_, yy - 0.6 * mm, on=on_)
    x_ += 8 * mm + text(c, n_, x_ + 8 * mm, yy, "Sans-B" if on_ else "Sans", 6.2, INK if on_ else MUTED) + 6 * mm
tag(c, tagx, yy + 1 * mm, "B")
yy -= 4.6 * mm
micro(c, "Strengths", ix, yy - 1 * mm, size=5.2, spacing=0.7, color=DEEP)
yy -= 3 * mm
sw4 = 24 * mm
for amt, last in [("6.25", False), ("12.5", True)]:
    field(c, ix, yy, sw4, "Carvedilol", amt)
    field(c, ix + sw4 + 3 * mm, yy, 16 * mm, "Unit", "mg")
    yy2 = field(c, ix + sw4 + 22 * mm, yy, 60 * mm, "Name of the strength", "",
                hint="Leave empty: it is named from the amounts" if last else None)
    tools_right(c, ix + iw, yy - 6.4 * mm, [("Remove this strength", "quiet")])
    yy = yy2
tag(c, tagx, yy + 10 * mm, "C")
yy -= 0.6 * mm
tools_left(c, ix, yy - 3 * mm, [("Add a strength", "light")])
yy -= 7 * mm
tools_left(c, ix, yy - 3 * mm, [("Add the product", "dark"), ("Cancel", "quiet")], size=6)
yy -= 8 * mm
yy = screen_sec(c, ix, yy, iw, "02", "Products", "2 on the list")
px_ = [ix, ix + 62 * mm, ix + 104 * mm]
for lab_, x_ in zip(["Product", "Ingredients", "Strengths"], px_, strict=True):
    micro(c, lab_, x_, yy, size=5, spacing=0.6)
rule(c, ix, yy - 1.6 * mm, ix + iw, INK, 0.6)
yy -= 5.4 * mm
for name_, sub_, ings, strs, archived in [
        ("Carvexa", "film-coated tablet  ·  Sato Pharma", "Carvedilol", "6.25 mg, 12.5 mg, 25 mg", False),
        ("Product 2", "tablet  ·  Sato Pharma", "Ingredient A + Ingredient B", "6.25 mg / 5 mg", False),
        ("Product 3", "capsule  ·  Sato Pharma", "Ingredient C", "500 mg", True)]:
    w_ = text(c, name_, ix, yy, "Sans-B", 6.6)
    if archived:
        chip(c, ix + w_ + 2 * mm, yy - 0.9 * mm, "Archived", size=5.2)
    text(c, sub_, ix, yy - 3.2 * mm, "Sans", 5.6, MUTED)
    text(c, ings, px_[1], yy, "Sans", 6.4)
    text(c, strs, px_[2], yy, "Sans", 6.4)
    tools_right(c, ix + iw, yy - 1 * mm, [("Change", "light")])
    rule(c, ix, yy - 5.2 * mm, ix + iw, RULE)
    yy -= 8.6 * mm
tag(c, tagx, yy + 13 * mm, "D")
y -= fh + 3.5 * mm
y = legend(c, [("A", "Add a product", "Administrators only."),
               ("B", "Ingredients", "Each one on the watchlist."),
               ("C", "Strengths", "An amount per ingredient."),
               ("D", "The list", "Offered on every new case.")], y, 4) - 6 * mm

y = label(c, "How to add a product", y)
top = y
yl = steps(c, ["Open <b>Products</b> and press <b>Add a product</b>.",
               "Type the <b>Product name</b> as it is registered, the holder (Sato Pharma unless another) and the "
               "dosage form.",
               "Under <b>Ingredients</b>, switch on each active ingredient of the product. Only ingredients on the "
               "watchlist are offered: add a missing one on Ingredients first."], ML, y, colw)
yr = steps(c, ["Under <b>Strengths</b>, give each ingredient's amount and unit; <b>Add a strength</b> for each "
               "other strength. Left empty, its name is made from the amounts, such as 6.25 mg / 5 mg.",
               "Press <b>Add the product</b>. It is offered at once under <b>Product or ingredient</b> on every new "
               "case."], ML + colw + 8 * mm, top, colw, start=4)
y = min(yl, yr) - 5 * mm
y = notes_row(c, [
    ("Take off the list", "<b>Change</b>, then <b>Take off the list</b>. A product a case names is archived, never "
                          "deleted: it stays on that case and is no longer offered."),
    ("Locked by a case", "Once a case names a product, its ingredients and that strength's amounts can no longer "
                         "change."),
    ("Each ingredient counts", "A case of a product counts for each of its ingredients: on the ingredient's screen, "
                               "under <b>05 Reactions by MeSH</b>, in the <b>Cases</b> column."),
    ("Who", "Everyone sees the list. Only an administrator adds, changes or takes off a product."),
], y, 4, gap=5 * mm)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 16 · CASES: HOW A CASE STARTS, AND THE LIST ═════════════════════════
new_page("Cases and products")
y = running_head(c, "05  ·  Cases and products  ·  cases")
y = head(c, "", "Cases: each individual case safety report", y, sub="A drawing, not real data")
y = para(c, "Each case keeps its source document, the form PHAROS fills from it, your check and confirmation, the "
            "clock to the authority, and the CIOMS I form or E2B(R3) file.", what_st, ML, y, CW) - 3 * mm
fh = 94.5 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
yy = y - 6 * mm
page_title(c, ix, yy, "Pharmacovigilance", "Cases")
yy -= 10 * mm
yy = screen_sec(c, ix, yy, iw, "01", "New case")
yy = para(c, "Drop the report as it arrived: a PDF, a photo of a form, a Word file, a saved email or a text file. "
             "PHAROS keeps the original and fills in the case form within a few minutes; you check it against the "
             "document and confirm. A report can also be forwarded to the PHAROS mailbox with CASE in the subject.",
          ParagraphStyle("pn2", parent=tiny, fontSize=6.2, leading=8.4), ix, yy, iw) - 2 * mm
field(c, ix + f3 + 4 * mm, yy, f3, "Day zero", "05/11/2026", hint="The day the company first received the report")
field(c, ix + 2 * (f3 + 4 * mm), yy, f3, "Product or ingredient", "PHAROS will suggest it", placeholder=True)
yy = field(c, ix, yy, f3, "Document", "report-0511.pdf", hint="PDF, photo, Word, saved email or text; at most 10 MB")
tag(c, tagx, yy + 9 * mm, "A")
tools_left(c, ix, yy - 3 * mm, [("Open the case", "dark")], size=6)
yy -= 9 * mm
yy = screen_sec(c, ix, yy, iw, "02", "Cases")
c.setFillColor(WHITE)
c.setStrokeColor(RULE)
c.rect(ix + iw - 22 * mm, yy + 3.2 * mm, 22 * mm, 4.4 * mm, stroke=1, fill=1)
text(c, "Open cases  ▾", ix + iw - 20.6 * mm, yy + 4.6 * mm, "Sans", 6)
tag(c, tagx, yy + 5.4 * mm, "B")
yy -= 1 * mm
yy = table(c, [
    ("<b>CASE-2026-003</b><br/><font color='#5B6670'>Uploaded · day zero 5 Nov 2026</font>",
     "To check and confirm<br/><font color='#5B6670'>Missing an identifiable reporter</font>",
     "12 days left (due 2026-11-20)<br/><font color='#5B6670'>Seriousness not decided</font>",
     "Carvexa 6.25 mg", "Female, 54<br/>dizzy and fainted"),
    ("<b>CASE-2026-002</b><br/><font color='#5B6670'>Literature paper · day zero 3 Nov 2026</font>",
     "Confirmed", "10 days left (due 2026-11-18)<br/><font color='#5B6670'>Serious</font>", "Levofloxacin",
     "Male, 71<br/>rash"),
    ("<b>CASE-2026-001</b><br/><font color='#5B6670'>Forwarded email · day zero 20 Oct 2026</font>",
     "Sent to the authority", "Was due 2026-11-04<br/><font color='#5B6670'>Serious</font>", "Carvexa 12.5 mg",
     "Female, 62<br/>bradycardia"),
], yy, [35 * mm, 31 * mm, 34 * mm, 32 * mm, iw - 132 * mm],
    header=["Case", "Where it stands", "Clock", "Product or ingredient", "Patient and reaction"], x0=ix,
    styles=[cell_s] * 5, pad=1.1 * mm)
tag(c, tagx, yy + 14 * mm, "C")
y -= fh + 3.5 * mm
y = legend(c, [("A", "New case", "Reviewers and administrators."),
               ("B", "Open or every case", "Open cases first."),
               ("C", "The list", "Where each stands, and its clock.")], y, 3) - 3.6 * mm

y = label(c, "Three ways a case starts", y)
y = table(c, [
    ("Uploaded", "On <b>Cases</b>, under <b>New case</b>: the document as it arrived, its <b>Day zero</b> (the day "
                 "the company first received the report, today or up to a year back), and the product if you know "
                 "it. Press <b>Open the case</b>."),
    ("Forwarded email", "Forward the report from your own address to the PHAROS mailbox, pharos@satopharma.com, with "
                        "the word CASE in the subject. The case opens by itself; day zero is the day the message is "
                        "dated. Only a reviewer's or an administrator's address is accepted."),
    ("Literature paper", "On a possible case report on an ingredient's screen, press <b>Open a case</b> (page 7). "
                         "Day zero is the day PHAROS found the paper. The paper then shows its case."),
], y, [34 * mm, CW - 34 * mm], styles=[cell_b, cell_st]) - 6 * mm

y = label(c, "Where a case stands", y)
y = table(c, [
    ("Waiting to be read  ·  Being read", "PHAROS keeps the original and reads it. The form appears within a few "
                                          "minutes."),
    ("To check and confirm", "The form is filled: check it against the document (page 17). The list says what is "
                             "missing."),
    ("Confirmed", "Checked and confirmed: ready for the authority. The clock still runs."),
    ("Sent to the authority", "Recorded as sent, with the day and the authority's reference. The clock stops."),
    ("Not a valid case  ·  Could not be read", "Closed with a comment; or the document could not be read: press "
                                               "<b>Read again</b>, or fill the form yourself."),
], y, [60 * mm, CW - 60 * mm], styles=[cell_b, cell_st]) - 6 * mm
y = notes_row(c, [
    ("The clock", "15 days from day zero; 90 days once a reviewer sets <b>Not serious</b>. Until seriousness is "
                  "decided the case counts as serious."),
    ("On the list", "“12 days left”, “Due today”, “Overdue by 2 days”, and once closed “Was due”. An overdue open "
                    "case is marked."),
    ("Who", "Everyone signed in sees the cases. Only reviewers and administrators open, change, confirm and send "
            "them."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 17 · CASES: CHECK, CONFIRM, SEND ═════════════════════════
new_page("Cases and products")
y = running_head(c, "05  ·  Cases and products  ·  check, confirm, send")
y = head(c, "", "A case: check it, confirm it, send it", y, sub="A drawing, not real data")
y = para(c, "PHAROS reads the document and fills the form. A reviewer checks every field against the document, "
            "decides the seriousness, and confirms. PHAROS never sends a case: you do, and record it.", what_st, ML,
         y, CW) - 3 * mm
fh = 118.5 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
yy = y - 6 * mm
page_title(c, ix, yy, "Cases  ·  Uploaded", "CASE-2026-003")
text(c, "report-0511.pdf", ix + 34 * mm, yy - 5.4 * mm, "Sans", 6.2, MUTED)
tools_right(c, ix + iw, yy - 4.6 * mm, [("Open the document", "light")], size=6)
yy -= 10.6 * mm
w_ = chip(c, ix, yy - 0.9 * mm, "To check and confirm", size=5.6, fill=MARK)
text(c, "12 days left (due 2026-11-20)  ·  15 days: serious or not yet decided", ix + w_ + 3 * mm, yy, "Sans", 6.2)
tag(c, tagx, yy + 1 * mm, "A")
yy -= 4.6 * mm
yy = screen_sec(c, ix, yy, iw, "01", "A valid case", "Read 5 Nov 2026, 10:06")
for k_, (crit, ok_) in enumerate([("an identifiable patient", True), ("an identifiable reporter", False),
                                  ("a suspect product", True), ("a reaction", True)]):
    cx_ = ix + (k_ % 2) * 80 * mm
    cy_ = yy - (k_ // 2) * 4.6 * mm
    text(c, crit, cx_, cy_, "Sans", 6.2)
    chip(c, cx_ + 34 * mm, cy_ - 0.9 * mm, "Present" if ok_ else "Missing", size=5.2, fill=SEA if ok_ else DANGER,
         color=WHITE)
tag(c, tagx, yy + 1 * mm, "B")
yy -= 8.6 * mm
f5 = (iw - 16 * mm) / 5
for k_, (lab_, val_) in enumerate([("Seriousness", "Not decided (15 days)"), ("Product or ingredient", "Carvexa"),
                                   ("Strength", "6.25 mg"), ("Type of report", "Spontaneous"),
                                   ("Country (two letters)", "EG")]):
    yy2 = field(c, ix + k_ * (f5 + 4 * mm), yy, f5, lab_, val_, size=5.8)
yy = yy2 - 1 * mm
yy = screen_sec(c, ix, yy, iw, "02", "The case form", "Not saved")
micro(c, "Patient", ix, yy - 0.6 * mm, size=5, spacing=0.6, color=DEEP)
yy -= 2.4 * mm
f6 = (iw - 20 * mm) / 6
for k_, (lab_, val_) in enumerate([("Initials", "M. A."), ("Sex", "Female"), ("Age", "54"), ("Age in", "Years"),
                                   ("Weight (kg)", ""), ("Birth date", "")]):
    yy2 = field(c, ix + k_ * (f6 + 4 * mm), yy, f6, lab_, val_, size=5.8)
yy = yy2
text(c, "“a 54-year-old woman”", ix, yy - 0.4 * mm, "Serif-I", 6.4)
text(c, "patient.age_value  ·  page 1", ix + 26 * mm, yy - 0.4 * mm, "Sans", 5.4, MUTED)
tag(c, tagx, yy + 0.6 * mm, "C")
yy -= 4 * mm
micro(c, "Reactions", ix, yy - 0.6 * mm, size=5, spacing=0.6, color=DEEP)
tools_right(c, ix + iw, yy - 0.6 * mm, [("Add a reaction", "light")])
yy -= 2.4 * mm
f4 = (iw - 12 * mm) / 4
for k_, (lab_, val_, hint_) in enumerate([("As the reporter wrote it", "dizzy and fainted", None),
                                          ("In English", "Dizziness; syncope", None),
                                          ("MedDRA LLT code", "", "8 digits, from the MedDRA browser"),
                                          ("MedDRA version", "", "e.g. 28.1")]):
    yy2 = field(c, ix + k_ * (f4 + 4 * mm), yy, f4, lab_, val_, hint=hint_, size=5.8)
yy = yy2 - 0.6 * mm
yy = screen_sec(c, ix, yy, iw, "03", "Decide")
tools_left(c, ix + iw / 2 + 4 * mm, yy - 6.1 * mm,
           [("Save", "light"), ("Confirm the case", "dark"), ("Not a valid case", "quiet")], size=6)
tag(c, tagx, yy - 5 * mm, "D")
yy = field(c, ix, yy, iw / 2 - 4 * mm, "Comment", "", hint="Kept in the history with the step")
yy -= 1.6 * mm
c3 = (iw - 10 * mm) / 3
yy = screen_sec(c, ix, yy, c3, "04", "E2B(R3) file")
screen_sec(c, ix + c3 + 5 * mm, yy + 6 * mm, c3, "05", "CIOMS I form")
yy_h = screen_sec(c, ix + 2 * (c3 + 5 * mm), yy + 6 * mm, c3, "06", "History")
tools_left(c, ix, yy - 3 * mm, [("Make the E2B file", "light")], size=5.8)
text(c, "Needs each reaction's MedDRA code", ix, yy - 7.6 * mm, "Sans", 5.4, MUTED)
tools_left(c, ix + c3 + 5 * mm, yy - 3 * mm, [("Open the CIOMS I form", "light")], size=5.8)
text(c, "The reactions in the reporter's words", ix + c3 + 5 * mm, yy - 7.6 * mm, "Sans", 5.4, MUTED)
hx_ = ix + 2 * (c3 + 5 * mm)
text(c, "5 Nov 2026, 10:02  ·  Received  ·  Sama Mosaad", hx_, yy_h, "Sans", 5.6)
text(c, "5 Nov 2026, 10:06  ·  Read by PHAROS", hx_, yy_h - 3.4 * mm, "Sans", 5.6)
text(c, "Original SHA-256 9f2c41d0…a41b07e3", hx_, yy_h - 6.8 * mm, "Mono", 5.2, MUTED)
tag(c, tagx, yy_h - 2 * mm, "E")
y -= fh + 3.5 * mm
y = legend(c, [("A", "Where it stands", "Its status and clock."),
               ("B", "A valid case", "Four criteria: Present or Missing."),
               ("C", "The form", "What PHAROS read, with its words."),
               ("D", "Decide", "Save, confirm, or not valid."),
               ("E", "Send and record", "E2B or CIOMS I; the history.")], y, 5) - 3.6 * mm

y = label(c, "How to check and confirm a case", y)
top = y
yl = steps(c, ["Open the case. Press <b>Open the document</b> and keep it beside the form.",
               "Check every field against the document: patient, reporter, products, reactions, narrative. Under "
               "each part, PHAROS quotes the words it read, with the page. Correct what is wrong; press <b>Save</b>.",
               "Under <b>A valid case</b>, each criterion says <b>Present</b> or <b>Missing</b>.",
               "Set <b>Seriousness</b>: Serious (15 days) or Not serious (90 days). PHAROS only suggests it: you "
               "decide."], ML, y, colw)
yr = steps(c, ["Choose the product and its strength, or the ingredient. Press <b>Confirm the case</b>. It is "
               "refused while a criterion is missing, the seriousness is not decided or nothing is chosen.",
               "Until MedDRA arrives, press <b>Open the CIOMS I form</b>, save it as PDF and send it. With each "
               "reaction's MedDRA code, <b>Make the E2B file</b> instead.",
               "Once sent, give <b>Sent on</b> and <b>The authority's reference</b>, and press <b>Record as "
               "sent</b>."], ML + colw + 8 * mm, top, colw, start=5)
y = min(yl, yr) - 3 * mm
y = notes_row(c, [
    ("Not a case", "<b>Not a valid case</b>, with a comment, closes it. No case is ever deleted."),
    ("A follow-up", "On a confirmed or sent case, <b>Reopen</b> with a comment, and a <b>New day zero (a "
                    "follow-up)</b> if new information came. A confirmed case is corrected only after Reopen."),
    ("CIOMS I or E2B(R3)", "The CIOMS I form needs no MedDRA code. The E2B file needs every reaction's MedDRA "
                           "code; PHAROS never invents one. Until it passes the gateway test, it is a draft."),
    ("The history", "Every step, its time, the person and the comment, kept and never changed, with the "
                    "original document's SHA-256."),
], y, 4, gap=5 * mm)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 12 · REPORTS ═════════════════════════
new_page("Reports")
y = running_head(c, "06  ·  Reports")
y = head(c, "06", "Reports: the weekly report", y)
y = para(c, "Our record that we screened, week by week. It is made for the SOP and the pharmacovigilance system "
            "master file.", what_st, ML, y, CW) - 4 * mm
fw4 = (CW - 15 * mm) / 4
for i, (v, s) in enumerate([("Sunday 05:00", "Made by itself every Sunday at 05:00 Cairo time."),
                            ("Sun to Sat", "The week that has just ended, Cairo days."),
                            ("PDF and Excel", "The same six sections in both files."),
                            ("Never overwritten", "Kept in a locked archive with its fingerprint.")]):
    x = ML + i * (fw4 + 5 * mm)
    c.setFillColor(SURFACE2)
    c.rect(x, y - 17 * mm, fw4, 17 * mm, stroke=0, fill=1)
    c.setFillColor(BEACON)
    c.rect(x, y - 17 * mm, fw4, 0.8 * mm, stroke=0, fill=1)
    text(c, v, x + 3 * mm, y - 6.4 * mm, "Serif-B", 11)
    p, ph = ptext(s, ParagraphStyle("f4", parent=tiny, fontSize=7.4, leading=9.6), fw4 - 6 * mm)
    p.drawOn(c, x + 3 * mm, y - 8.6 * mm - ph)
y -= 17 * mm + 5 * mm

y = label(c, "The six sections", y)
y = table(c, [
    ("01", "Summary", "The week's figures; every decision taken in it, with its due day, its report to the authority "
                      "and its signal; and each ingredient: Ready, or Still preparing."),
    ("02", "Authorities read", "For each country, her 25 first: reads, reads that failed, new items. The label "
                               "watch, and each literature reference with how it was screened (page 13)."),
    ("03", "Our ingredients by country", "For each watched ingredient, each country's answer. Every notice with its "
                                         "link, the words matched and the decision. Its label changes, set against "
                                         "our label."),
    ("04", "Literature", "For each ingredient: possible case reports first, with their dates; its literature "
                         "references; each search with its counts; every paper, and whether EMA monitors it."),
    ("05", "Everything new, per authority", "Every item each authority published in the week, and who looked at "
                                            "the country, and when."),
    ("06", "To check by hand", "Her pages the app does not read in full, the sources whose reads failed (with the "
                               "last failure), and the sources not read that week."),
], y, [10 * mm, 48 * mm, CW - 58 * mm], header=["", "Section", "What it holds"],
    styles=[ParagraphStyle("sn", parent=cell_st, fontName="Serif-B", textColor=DEEP), cell_b, cell_st]) - 3 * mm
y = para(c, "The Excel file has the same, as sheets: Summary, Findings, Decisions, Authorities read, Ingredients by "
            "country, three Literature sheets, Everything new, To check by hand. A <b>daily report</b>, the same for "
            "one day, is made at 07:00 Cairo for the day before.", tiny, ML, y, CW) - 5.5 * mm

# the Reports page, drawn
dw = CW * 0.52
sxs = ML + dw + 7 * mm
sws = W - MR - sxs
fh = 73 * mm
frame(c, ML, y, dw, fh)
ix = ML + 4 * mm
iw = dw - 8 * mm
rtag = ML + dw - 2.4 * mm
yy = screen_sec(c, ix, y - 4 * mm, iw, "02", "Weekly reports")
text(c, "Sun 1 Nov – Sat 7 Nov 2026", ix, yy - 1 * mm, "Sans-B", 6.6)
text(c, "Made 8 Nov 2026 05:04", ix + iw - 27 * mm, yy - 1 * mm, "Mono", 5.2, MUTED)
yy -= 3.6 * mm
for f, h_ in [("PDF", "9f86d081…b0f00a08"), ("Excel", "2c26b46b…e7425e73")]:
    lbutton(c, ix, yy, f, size=5.6, h=4.4 * mm)
    micro(c, "SHA-256", ix + 13 * mm, yy - 2.9 * mm, size=4.6, spacing=0.5)
    text(c, h_, ix + 23 * mm, yy - 3 * mm, "Mono", 5.6)
    lbutton(c, ix + 49 * mm, yy, "Copy", size=5.4, h=4.4 * mm)
    yy -= 5.6 * mm
tag(c, rtag, yy + 8.4 * mm, "A")
yy -= 1.4 * mm
micro(c, "Signatures", ix, yy, size=5, spacing=0.6, color=INK)
yy -= 4.2 * mm
w_ = text(c, "Sama Mosaad", ix, yy, "Sans-B", 6.2)
text(c, "Administrator  ·  Approved  ·  8 Nov 2026 10:20", ix + w_ + 2 * mm, yy, "Sans", 5.6, MUTED)
yy -= 3.6 * mm
dot(c, ix, yy - 0.3 * mm, SEA)
text(c, "Fingerprint matches", ix + 3.2 * mm, yy, "Sans-B", 5.8, SEA)
tag(c, rtag, yy + 2 * mm, "B")
yy -= 2.4 * mm
lbutton(c, ix, yy, "Sign this report", size=5.6, h=4.4 * mm)
yy -= 6.8 * mm
p5 = c.beginPath()
p5.moveTo(ix, yy + 2.2 * mm)
p5.lineTo(ix + 1.6 * mm, yy + 1.2 * mm)
p5.lineTo(ix, yy + 0.2 * mm)
p5.close()
c.setFillColor(INK)
c.drawPath(p5, stroke=0, fill=1)
text(c, "Monthly reports (until November 2026)", ix + 3 * mm, yy + 0.4 * mm, "Sans-B", 6.2)
tag(c, rtag, yy + 1.2 * mm, "C")
yy -= 4 * mm
yy = screen_sec(c, ix, yy, iw, "03", "Packs")
text(c, "PSUR pack, levofloxacin, 1 Nov 2025 – 31 Oct 2026", ix, yy - 1 * mm, "Sans-B", 6.2)
text(c, "Made", ix + iw - 5 * mm - pdfmetrics.stringWidth("Made", "Sans-B", 5.8), yy - 1 * mm, "Sans-B", 5.8, SEA)
tag(c, rtag, yy - 0.2 * mm, "D")
yy -= 5 * mm
yy = screen_sec(c, ix, yy, iw, "04", "Screening log")
micro(c, "Week", ix, yy - 1 * mm, size=5, spacing=0.6)
c.setStrokeColor(RULE)
c.setFillColor(WHITE)
c.rect(ix, yy - 7.4 * mm, 44 * mm, 5 * mm, stroke=1, fill=1)
text(c, "Sun 1 Nov – Sat 7 Nov 2026", ix + 2 * mm, yy - 5.6 * mm, "Sans", 6)
tag(c, rtag, yy - 5 * mm, "E")
label(c, "How to file the weekly report", y, sxs)
steps(c, ["Open <b>Reports</b>. Under <b>02 Weekly reports</b> the newest week is first.",
          "Press <b>PDF</b>, then <b>Excel</b>, and file both with the screening records. <b>Copy</b> gives "
          "each file's SHA-256 to keep with it. Administrators also receive the PDF on Telegram on Sunday.",
          "Press <b>Sign this report</b>: Reviewed or Approved, with your password (page 19).",
          "Work through section 06, <b>To check by hand</b>: open each page it lists and look at it.",
          "For any other week, choose it under <b>Screening log</b>: every check of every source, Sunday to "
          "Saturday, including checks that found nothing."], sxs, y - 12, sws)
y -= fh + 3.5 * mm
y = legend(c, [("A", "The files", "With their SHA-256."),
               ("B", "Signatures", "Do they still match?"),
               ("C", "Monthly", "Before Nov 2026."),
               ("D", "Packs", "Page 20."),
               ("E", "Screening log", "Pick any week.")], y, 5) - 5 * mm
y = notes_row(c, [
    ("Kept for inspection", "Each file is kept in a locked archive with its SHA-256 fingerprint, the version of "
                            "PHAROS that made it and the run that made it."),
    ("Made again, never replaced", "A week made again is stored beside the first as a new version. Nothing is "
                                   "overwritten; the Reports page offers the latest."),
    ("The five-day clock", "The report comes after the week. A finding due to the Egyptian Drug Authority is "
                           "followed by its clock on the Ingredients screen and the morning reminder (page 9)."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 13 · REPORTS: INSPECTION EVIDENCE ═════════════════════════
new_page("Reports")
y = running_head(c, "06  ·  Reports  ·  inspection evidence")
y = head(c, "", "Inspection evidence: fingerprints and signatures", y, sub="A drawing, not real data")
y = para(c, "What an inspector can be shown for any week: the two files, their fingerprints, who signed them and "
            "what for, and a record of changes that nobody can alter.", what_st, ML, y, CW) - 3 * mm
fh = 52 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
tagx = ML + CW - 4.6 * mm
lw2 = 76 * mm
yy = y - 6 * mm
text(c, "Sun 1 Nov – Sat 7 Nov 2026", ix, yy, "Sans-B", 6.8)
text(c, "Made 8 Nov 2026 05:04", ix + 46 * mm, yy, "Mono", 5.4, MUTED)
yy -= 3 * mm
for f, h_ in [("PDF", "9f86d081…b0f00a08"), ("Excel", "2c26b46b…e7425e73")]:
    lbutton(c, ix, yy, f, size=5.8, h=4.6 * mm)
    micro(c, "SHA-256", ix + 13 * mm, yy - 3 * mm, size=4.8, spacing=0.5)
    text(c, h_, ix + 24 * mm, yy - 3.1 * mm, "Mono", 6)
    lbutton(c, ix + 52 * mm, yy, "Copy", size=5.6, h=4.6 * mm)
    yy -= 6 * mm
tag(c, ix + lw2 - 4 * mm, yy + 9 * mm, "A")
yy -= 1 * mm
micro(c, "Signatures", ix, yy, size=5, spacing=0.6, color=INK)
yy -= 4.6 * mm
w_ = text(c, "Sama Mosaad", ix, yy, "Sans-B", 6.4)
text(c, "Administrator", ix + w_ + 2 * mm, yy, "Sans", 5.8, MUTED)
yy -= 3.6 * mm
text(c, "Approved  ·  8 Nov 2026 10:20", ix, yy, "Sans", 6)
tag(c, ix + lw2 - 4 * mm, yy + 2 * mm, "B")
yy -= 3.8 * mm
dot(c, ix, yy - 0.3 * mm, SEA)
w_ = text(c, "Fingerprint matches", ix + 3.2 * mm, yy, "Sans-B", 6, SEA)
text(c, "4e074085…a1b2c3d4", ix + 5 * mm + w_, yy, "Mono", 5.6, MUTED)
tag(c, ix + lw2 - 4 * mm, yy + 1 * mm, "C")
yy -= 3 * mm
lbutton(c, ix, yy, "Sign this report", size=6)
# the sign form, on the right
fx = ix + lw2 + 4 * mm
fw = ix + iw - fx
c.setStrokeColor(RULE)
c.setLineWidth(0.6)
c.line(fx - 4 * mm, y - 4 * mm, fx - 4 * mm, y - fh + 4 * mm)
yy = y - 6 * mm
text(c, "Sign Sun 1 Nov – Sat 7 Nov 2026", fx, yy, "Sans-B", 6.8)
yy -= 5 * mm
micro(c, "What your signature means", fx, yy, size=4.8, spacing=0.5)
yy -= 4.4 * mm
for k, st in enumerate(["I have reviewed this report.", "I approve this report."]):
    c.setStrokeColor(INK)
    c.setFillColor(INK if k == 1 else WHITE)
    c.circle(fx + 1.2 * mm, yy + 0.8 * mm, 1.1 * mm, stroke=1, fill=1)
    text(c, st, fx + 4 * mm, yy, "Sans", 6.2)
    yy -= 4.4 * mm
tag(c, tagx, yy + 6 * mm, "D")
yy -= 1 * mm
micro(c, "Your password", fx, yy, size=4.8, spacing=0.5)
c.setStrokeColor(RULE)
c.setFillColor(WHITE)
c.rect(fx, yy - 6.4 * mm, fw - 4 * mm, 4.8 * mm, stroke=1, fill=1)
text(c, "••••••••••", fx + 1.6 * mm, yy - 4.6 * mm, "Sans", 6.6)
yy -= 8.6 * mm
micro(c, "Comment (optional)", fx, yy, size=4.8, spacing=0.5)
c.setStrokeColor(RULE)
c.setFillColor(WHITE)
c.rect(fx, yy - 7.4 * mm, fw - 4 * mm, 5.8 * mm, stroke=1, fill=1)
yy -= 10 * mm
bw_ = lbutton(c, fx, yy, "Sign electronically", dark=True, size=6)
lbutton(c, fx + bw_ + 2 * mm, yy, "Cancel", size=6)
tag(c, tagx, yy - 2.4 * mm, "E")
y -= fh + 3.5 * mm
y = legend(c, [("A", "SHA-256", "Shortened; Copy gives all 64."),
               ("B", "Signatures", "Name, role, meaning, time."),
               ("C", "The check", "Still the files signed?"),
               ("D", "The meaning", "Reviewed, or Approved."),
               ("E", "Sign", "With your password.")], y, 5) - 6 * mm

top = y
y1 = label(c, "How to check a file against its fingerprint", y)
yl = steps(c, ["Press <b>Copy</b> beside the file's SHA-256.",
               "On the computer that holds the filed copy, run <b>certutil -hashfile &lt;file&gt; SHA256</b> "
               "(Windows) or <b>sha256sum &lt;file&gt;</b>.",
               "The same 64 characters mean the same file, byte for byte."], ML, y1, colw)
y2 = label(c, "How to sign a weekly report", top, ML + colw + 8 * mm)
yr = steps(c, ["Press <b>Sign this report</b>. Reviewers and administrators; an administrator is offered "
               "Approved first.",
               "Choose what your signature means, type your password, and add a comment if you wish.",
               "Press <b>Sign electronically</b>. Your name, role, the meaning, the time and the report's fingerprint "
               "are recorded. It cannot be undone."], ML + colw + 8 * mm, y2, colw)
y = min(yl, yr) - 3 * mm
y = label(c, "Under each signature", y)
y = table(c, [
    ("Fingerprint matches", "The report's files are the ones that were signed."),
    ("File changed since signing", "The week was made again: new files, new fingerprints. Sign it again; the old "
                                   "signature stays."),
], y, [52 * mm, CW - 52 * mm], styles=[cell_b, cell_st]) - 5 * mm
y = label(c, "Where each record is, when an inspector asks", y)
y = table(c, [
    ("One week's screening", "Reports, 02 Weekly reports: the PDF and the Excel file, their SHA-256 and signatures."),
    ("What was checked, and when", "Reports, 04 Screening log: every source, every run, and what it found."),
    ("One ingredient over its PSUR interval", "Reports, 03 Packs: a PSUR pack (page 20)."),
    ("Every decision and signature over a period", "Reports, 03 Packs: an inspection pack, administrators only "
                                                   "(page 20)."),
], y, [62 * mm, CW - 62 * mm], styles=[cell_b, cell_st]) - 5 * mm
y = notes_row(c, [
    ("Your password", "Signing asks for your password, and a sign-in with it in the last 5 minutes. If you sign in "
                      "by e-mail link, first set a password under <b>Me</b>, then Password."),
    ("Never changed", "A signature is never edited or deleted. The audit log of every change cannot be changed or "
                      "emptied by anyone, the database's owner included."),
    ("The archive check", "Every Sunday PHAROS re-reads a sample of the originals, the weekly reports and the packs, "
                          "checks each against its fingerprint, and tests that nothing can be overwritten."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 14 · REPORTS: PACKS ON REQUEST ═════════════════════════
new_page("Reports")
y = running_head(c, "06  ·  Reports  ·  packs on request")
y = head(c, "", "Packs on request: PSUR and inspection", y, sub="A drawing, not real data")
y = para(c, "A PSUR pack for one ingredient, or an inspection pack for the whole system: asked for on Reports, made "
            "within four hours, signed like a weekly report.", what_st, ML, y, CW) - 3 * mm
fh = 66 * mm
frame(c, ML, y, CW, fh)
ix = ML + 5 * mm
iw = CW - 18 * mm
tagx = ML + CW - 4.6 * mm
yy = screen_sec(c, ix, y - 4 * mm, iw, "03", "Packs")
fx_ = ix
for lab_, val, w0 in [("Pack", "PSUR pack: one ingredient", 44), ("Ingredient", "Levofloxacin", 32),
                      ("First day", "01/11/2025", 24), ("Last day", "31/10/2026", 24)]:
    micro(c, lab_, fx_, yy - 1 * mm, size=4.8, spacing=0.5)
    c.setStrokeColor(RULE)
    c.setFillColor(WHITE)
    c.rect(fx_, yy - 7.4 * mm, w0 * mm, 5 * mm, stroke=1, fill=1)
    text(c, val, fx_ + 1.6 * mm, yy - 5.6 * mm, "Mono" if "/" in val else "Sans", 6)
    fx_ += (w0 + 3) * mm
tag(c, tagx, yy - 4.6 * mm, "A")
yy -= 10.4 * mm
p, ph = ptext("The days start at the EURD interval of the ingredient, up to today. Change them if you need other "
              "days. The pack is made by the next collection run, within four hours, and you are told on Telegram. "
              "At most five years.", ParagraphStyle("ph", parent=tiny, fontSize=6.6, leading=8.8), iw - 6 * mm)
p.drawOn(c, ix, yy - ph)
yy -= ph + 2 * mm
lbutton(c, ix, yy, "Ask for the pack", dark=True, size=6)
tag(c, tagx, yy - 2.4 * mm, "B")
yy -= 8.4 * mm
for name, who, st, made in [
    ("PSUR pack, levofloxacin, 1 Nov 2025 – 31 Oct 2026", "Asked for by Sama Mosaad, 6 Nov 2026 09:12",
     "Made 6 Nov 2026 12:31", True),
    ("Inspection pack, 7 Nov 2025 – 6 Nov 2026", "Asked for by Sama Mosaad, 6 Nov 2026 09:20",
     "Waiting for the next collection run (within four hours)", False)]:
    rule(c, ix, yy + 1.6 * mm, ix + iw, RULE)
    text(c, name, ix, yy - 1.4 * mm, "Sans-B", 6.6)
    text(c, who, ix, yy - 4.6 * mm, "Sans", 5.6, MUTED)
    sw_ = pdfmetrics.stringWidth(st, "Sans-B", 5.8)
    text(c, st, ix + iw - 6 * mm - sw_, yy - 1.4 * mm, "Sans-B", 5.8, SEA if made else DEEP)
    yy -= 7.4 * mm
    if made:
        bx = ix
        for f in ["PDF", "Excel"]:
            bx += lbutton(c, bx, yy, f, size=5.6, h=4.4 * mm) + 1.6 * mm
            micro(c, "SHA-256", bx, yy - 2.9 * mm, size=4.6, spacing=0.5)
            bx += 10 * mm
            bx += text(c, "c3ab8ff1…7d0b6e2a" if f == "PDF" else "1f0e3dad…99a5f7a2", bx, yy - 3 * mm, "Mono",
                       5.6) + 2 * mm
            bx += lbutton(c, bx, yy, "Copy", size=5.4, h=4.4 * mm) + 5 * mm
        tag(c, tagx, yy - 2.2 * mm, "C")
        yy -= 7.6 * mm
        text(c, "Signatures:", ix, yy - 1 * mm, "Sans-B", 5.8)
        text(c, "Not signed yet.", ix + 14 * mm, yy - 1 * mm, "Sans", 5.8, MUTED)
        lbutton(c, ix + 34 * mm, yy + 2 * mm, "Sign this report", size=5.6, h=4.4 * mm)
        yy -= 6.4 * mm
    else:
        tag(c, tagx, yy + 6 * mm, "D")
y -= fh + 3.5 * mm
y = legend(c, [("A", "The pack", "Kind, ingredient, days."),
               ("B", "Ask", "Made within four hours."),
               ("C", "Made", "Files, SHA-256, signatures."),
               ("D", "Waiting", "Until the next run.")], y, 4) - 6 * mm

y = label(c, "How to ask for a pack", y)
top = y
yl = steps(c, ["Open <b>Reports</b>, then <b>Packs</b>. Choose the pack.",
               "<b>PSUR pack</b> (reviewers and administrators): choose the ingredient. Its days start at its EURD "
               "interval, up to today, or the last 12 months when it has none."], ML, y, colw)
yr = steps(c, ["<b>Inspection pack</b> (administrators only, and only they see it): the last 12 months. Change the days if needed: at "
               "most five years, the first day not in the future. Press <b>Ask for the pack</b>.",
               "When it is made, Telegram tells you and the administrators, with the PDF. Download both files and "
               "sign it as a weekly report."], ML + colw + 8 * mm, top, colw, start=3)
y = min(yl, yr) - 3 * mm
y = label(c, "What each pack holds", y)
y = table(c, [
    ("PSUR pack", "The EURD interval. §3 Regulatory actions: every notice naming the ingredient or its class, by "
                  "country, with its decision, its report to the authority and its signal, and each country's "
                  "answer. §4 Label changes, each against our label. §11 Literature: possible case reports first, "
                  "with their dates, and the searches. §15–16 Signals: stage, outcome and every step. The screening "
                  "annex. Findings that do not concern us are counted, and listed with their reason in the Excel "
                  "file."),
    ("Inspection pack", "Coverage: each page of hers and whether the app reads it. The screening log. Every "
                        "decision, and every signature (weekly reports, packs and signals) with whether what was "
                        "signed still matches. Every report to the authority, withdrawn ones too. Every weekly report "
                        "with both SHA-256. The archive checks. The audit log, counted per table. The people and "
                        "their roles."),
], y, [30 * mm, CW - 30 * mm], styles=[cell_b, cell_st]) - 5 * mm
y = notes_row(c, [
    ("Limits", "At most two packs waiting per person and five in all. The same pack asked for again while it waits "
               "is the same request. A test run never makes one."),
    ("If it takes long", "A pack not finished in one run goes on in the next. After three tries it shows <b>Not "
                         "made</b> with the reason: ask for it again."),
    ("Never overwritten", "Kept in the locked archive with the SHA-256 of each file. It is read from the same "
                          "records as the screens and the weekly reports."),
], y, 3)
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 15 · TELEGRAM, PEOPLE, ME, THE PHONE APP ═════════════════════════
new_page("Telegram, People, Me")
y = running_head(c, "07  Telegram  ·  08  People and Me  ·  The phone app")
y = head(c, "07", "Telegram: what PHAROS sends", y)
y = para(c, "Messages carry the authority's public notice only: never a comment, never a decision.",
         what_st, ML, y, CW) - 3 * mm
y = table(c, [
    ("Immediate message", "Ingredient notices, immediately",
     "A new notice that names one of our ingredients, as soon as it is found: the ingredient, the country and "
     "authority, the type, the title as published, and a link to it."),
    ("Class digest", "Class-wide notices, daily digest",
     "Notices that name only a drug class, together in one message once a day, after 09:00 Cairo. At its end, "
     "the <b>Possible case reports</b> found since the last one (page 7)."),
    ("New items", "New items on the authorities' pages, once a day",
     "Once a day, after 09:00 Cairo: how many items each country published since the last message, with a link "
     "to Sources. Nothing is sent on a day with nothing new."),
    ("Morning reminder", "Every reviewer and administrator",
     "After 07:00 Cairo: findings due to the Egyptian Drug Authority and signal steps, late or due within 2 days, "
     "each with a link. Nothing when nothing is due (page 9)."),
    ("For administrators", "Source health alerts",
     "A source that stopped working. On Sunday morning, the weekly report PDF. A pack made, or not made, also "
     "to whoever asked for it."),
], y, [31 * mm, 47 * mm, CW - 78 * mm], header=["Message", "Its name under What I receive", "What it carries"],
    styles=[cell_b, cell_st, cell_st]) - 3 * mm
y = para(c, "<b>Never on Telegram:</b> other papers, and anything found by a look into the past (History). "
            "While PHAROS is in dry run it writes every message down and sends none; <b>Me</b> shows which, under "
            "Real Telegram messages (administrators).", tiny, ML, y, CW) - 4 * mm
top = y
micro(c, "Connect Telegram", ML, y - 5, color=INK, size=6.6)
yl = steps(c, ["Open <b>Me</b>: your name at the top right. Press <b>Connect Telegram</b>.",
               "Open the link on the phone where you use Telegram and press <b>Start</b> in the chat. The link works "
               "once and for 24 hours.",
               "Under <b>What I receive</b>, choose your messages."], ML, y - 9, colw)
micro(c, "Install PHAROS on an Android phone", ML + colw + 8 * mm, y - 5, color=INK, size=6.6)
yr = steps(c, ["Open <b>pharos-satopharma.pages.dev</b> in Chrome and sign in.",
               "Open Chrome's menu (the three dots) and press <b>Add to Home screen</b> (on some phones "
               "<b>Install app</b>), then <b>Install</b>.",
               "PHAROS opens from its own icon, full screen, at Ingredients. The tabs sit at the foot of the "
               "screen, in reach of the thumb."], ML + colw + 8 * mm, y - 9, colw)
y = min(yl, yr) - 1 * mm
y = para(c, "On an iPhone: Safari, then Share, then <b>Add to Home Screen</b>. The phone app is the same website: it "
            "needs a connection, and every screen is always the latest one.", tiny, ML + colw + 8 * mm, y, colw)
y -= 8 * mm

y = head(c, "08", "People and Me", y)
top = y
colw2 = (CW - 9 * mm) / 2
x2 = ML + colw2 + 9 * mm
micro(c, "People (administrators): invite a person", ML, y - 5, color=INK, size=6.6)
yl = steps(c, ["Press <b>Invite a person</b>.",
               "Write the full name and work email. Choose the role.",
               "Press <b>Send the invitation</b>. They get an email to choose a password."], ML, y - 9, colw2)
yl = para(c, "In the table: change a <b>Role</b>, switch <b>Can sign in</b> off to stop someone at once, and choose "
             "their <b>Messages</b>. Nobody can sign in without an invitation.", tiny, ML, yl, colw2)
micro(c, "Me: your own account", x2, y - 5, color=INK, size=6.6)
yr = table(c, [
    ("Telegram", "Connect your chat, or another one."),
    ("What I receive", "Your Telegram messages."),
    ("Real Telegram messages", "Administrators: a test, dry run on or off."),
    ("Password", "Set or change it. Signing needs it."),
    ("This device", "Light or dark, and Sign out."),
], y - 9, [27 * mm, colw2 - 27 * mm], x0=x2, styles=[cell_b, cell_st], pad=1.2 * mm)
y = min(yl, yr) - 7 * mm
y = label(c, "The three roles", y)
y = notes_row(c, [
    ("Reader", "Sees every screen and every report."),
    ("Reviewer", "Also records decisions, reports to the authority and signal steps; signs reports; asks for PSUR "
                 "packs."),
    ("Administrator", "Also manages the watchlist, drug classes, sources and people, and asks for inspection packs. "
                      "Dr Sama Mosaad's role."),
], y, 3) - 3 * mm
check(PAGE, y)
c.showPage()

# ═════════════════════════ PAGE 16 · FOR THE SOP ═════════════════════════
new_page("For the SOP")
y = running_head(c, "09  ·  For the SOP and the master file")
y = head(c, "09", "For the SOP and the master file", y)
y = para(c, "What PHAROS covers, a routine to screen with it, and the record it keeps. Written to be lifted into "
            "the SOP and the pharmacovigilance system master file.", what_st, ML, y, CW) - 4 * mm

y = label(c, "Scope", y)
y = para(c, "PHAROS screens, for the active ingredients on its watchlist and their drug classes: the safety "
            "publications of the 25 reference regulatory authorities (their DHPC, safety-notification and "
            "drug-database pages) and of other authorities; the newsletters those authorities send to the "
            "pharmacovigilance mailbox; the product information (SPC) of products with those ingredients; and the "
            "literature in PubMed, PubMed Central and Europe PMC, with each Global and Local literature reference "
            "(those the app cannot search are checked by hand weekly). A page PHAROS cannot read is listed in the "
            "weekly report, to be checked by hand. It keeps the five-day clock and the signal steps of a finding "
            "that concerns us, and each individual case with its clock to the authority.", ink_tiny, ML, y,
         CW) - 4 * mm

y = label(c, "A routine to screen with PHAROS", y)
y = table(c, [
    ("Every working day", "<b>Sources</b>: on each card with new items, read them, open every page marked Not "
                          "read by the app, then press Mark as looked at. Read the day's Telegram messages and act "
                          "on the morning reminder."),
    ("Every week", "<b>Ingredients</b>: for each watched ingredient, open its screen for <b>Last week</b>. Record "
                   "a decision on every mention, label change and possible case report; check by hand every "
                   "country that says so. On <b>Sources</b>, record the hand check of each reference marked By hand."),
    ("Every Sunday", "<b>Reports</b>: download the weekly report, PDF and Excel; file both with their SHA-256; sign "
                     "it; work through section 06, To check by hand."),
    ("When a finding concerns us", "Record <b>Concerns us</b> with a comment. Report it to the Egyptian Drug "
                                   "Authority within five days and press <b>Sent to the authority</b>. Take its "
                                   "signal through its steps."),
    ("When an ingredient is added", "Check its names and class words, test them against the archive, press Confirm, "
                                    "give its Japan code, and wait for <b>Ready</b> on its row."),
    ("When a case arrives", "Open it on <b>Cases</b>; check it against the document and confirm it; send it within "
                            "15 days, 90 if not serious, and record it as sent."),
    ("For a PSUR or an inspection", "Ask for the pack on <b>Reports</b>; sign it once it is made."),
], y, [44 * mm, CW - 44 * mm], header=["When", "What to do"], styles=[cell_b, cell_st]) - 4 * mm

y = label(c, "The record PHAROS keeps", y)
y = notes_row(c, [
    ("Originals", "Every notice and its PDFs, as found, in a locked archive nobody can change. A sample is "
                  "re-checked every week."),
    ("Every read and look", "Every check of every source, worked or failed: the screening log. Who looked at each "
                            "country, and when."),
    ("Every decision", "Who, when, what and why, with each report to the authority and signal step; never "
                       "edited."),
    ("Every signature", "Who signed which file, meaning what, with its fingerprint. Nobody can change the audit "
                        "log."),
], y, 4, gap=5 * mm) - 4 * mm

y = label(c, "Deviations, audits and CAPA", y)
colw2 = (CW - 9 * mm) / 2
yl = para(c, "<b>A deviation (PV-SOP-021).</b> A hand check not recorded, a case past its clock, section 06 left "
             "undone, a finding reported after five days: the QPPV notifies QA on PV-FM-009; the root cause and CAPA "
             "go on PV-FM-010. PHAROS shows the gap; it keeps no CAPA record.", tiny, ML, y, colw2)
yr = para(c, "<b>An audit (PV-SOP-022).</b> Each observation gets a CAPA plan (PV-FM-011 to 013). The evidence: the "
             "weekly reports with their SHA-256 and signatures, the screening log, the inspection pack, the audit "
             "log. PV-SOP-024 sets out the quality system.", tiny, ML + colw2 + 9 * mm, y, colw2)
y = min(yl, yr) - 5 * mm

y = navy_band(c, y, "Remember", [
    "PHAROS finds and shows. A person decides.",
    "Nothing found counts only when every read worked. Otherwise, check by hand.",
    "A decision is never edited. You record a new one after it.",
    "A finding that concerns us reaches the Egyptian Drug Authority within five days.",
    "Every date and time, on screen and in the reports, is Cairo time.",
], gap=5.2 * mm, size=9.8)
y -= 6 * mm
centred(c, "PHAROS Handbook  ·  Edition 4  ·  November 2026  ·  Sato Pharma, Pharmacovigilance", "Serif-I", 8.6, y,
        MUTED)
y -= 2 * mm
check(PAGE, y)
c.save()
print("\n".join(report))
