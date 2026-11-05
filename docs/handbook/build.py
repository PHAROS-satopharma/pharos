"""The PHAROS handbook for Dr Sama Mossad: four A4 pages, few words, mostly pictures."""
import sys
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import Paragraph
from kit import *

OUT = sys.argv[1]
TOTAL = 4
BOTTOM = 19 * mm
report = []

tiny = ParagraphStyle("tiny", parent=body, fontSize=8, leading=11, textColor=MUTED)
tiny_c = ParagraphStyle("tinyc", parent=tiny, alignment=TA_CENTER)


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


def label(c, text, y, x=ML):
    micro(c, text, x, y - 6, color=INK, size=6.8)
    return y - 12


def tag(c, cx, cy, letter):
    c.setFillColor(INK)
    c.circle(cx, cy, 2.3 * mm, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.setFont("Sans-B", 7.4)
    c.drawCentredString(cx, cy - 2.6, letter)


def station(c, x, y_top, w, h, num, title, sub, dark=False):
    """One box of the flow: flat fill, numeral, title, one short line."""
    c.setFillColor(INK if dark else WHITE)
    c.setStrokeColor(INK if dark else RULE)
    c.setLineWidth(0.6)
    c.rect(x, y_top - h, w, h, stroke=0 if dark else 1, fill=1)
    c.setFillColor(BEACON if dark else DEEP)
    c.setFont("Serif", 15)
    c.drawString(x + 4 * mm, y_top - 9.6 * mm, num)
    c.setFillColor(WHITE if dark else INK)
    c.setFont("Sans-B", 10)
    c.drawString(x + 13 * mm, y_top - 9.4 * mm, title)
    st = ParagraphStyle("s", parent=tiny, textColor=MAST_MUTED if dark else MUTED)
    p, ph = ptext(sub, st, w - 17 * mm)
    p.drawOn(c, x + 13 * mm, y_top - 11.4 * mm - ph)


def arrow_down(c, x, y1, y2):
    c.setStrokeColor(DEEP)
    c.setLineWidth(0.8)
    c.line(x, y1, x, y2 + 1.4 * mm)
    c.setFillColor(DEEP)
    p = c.beginPath()
    p.moveTo(x - 1.3 * mm, y2 + 1.6 * mm)
    p.lineTo(x + 1.3 * mm, y2 + 1.6 * mm)
    p.lineTo(x, y2)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


c = canvas.Canvas(OUT, pagesize=A4)
c.setTitle("The PHAROS Handbook")
c.setAuthor("Sato Pharma")
c.setSubject("How PHAROS, the safety notification monitor of Sato Pharma, works and how to use it")
c.setCreator("Sato Pharma")
c.setKeywords("PHAROS, pharmacovigilance, safety notifications, handbook")
c._doc.info.producer = "Sato Pharma"

# ═════════════════════════ PAGE 1 · COVER AND THE IDEA ═════════════════════════
page_furniture(c, 1, TOTAL, "The idea")
c.setStrokeColor(INK)
c.setLineWidth(0.7)
c.rect(5 * mm, 5 * mm, W - 10 * mm, H - 10 * mm, stroke=1, fill=0)
c.setStrokeColor(DEEP)
c.setLineWidth(0.3)
c.rect(6.4 * mm, 6.4 * mm, W - 12.8 * mm, H - 12.8 * mm, stroke=1, fill=0)
micro(c, "Sato Pharma  ·  Pharmacovigilance", ML, H - 16 * mm, color=INK)
micro(c, "Handbook  ·  Edition 1  ·  November 2026", W - MR, H - 16 * mm, align="right")
rule(c, ML, H - 19.5 * mm, W - MR, INK, 0.8)

lw = 90 * mm
lh = lw * 983 / 1520
c.drawImage(BRAND + "pharos-logo-stacked.png", W / 2 - lw / 2, H - 29 * mm - lh, width=lw, height=lw * 1024 / 1536,
            mask="auto")
y = H - 29 * mm - lh - 10 * mm
centred(c, "The PHAROS Handbook", "Serif-B", 30, y - 22)
y -= 33
centred(c, "How our safety watch works, and how to use it", "Serif-I", 12, y - 10, MUTED)
y -= 21
c.setFillColor(BEACON)
c.rect(W / 2 - 9 * mm, y - 1, 18 * mm, 1.1 * mm, stroke=0, fill=1)
y -= 12 * mm
centred(c, "Prepared for", "Serif-I", 9.5, y, MUTED)
centred(c, "Dr Sama Mossad", "Script", 30, y - 13 * mm)
y -= 26 * mm

# the idea in one sentence
bh = 38 * mm
c.setFillColor(INK)
c.rect(ML, y - bh, CW, bh, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(W / 2 - 9 * mm, y - 1.1 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
micro(c, "PHAROS in one sentence", W / 2 - 18 * mm, y - 7.5 * mm, color=BEACON, size=6.6)
q = ParagraphStyle("q", fontName="Serif", fontSize=13.2, leading=19, textColor=WHITE, alignment=TA_CENTER)
para(c, "It reads the world's medicine regulators for us, finds our ingredients, "
        "keeps the original, and lets a person decide.", q, ML + 16 * mm, y - 14 * mm, CW - 32 * mm)
y -= bh + 10 * mm

# where the name comes from
rule(c, ML, y, W - MR, INK, 0.8)
c.setFillColor(INK)
c.setFont("Serif-B", 15)
c.drawString(ML, y - 8.5 * mm, "Where the name PHAROS comes from")
micro(c, "Alexandria, Egypt", W - MR, y - 8 * mm, align="right")
y -= 16 * mm
lcw = 58 * mm
c.setFillColor(INK)
c.setFont("Serif", 38)
c.drawString(ML, y - 12 * mm, "Φάρος")
c.setFillColor(MUTED)
c.setFont("Serif-I", 9)
c.drawString(ML, y - 18 * mm, "Pharos, an island off Alexandria")
fy = y - 26 * mm
for v, lab in [("280 BC", "the lighthouse is built"), ("1,500+", "years it stood"), ("1 of 7", "ancient Wonders of the World")]:
    rule(c, ML, fy + 3.6 * mm, ML + lcw - 6 * mm, RULE)
    c.setFillColor(DEEP)
    c.setFont("Serif-B", 10)
    c.drawString(ML, fy - 1 * mm, v)
    c.setFillColor(MUTED)
    c.setFont("Sans", 7.4)
    c.drawString(ML + 17 * mm, fy - 1 * mm, lab)
    fy -= 7.4 * mm
c.setStrokeColor(RULE)
c.setLineWidth(0.6)
c.line(ML + lcw - 2 * mm, y, ML + lcw - 2 * mm, fy + 3 * mm)
sx_ = ML + lcw + 4 * mm
sw_ = W - MR - sx_
story = ParagraphStyle("story", parent=body, fontSize=9, leading=13.2)
sy = y
for t in [
    "Pharos was a small island off the coast of Alexandria. Around 280 BC a great lighthouse was built "
    "there. Its fire guided ships safely into the harbour, and it stood for more than 1,500 years.",
    "It was so famous that its name became the word for a lighthouse in many languages: "
    "<i>phare</i> in French, <i>faro</i> in Italian and Spanish.",
    "Our PHAROS does the same job. A lighthouse does not steer the ship. <b>It keeps the light on, so we "
    "never sail on in the dark.</b>",
]:
    sy = para(c, t, story, sx_, sy, sw_) - 2.6 * mm
sy = para(c, "The letters also spell its full name: <b>Ph</b>armaceutical <b>A</b>lerts &amp; <b>R</b>egulatory "
             "<b>O</b>bservation <b>S</b>ystem.", ParagraphStyle("acr", parent=story, textColor=MUTED, fontSize=8.4),
          sx_, sy, sw_)
y = min(sy, fy) - 2 * mm
check(1, y)
c.showPage()

# ═════════════════════════ PAGE 2 · THE ENGINE ═════════════════════════
page_furniture(c, 2, TOTAL, "The engine")
y = running_head(c, "01  ·  The engine")
y = section_head(c, "01", "The engine", y, sub="It runs by itself, day and night")

# three figures
figs = [("25", "regulators we read"), ("15", "languages, never translated"), ("6×", "rounds a day, every 4 hours")]
fw = CW / 3
for i, (v, lab) in enumerate(figs):
    x = ML + i * fw
    if i:
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(x, y - 1 * mm, x, y - 17 * mm)
    c.setFillColor(INK)
    c.setFont("Serif", 30)
    c.drawString(x + (5 * mm if i else 0), y - 11 * mm, v)
    c.setFillColor(MUTED)
    c.setFont("Sans", 8.4)
    c.drawString(x + (5 * mm if i else 0), y - 16.5 * mm, lab)
y -= 24 * mm
rule(c, ML, y, W - MR, RULE)
y -= 9 * mm

# the flow, top to bottom
y = label(c, "One round, step by step", y)
fx = ML
fwid = CW * 0.56
sh = 21.5 * mm
gap = 7 * mm
flow = [
    ("1", "Read", "Regulators' safety pages, their newsletters in our mailbox, and medical literature."),
    ("2", "Open", "Every new notice and its PDFs. Scanned pages are read too."),
    ("3", "Keep", "The original file goes into a locked archive. Nobody can change or delete it."),
    ("4", "Find", "Our ingredient's names, in that country's own language. Look-alike drugs are left out."),
    ("5", "Show and tell", "One row in your table, and a Telegram message to the right people."),
]
top = y
for i, (n, t, s) in enumerate(flow):
    last = i == len(flow) - 1
    station(c, fx, y, fwid, sh, n, t, s, dark=last)
    if not last:
        arrow_down(c, fx + 7.5 * mm, y - sh, y - sh - gap)
    y -= sh + gap
flow_bottom = y + gap

# right column: same news, many countries -> one row
rx = ML + fwid + 9 * mm
rw = W - MR - rx
ry = label(c, "Same news, one row", top, rx)
para(c, "When Europe publishes a safety letter, many countries publish it again. You see it once.",
     tiny, rx, ry, rw)
ry -= 14 * mm
boxes = [("EMA", "First published here"), ("Germany", "copy"), ("Spain", "copy"), ("Japan", "copy")]
bw, bh2 = rw, 8.5 * mm
for i, (name, note_) in enumerate(boxes):
    by = ry - i * (bh2 + 2.2 * mm)
    c.setFillColor(SURFACE2 if i else WHITE)
    c.setStrokeColor(INK if i == 0 else RULE)
    c.setLineWidth(0.8 if i == 0 else 0.6)
    c.rect(rx + (0 if i == 0 else 6 * mm), by - bh2, bw - (0 if i == 0 else 6 * mm), bh2, stroke=1, fill=1)
    c.setFillColor(INK)
    c.setFont("Sans-B" if i == 0 else "Sans", 8.4)
    c.drawString(rx + (3 if i == 0 else 9) * mm, by - 5.6 * mm, name)
    micro(c, note_, rx + bw - 3 * mm, by - 5.4 * mm, align="right", size=5.6, spacing=0.7,
          color=DEEP if i == 0 else MUTED)
    if i:
        c.setStrokeColor(DEEP)
        c.setLineWidth(0.7)
        c.line(rx + 3 * mm, by - bh2 / 2, rx + 6 * mm, by - bh2 / 2)
last_box = ry - 3 * (bh2 + 2.2 * mm) - bh2
c.setStrokeColor(DEEP)
c.setLineWidth(0.7)
c.line(rx + 3 * mm, ry - bh2, rx + 3 * mm, last_box + bh2 / 2)
arrow_down(c, rx + bw / 2, last_box - 1.5 * mm, last_box - 8 * mm)
ry = last_box - 9.5 * mm
c.setFillColor(INK)
c.rect(rx, ry - 10 * mm, bw, 10 * mm, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(rx + 3.5 * mm, ry - 5.8 * mm, 1.8 * mm, 1.8 * mm, stroke=0, fill=1)
c.setFillColor(WHITE)
c.setFont("Sans-B", 9)
c.drawString(rx + 7.5 * mm, ry - 6.3 * mm, "One row in your table")
ry -= 16 * mm

# label watch, small
ry = label(c, "Every Monday: the label watch", ry, rx)
ry = para(c, "PHAROS compares the official product leaflets with last week's copy. If a safety section "
             "changes, you see the old and new words side by side.", tiny, rx, ry, rw)

y = min(flow_bottom, ry) - 10 * mm
rule(c, ML, y, W - MR, RULE)
y -= 8 * mm
y = label(c, "Safety nets", y)
nets = [("Locked archive", "Every original is kept, and nobody can change or delete it."),
        ("A health light on each source", "Working, Needs a look, or Not reachable."),
        ("A watchdog", "If nothing is read for 6 hours, an administrator is told.")]
cw3 = (CW - 2 * 6 * mm) / 3
hmax = 0
for i, (t, s) in enumerate(nets):
    x = ML + i * (cw3 + 6 * mm)
    c.setFillColor(BEACON)
    c.rect(x, y - 3.2 * mm, 1.8 * mm, 1.8 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Sans-B", 9)
    c.drawString(x + 4 * mm, y - 3.3 * mm, t)
    p, ph = ptext(s, tiny, cw3 - 4 * mm)
    p.drawOn(c, x + 4 * mm, y - 5 * mm - ph)
    hmax = max(hmax, 5 * mm + ph)
y -= hmax + 2 * mm
check(2, y)
c.showPage()

# ═════════════════════════ PAGE 3 · WHAT YOU SEE ═════════════════════════
page_furniture(c, 3, TOTAL, "What you see")
y = running_head(c, "02  ·  What you see")
y = section_head(c, "02", "What you see", y, sub="pharos-satopharma.pages.dev")

# the home page, drawn
y = label(c, "The home page: Notifications", y)
fx, fw = ML, CW
fh = 66 * mm
c.setFillColor(WHITE)
c.setStrokeColor(RULE)
c.setLineWidth(0.6)
c.rect(fx, y - fh, fw, fh, stroke=1, fill=1)
c.setFillColor(INK)
c.rect(fx, y - 0.9 * mm, fw, 0.9 * mm, stroke=0, fill=1)
navs = ["Notifications", "Ingredients", "Sources", "Reports", "People", "My account"]
x = fx + 5 * mm
for i, n in enumerate(navs):
    f = "Sans-B" if i == 0 else "Sans"
    c.setFillColor(INK if i == 0 else MUTED)
    c.setFont(f, 7.4)
    c.drawString(x, y - 6.4 * mm, n)
    w_ = pdfmetrics.stringWidth(n, f, 7.4)
    if i == 0:
        c.setFillColor(BEACON)
        c.rect(x, y - 9.2 * mm, w_, 0.8 * mm, stroke=0, fill=1)
    x += w_ + 7 * mm
rule(c, fx, y - 9.2 * mm, fx + fw, RULE)
ix = fx + 5 * mm
iw = fw - 10 * mm - 8 * mm
yy = y - 14 * mm
tw = (iw - 3 * 3 * mm) / 4
for i, (lab, n) in enumerate([("New", "3"), ("Reviewed", "1"), ("Relevant", "1"), ("Not relevant", "2")]):
    tx = ix + i * (tw + 3 * mm)
    c.setFillColor(SURFACE2)
    c.rect(tx, yy - 11 * mm, tw, 11 * mm, stroke=0, fill=1)
    if i == 0:
        c.setFillColor(BEACON)
        c.rect(tx, yy - 11 * mm, tw, 0.8 * mm, stroke=0, fill=1)
    micro(c, lab, tx + 3 * mm, yy - 4 * mm, size=5.6, spacing=0.8)
    c.setFillColor(INK)
    c.setFont("Serif", 14)
    c.drawString(tx + 3 * mm, yy - 9.4 * mm, n)
tag(c, ix + iw + 5 * mm, yy - 5.5 * mm, "A")
yy -= 15 * mm
xx = ix
for lab, wmm in [("Search titles", 46), ("Country", 24), ("Ingredient", 24), ("Status", 20), ("Type", 20)]:
    c.setStrokeColor(RULE)
    c.setFillColor(WHITE)
    c.rect(xx, yy - 5.8 * mm, wmm * mm, 5.8 * mm, stroke=1, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Sans", 6.6)
    c.drawString(xx + 2 * mm, yy - 3.9 * mm, lab)
    xx += wmm * mm + 2 * mm
tag(c, ix + iw + 5 * mm, yy - 2.9 * mm, "B")
yy -= 11 * mm
cols = [("Date", 0), ("Published by", 20), ("Ingredient", 48), ("Safety notification", 76), ("Status", 128)]
for lab, off in cols:
    micro(c, lab, ix + off * mm, yy, size=5.4, spacing=0.7)
rule(c, ix, yy - 2 * mm, ix + iw, INK, 0.7)
rows = [("5 Nov", "Germany", "BfArM", "New", 46), ("3 Nov", "Japan", "PMDA", "Relevant", 38),
        ("28 Oct", "Spain", "AEMPS", "Not relevant", 42)]
ry = yy - 2 * mm
for d, ctry, reg, st, bar in rows:
    ry -= 7.6 * mm
    c.setFillColor(INK)
    c.setFont("Sans", 7)
    c.drawString(ix, ry + 3.2 * mm, d)
    c.drawString(ix + 20 * mm, ry + 3.2 * mm, ctry)
    c.setFillColor(MUTED)
    c.setFont("Sans", 6)
    c.drawString(ix + 20 * mm, ry + 0.8 * mm, reg)
    c.setFillColor(SURFACE2)
    c.rect(ix + 48 * mm, ry + 1.8 * mm, 19 * mm, 3.4 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Sans", 6.4)
    c.drawString(ix + 49.3 * mm, ry + 2.7 * mm, "Lornoxicam")
    c.setFillColor(RULE)
    c.rect(ix + 76 * mm, ry + 3 * mm, bar * mm * 0.9, 1.7 * mm, stroke=0, fill=1)
    c.rect(ix + 76 * mm, ry + 0.6 * mm, 16 * mm, 1.2 * mm, stroke=0, fill=1)
    if st == "New":
        c.setFillColor(BEACON)
        c.rect(ix + 128 * mm, ry + 2.4 * mm, 1.7 * mm, 1.7 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Sans-B" if st == "New" else "Sans", 6.8)
    c.drawString(ix + 130.8 * mm, ry + 2.4 * mm, st)
    c.setStrokeColor(MUTED)
    c.setLineWidth(0.6)
    ax, ay = ix + iw - 2.5 * mm, ry + 2 * mm
    c.line(ax, ay, ax + 2 * mm, ay + 2 * mm)
    c.line(ax + 0.8 * mm, ay + 2 * mm, ax + 2 * mm, ay + 2 * mm)
    c.line(ax + 2 * mm, ay + 0.8 * mm, ax + 2 * mm, ay + 2 * mm)
    rule(c, ix, ry - 0.6 * mm, ix + iw, RULE)
tag(c, ix + iw + 5 * mm, yy - 12 * mm, "C")
tag(c, ix + 128 * mm + 14 * mm, yy + 0.8 * mm, "D")
y -= fh + 5 * mm

legend = [("A", "Counts", "Click a tile to see only those."),
          ("B", "Filters", "Find what you need."),
          ("C", "One row", "One safety news. Click to open."),
          ("D", "Status", "New until someone decides.")]
lw4 = CW / 4
for i, (L, t, s) in enumerate(legend):
    x = ML + i * lw4
    tag(c, x + 2.3 * mm, y - 2.6 * mm, L)
    c.setFillColor(INK)
    c.setFont("Sans-B", 8.6)
    c.drawString(x + 7 * mm, y - 3.6 * mm, t)
    p, ph = ptext(s, tiny, lw4 - 9 * mm)
    p.drawOn(c, x + 7 * mm, y - 5 * mm - ph)
y -= 14 * mm


y -= 5 * mm
y = label(c, "One notice, opened", y)
fh2 = 69 * mm
c.setFillColor(WHITE)
c.setStrokeColor(RULE)
c.setLineWidth(0.6)
c.rect(ML, y - fh2, CW, fh2, stroke=1, fill=1)
mx = ML + 5 * mm
mw = CW * 0.62
sx = mx + mw + 6 * mm
sw = ML + CW - 5 * mm - sx
yy = y - 5 * mm
c.setFillColor(MUTED)
c.setFont("Sans", 6.4)
c.drawString(mx, yy - 2 * mm, "All notifications")
micro(c, "DHPC letter  ·  First published 5 Nov", mx, yy - 7 * mm, size=5.4, spacing=0.7, color=DEEP)
c.setFillColor(INK)
c.rect(mx, yy - 12 * mm, mw * 0.78, 2.6 * mm, stroke=0, fill=1)
c.rect(mx, yy - 16 * mm, mw * 0.5, 2.6 * mm, stroke=0, fill=1)
yy -= 21 * mm


def sec(num, title, yy):
    micro(c, num + "  " + title, mx, yy, size=5.6, spacing=0.7, color=INK)
    rule(c, mx, yy - 1.6 * mm, mx + mw, RULE)
    return yy - 4.6 * mm


yy = sec("02", "Where the ingredient is named", yy)
lines = [(0.92, None), (0.85, (0.30, 0.17)), (0.95, None), (0.6, (0.08, 0.17))]
for frac, hl in lines:
    c.setFillColor(RULE)
    c.rect(mx, yy, mw * frac, 1.5 * mm, stroke=0, fill=1)
    if hl:
        c.setFillColor(HexColor("#F6DC9F"))
        c.rect(mx + mw * hl[0] - 0.6 * mm, yy - 1 * mm, mw * hl[1] + 1.2 * mm, 3.6 * mm, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Sans-B", 6.2)
        c.drawString(mx + mw * hl[0], yy + 0.1 * mm, "lornoxicam")
    yy -= 4 * mm
tag(c, mx + mw * 0.47 + 6 * mm, yy + 13 * mm, "E")
yy -= 2.5 * mm
yy = sec("03", "The original document", yy)
pw, ph_ = 15 * mm, 19 * mm
for k in range(3):
    px = mx + k * (pw + 3 * mm)
    c.setFillColor(WHITE)
    c.setStrokeColor(RULE)
    c.rect(px, yy - ph_, pw, ph_, stroke=1, fill=1)
    c.setFillColor(SURFACE2)
    for j in range(6):
        c.rect(px + 2 * mm, yy - 4 * mm - j * 2.4 * mm, pw - 4 * mm - (j % 3) * 1.5 * mm, 1 * mm, stroke=0, fill=1)
c.setFillColor(INK)
c.setFont("Sans-B", 6.4)
c.drawString(mx + 3 * (pw + 3 * mm) + 2 * mm, yy - 9 * mm, "Download the original")
tag(c, mx + 3 * (pw + 3 * mm) + 2 * mm + 30 * mm, yy - 8.3 * mm, "F")
# side panel: decision
c.setFillColor(SURFACE2)
c.rect(sx, y - fh2 + 5 * mm, sw, fh2 - 10 * mm, stroke=0, fill=1)
rule(c, sx, y - 5 * mm, sx + sw, INK, 0.8)
micro(c, "Decision", sx + 3 * mm, y - 10 * mm, size=5.8, spacing=0.8, color=INK)
oy = y - 14 * mm
for k, opt in enumerate(["Reviewed", "Relevant", "Not relevant"]):
    c.setFillColor(WHITE)
    c.setStrokeColor(INK if k == 1 else RULE)
    c.setLineWidth(0.8 if k == 1 else 0.6)
    c.rect(sx + 3 * mm, oy - 5.4 * mm, sw - 6 * mm, 5.4 * mm, stroke=1, fill=1)
    c.setFillColor(INK)
    c.setFont("Sans-B" if k == 1 else "Sans", 6.8)
    c.drawString(sx + 5.5 * mm, oy - 3.7 * mm, opt)
    oy -= 6.8 * mm
c.setFillColor(WHITE)
c.setStrokeColor(RULE)
c.setLineWidth(0.6)
c.rect(sx + 3 * mm, oy - 9 * mm, sw - 6 * mm, 9 * mm, stroke=1, fill=1)
c.setFillColor(MUTED)
c.setFont("Sans", 6.2)
c.drawString(sx + 5 * mm, oy - 3.6 * mm, "Comment")
oy -= 11.5 * mm
c.setFillColor(INK)
c.rect(sx + 3 * mm, oy - 5.6 * mm, sw - 6 * mm, 5.6 * mm, stroke=0, fill=1)
c.setFillColor(WHITE)
c.setFont("Sans-B", 6.8)
c.drawString(sx + 5.5 * mm, oy - 3.8 * mm, "Record: Relevant")
tag(c, sx + sw - 1.5 * mm, y - 9 * mm, "G")
y -= fh2 + 5 * mm
legend2 = [("E", "Highlighted words", "Exactly where our ingredient is named."),
           ("F", "The original", "The real PDF, kept in the archive."),
           ("G", "Decision", "Your choice, with your name and the time.")]
lw3 = CW / 3
for i, (L, t, s) in enumerate(legend2):
    x = ML + i * lw3
    tag(c, x + 2.3 * mm, y - 2.6 * mm, L)
    c.setFillColor(INK)
    c.setFont("Sans-B", 8.6)
    c.drawString(x + 7 * mm, y - 3.6 * mm, t)
    p, ph = ptext(s, tiny, lw3 - 9 * mm)
    p.drawOn(c, x + 7 * mm, y - 5 * mm - ph)
y -= 19 * mm


# the other pages, one line each
y = label(c, "The other pages", y)
pages = [("Sign in", "Your work email and password. By invitation only."),
         ("Ingredients", "What we watch, and every name we look for."),
         ("Sources", "Every regulator, and whether it is working."),
         ("Reports", "The monthly PDF and Excel. Proof that we looked."),
         ("My account", "Connect Telegram. Choose your messages."),
         ("People", "Administrators only: invite people, set roles.")]
cw2 = (CW - 8 * mm) / 2
for r in range(0, len(pages), 2):
    rule(c, ML, y, W - MR, RULE)
    hmax = 0
    for k, (t, s) in enumerate(pages[r:r + 2]):
        x = ML + k * (cw2 + 8 * mm)
        c.setFillColor(INK)
        c.setFont("Sans-B", 9)
        c.drawString(x, y - 5 * mm, t)
        p, ph = ptext(s, tiny, cw2 - 30 * mm)
        p.drawOn(c, x + 28 * mm, y - 2.4 * mm - ph)
        hmax = max(hmax, ph + 2.4 * mm, 7 * mm)
    y -= hmax + 2.6 * mm
rule(c, ML, y, W - MR, RULE)
check(3, y)
c.showPage()

# ═════════════════════════ PAGE 4 · EVERY DAY ═════════════════════════
page_furniture(c, 4, TOTAL, "Every day")
y = running_head(c, "03  ·  Every day")
y = section_head(c, "03", "How to use it", y, sub="Five minutes a day")

y = label(c, "Once, on your first day", y)
first = [("Choose a password", "from the invitation email."),
         ("Connect Telegram", "in My account. Press Start on your phone."),
         ("Choose your messages", "in My account, under What I receive.")]
for i, (t, s) in enumerate(first):
    x = ML + i * (cw3 + 6 * mm)
    c.setFillColor(SURFACE2)
    c.rect(x, y - 17 * mm, cw3, 17 * mm, stroke=0, fill=1)
    c.setFillColor(DEEP)
    c.setFont("Serif", 15)
    c.drawString(x + 4 * mm, y - 8.4 * mm, str(i + 1))
    c.setFillColor(INK)
    c.setFont("Sans-B", 9)
    c.drawString(x + 11 * mm, y - 7.6 * mm, t)
    p, ph = ptext(s, tiny, cw3 - 15 * mm)
    p.drawOn(c, x + 11 * mm, y - 9.4 * mm - ph)
y -= 26 * mm

y = label(c, "Every working day", y)
daily = [("Open Notifications", "and click the New tile."),
         ("Open the first row", "and look at the highlighted words. Is it our ingredient?"),
         ("Read the original", "PDF, right there on the page."),
         ("Record your decision", "Reviewed, Relevant or Not relevant.")]
for i, (t, s) in enumerate(daily):
    c.setFillColor(DEEP)
    c.setFont("Serif", 20)
    c.drawString(ML, y - 8 * mm, str(i + 1))
    c.setFillColor(INK)
    c.setFont("Sans-B", 10.5)
    c.drawString(ML + 11 * mm, y - 7.4 * mm, t)
    tw_ = pdfmetrics.stringWidth(t, "Sans-B", 10.5)
    c.setFillColor(MUTED)
    c.setFont("Sans", 9.4)
    c.drawString(ML + 11 * mm + tw_ + 2.2 * mm, y - 7.4 * mm, s)
    rule(c, ML + 11 * mm, y - 11 * mm, W - MR, RULE)
    y -= 14 * mm
y -= 8 * mm

# the status path
y = label(c, "The four statuses", y)
chips = [("New", "Nobody has decided yet.", True),
         ("Reviewed", "Read. Decision to come.", False),
         ("Relevant", "It concerns our products.", False),
         ("Not relevant", "It does not. Write why.", False)]
cw4 = (CW - 3 * 7 * mm) / 4
for i, (t, s, first_) in enumerate(chips):
    x = ML + i * (cw4 + 7 * mm)
    c.setFillColor(WHITE)
    c.setStrokeColor(INK if first_ else RULE)
    c.setLineWidth(0.8 if first_ else 0.6)
    c.rect(x, y - 9 * mm, cw4, 9 * mm, stroke=1, fill=1)
    if first_:
        c.setFillColor(BEACON)
        c.rect(x + 3 * mm, y - 5.4 * mm, 1.8 * mm, 1.8 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Sans-B", 9.4)
    c.drawString(x + (6.5 if first_ else 3.5) * mm, y - 5.9 * mm, t)
    p, ph = ptext(s, tiny, cw4)
    p.drawOn(c, x, y - 11 * mm - ph)
    if i < 3:
        ax = x + cw4 + 1.5 * mm
        c.setStrokeColor(DEEP)
        c.setLineWidth(0.8)
        c.line(ax, y - 4.5 * mm, ax + 3.4 * mm, y - 4.5 * mm)
        c.setFillColor(DEEP)
        p2 = c.beginPath()
        p2.moveTo(ax + 4 * mm, y - 4.5 * mm)
        p2.lineTo(ax + 2.6 * mm, y - 3.5 * mm)
        p2.lineTo(ax + 2.6 * mm, y - 5.5 * mm)
        p2.close()
        c.drawPath(p2, stroke=0, fill=1)
y -= 24 * mm

y = label(c, "Once a week, once a month", y)
for i, (t, s) in enumerate([("Every week", "Look at Sources. Anything not Working? Tell an administrator."),
                            ("Every month", "Open Reports and file the monthly PDF.")]):
    x = ML + i * (CW / 2 + 3 * mm)
    rule(c, x, y, x + CW / 2 - 3 * mm, INK, 0.8)
    c.setFillColor(INK)
    c.setFont("Sans-B", 9.4)
    c.drawString(x, y - 5.4 * mm, t)
    p, ph = ptext(s, tiny, CW / 2 - 3 * mm)
    p.drawOn(c, x, y - 7.2 * mm - ph)
y -= 20 * mm

# who can do what, three small columns
y = label(c, "Who can do what", y)
roles = [("Reader", "Sees everything."),
         ("Reviewer", "Also records decisions."),
         ("Administrator", "Also manages ingredients, sources and people.")]
for i, (t, s) in enumerate(roles):
    x = ML + i * (cw3 + 6 * mm)
    rule(c, x, y, x + cw3, INK, 0.8)
    c.setFillColor(INK)
    c.setFont("Sans-B", 9.4)
    c.drawString(x, y - 5.4 * mm, t)
    p, ph = ptext(s, tiny, cw3)
    p.drawOn(c, x, y - 7.2 * mm - ph)
y -= 20 * mm

# remember band
band_gap = 6.2 * mm
rules_txt = ["A decision is never edited. You add a new one after it.",
             "Comments stay in PHAROS. They never go by Telegram.",
             "Every time on screen is Cairo time.",
             "PHAROS finds and shows. You decide."]
band_h = 14 * mm + len(rules_txt) * band_gap
c.setFillColor(INK)
c.rect(ML, y - band_h, CW, band_h, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(ML, y - 1.1 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
micro(c, "Remember", ML + 7 * mm, y - 7 * mm, color=BEACON, size=6.8)
ry = y - 15 * mm
for i, t in enumerate(rules_txt):
    c.setFillColor(BEACON)
    c.setFont("Serif-B", 10.5)
    c.drawString(ML + 7 * mm, ry - 1, str(i + 1))
    c.setFillColor(WHITE)
    c.setFont("Serif", 11)
    c.drawString(ML + 14 * mm, ry - 1, t)
    ry -= band_gap
y -= band_h
y -= 6 * mm
c.setFillColor(BEACON)
c.rect(W / 2 - 1 * mm, y - 1 * mm, 2 * mm, 2 * mm, stroke=0, fill=1)
y -= 6 * mm
centred(c, "Prepared by hand for Dr Sama Mossad and the pharmacovigilance team of Sato Pharma.", "Serif-I", 9.4, y, MUTED)
y -= 5 * mm
_ew = sum(pdfmetrics.stringWidth(ch, "Mono", 6.4) + 1.1 for ch in "EDITION 1  ·  NOVEMBER 2026") - 1.1
micro(c, "Edition 1  ·  November 2026", W / 2 - _ew / 2, y - 1 * mm)
y -= 2 * mm
check(4, y)
c.save()
print("\n".join(report))
