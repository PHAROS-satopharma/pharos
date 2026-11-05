"""The PHAROS handbook for Dr Sama Mossad (administrator): four A4 pages, every page of the app, with how-to steps."""
import sys
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from kit import *

OUT = sys.argv[1]
TOTAL = 4
BOTTOM = 19 * mm
report = []
DANGER = HexColor("#A8322D")
MARK = HexColor("#F6DC9F")

tiny = ParagraphStyle("tiny", parent=body, fontSize=8, leading=11, textColor=MUTED)
step_st = ParagraphStyle("step", parent=body, fontSize=8.5, leading=11.8, textColor=INK)
what_st = ParagraphStyle("what", parent=body, fontName="Serif-I", fontSize=9.6, leading=13.4, textColor=SEA)


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
    for i, t in enumerate(items, start - 1):
        p, h = ptext(t, step_st, w - numw)
        c.setFillColor(DEEP)
        c.setFont("Serif-B", 10.5)
        c.drawString(x, y - 9.6, str(i + 1))
        p.drawOn(c, x + numw, y - h)
        y -= h + gap
    return y


def frame(c, x, y, w, h):
    c.setFillColor(WHITE)
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.rect(x, y - h, w, h, stroke=1, fill=1)


def button(c, x, y, text, dark=True, size=6.8):
    w = pdfmetrics.stringWidth(text, "Sans-B", size) + 6 * mm
    c.setFillColor(INK if dark else WHITE)
    c.setStrokeColor(INK)
    c.setLineWidth(0.6)
    c.rect(x - w, y - 5.6 * mm, w, 5.6 * mm, stroke=0 if dark else 1, fill=1)
    c.setFillColor(WHITE if dark else INK)
    c.setFont("Sans-B", size)
    c.drawString(x - w + 3 * mm, y - 3.8 * mm, text)
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


c = canvas.Canvas(OUT, pagesize=A4)
c.setTitle("The PHAROS Handbook")
c.setAuthor("Sato Pharma")
c.setSubject("How PHAROS, the safety notification monitor of Sato Pharma, works and how to run it")
c.setCreator("Sato Pharma")
c.setKeywords("PHAROS, pharmacovigilance, safety notifications, handbook")
c._doc.info.producer = "Sato Pharma"

# ═════════════════════════ PAGE 1 · COVER, NAME, ENGINE ═════════════════════════
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

lw = 88 * mm
lh = lw * 983 / 1520
c.drawImage(BRAND + "pharos-logo-stacked.png", W / 2 - lw / 2, H - 25 * mm - lh, width=lw, height=lw * 1024 / 1536,
            mask="auto")
y = H - 25 * mm - lh - 8 * mm
centred(c, "The PHAROS Handbook", "Serif-B", 30, y - 22)
y -= 33
centred(c, "Every page, and how to run it", "Serif-I", 12, y - 10, MUTED)
y -= 19
c.setFillColor(BEACON)
c.rect(W / 2 - 9 * mm, y - 1, 18 * mm, 1.1 * mm, stroke=0, fill=1)
y -= 10 * mm
centred(c, "Prepared for", "Serif-I", 9.5, y, MUTED)
centred(c, "Dr Sama Mossad", "Script", 30, y - 13 * mm)
centred(c, "Administrator  ·  full control of PHAROS", "Sans", 8, y - 19.5 * mm, DEEP)
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
y = min(sy, fy) - 9 * mm

# the engine, in the navy band
eh = 50 * mm
c.setFillColor(INK)
c.rect(ML, y - eh, CW, eh, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(ML, y - 1.1 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
micro(c, "The engine  ·  it runs by itself, every 4 hours, day and night", ML + 6 * mm, y - 7.5 * mm,
      color=BEACON, size=6.6)
eng = [("Read", "25 regulators, our mailbox and medical literature."),
       ("Open", "Every new notice and its PDFs, in its own language."),
       ("Keep", "The original goes into a locked archive."),
       ("Find", "Our ingredients, by every name, in every language."),
       ("Show", "One row on Notifications, and a Telegram message.")]
ew = (CW - 12 * mm) / 5
for i, (t, s) in enumerate(eng):
    x = ML + 6 * mm + i * ew
    if i:
        c.setStrokeColor(HexColor("#23446F"))
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
check(1, y)
c.showPage()

# ═════════════════════════ PAGE 2 · NOTIFICATIONS ═════════════════════════
page_furniture(c, 2, TOTAL, "Notifications")
y = running_head(c, "01  ·  Notifications")
y = head(c, "01", "Notifications: the home page", y, sub="A drawing, not real data")
y = para(c, "Every safety notice PHAROS found about our ingredients, one row each, newest first.",
         what_st, ML, y, CW) - 3 * mm

# home page drawing
fx, fw, fh = ML, CW, 58 * mm
frame(c, fx, y, fw, fh)
c.setFillColor(INK)
c.rect(fx, y - 0.9 * mm, fw, 0.9 * mm, stroke=0, fill=1)
x = fx + 5 * mm
for i, n in enumerate(["Notifications", "Ingredients", "Sources", "Reports", "People", "My account"]):
    f = "Sans-B" if i == 0 else "Sans"
    c.setFillColor(INK if i == 0 else MUTED)
    c.setFont(f, 7.2)
    c.drawString(x, y - 6 * mm, n)
    w_ = pdfmetrics.stringWidth(n, f, 7.2)
    if i == 0:
        c.setFillColor(BEACON)
        c.rect(x, y - 8.6 * mm, w_, 0.8 * mm, stroke=0, fill=1)
    x += w_ + 7 * mm
button(c, fx + fw - 4 * mm, y - 2 * mm, "Export to Excel", dark=False, size=6.2)
rule(c, fx, y - 8.6 * mm, fx + fw, RULE)
ix = fx + 5 * mm
iw = fw - 18 * mm
yy = y - 12 * mm
tw = (iw - 9 * mm) / 4
for i, (lab, n) in enumerate([("New", "3"), ("Reviewed", "1"), ("Relevant", "1"), ("Not relevant", "2")]):
    tx = ix + i * (tw + 3 * mm)
    c.setFillColor(SURFACE2)
    c.rect(tx, yy - 9.5 * mm, tw, 9.5 * mm, stroke=0, fill=1)
    if i == 0:
        c.setFillColor(BEACON)
        c.rect(tx, yy - 9.5 * mm, tw, 0.8 * mm, stroke=0, fill=1)
    micro(c, lab, tx + 3 * mm, yy - 3.6 * mm, size=5.4, spacing=0.8)
    c.setFillColor(INK)
    c.setFont("Serif", 12.5)
    c.drawString(tx + 3 * mm, yy - 8 * mm, n)
tag(c, ix + iw + 5 * mm, yy - 4.8 * mm, "A")
yy -= 12.5 * mm
xx = ix
for lab, wmm in [("Search titles", 42), ("Country", 22), ("Ingredient", 22), ("Status", 18), ("Type", 18)]:
    c.setStrokeColor(RULE)
    c.setFillColor(WHITE)
    c.rect(xx, yy - 5.2 * mm, wmm * mm, 5.2 * mm, stroke=1, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Sans", 6.3)
    c.drawString(xx + 2 * mm, yy - 3.5 * mm, lab)
    xx += wmm * mm + 2 * mm
c.setFont("Sans", 6.1)
for k, lab in enumerate(["Include history", "Include class-wide"]):
    bx2 = xx + 1 * mm + k * 0 * mm
    by2 = yy - 2.2 * mm - k * 3.2 * mm
    c.setStrokeColor(MUTED)
    c.rect(bx2, by2 - 0.4 * mm, 2.2 * mm, 2.2 * mm, stroke=1, fill=0)
    c.setFillColor(MUTED)
    c.drawString(bx2 + 3.2 * mm, by2, lab)
tag(c, ix + iw + 5 * mm, yy - 2.6 * mm, "B")
yy -= 9.5 * mm
for lab, off in [("Date", 0), ("Published by", 18), ("Ingredient", 44), ("Safety notification", 70), ("Status", 122)]:
    micro(c, lab, ix + off * mm, yy, size=5.2, spacing=0.7)
tag(c, ix + 122 * mm + 13 * mm, yy + 0.8 * mm, "D")
rule(c, ix, yy - 1.8 * mm, ix + iw, INK, 0.7)
ry = yy - 1.8 * mm
for d, ctry, reg, st, bar in [("5 Nov", "Germany", "BfArM", "New", 46), ("3 Nov", "Japan", "PMDA", "Relevant", 38),
                              ("28 Oct", "Spain", "AEMPS", "Not relevant", 42)]:
    ry -= 7 * mm
    c.setFillColor(INK)
    c.setFont("Sans", 6.8)
    c.drawString(ix, ry + 3 * mm, d)
    c.drawString(ix + 18 * mm, ry + 3 * mm, ctry)
    c.setFillColor(MUTED)
    c.setFont("Sans", 5.8)
    c.drawString(ix + 18 * mm, ry + 0.8 * mm, reg)
    c.setFillColor(SURFACE2)
    c.rect(ix + 44 * mm, ry + 1.7 * mm, 18 * mm, 3.3 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Sans", 6.2)
    c.drawString(ix + 45.2 * mm, ry + 2.6 * mm, "Lornoxicam")
    bars(c, ix + 70 * mm, ry + 2.9 * mm, bar * mm * 0.9)
    bars(c, ix + 70 * mm, ry + 0.6 * mm, 15 * mm)
    if st == "New":
        dot(c, ix + 122 * mm, ry + 2.3 * mm, BEACON)
    c.setFillColor(INK)
    c.setFont("Sans-B" if st == "New" else "Sans", 6.6)
    c.drawString(ix + 125 * mm, ry + 2.3 * mm, st)
    c.setStrokeColor(MUTED)
    c.setLineWidth(0.6)
    ax, ay = ix + iw - 2.5 * mm, ry + 2 * mm
    c.line(ax, ay, ax + 2 * mm, ay + 2 * mm)
    c.line(ax + 0.8 * mm, ay + 2 * mm, ax + 2 * mm, ay + 2 * mm)
    c.line(ax + 2 * mm, ay + 0.8 * mm, ax + 2 * mm, ay + 2 * mm)
    rule(c, ix, ry - 0.6 * mm, ix + iw, RULE)
tag(c, ix + iw + 5 * mm, yy - 10 * mm, "C")
y -= fh + 3.5 * mm
y = legend(c, [("A", "Counts", "Click a tile to see only those."),
               ("B", "Filters", "Old news and drug-group news stay hidden until you tick them."),
               ("C", "One row", "One safety news, even if ten countries published it."),
               ("D", "Status", "New until someone decides.")], y, 4) - 9 * mm

# one notice drawing
y = label(c, "Click a row: one notice, opened", y)
fh2 = 56 * mm
frame(c, ML, y, CW, fh2)
mx = ML + 5 * mm
mw = CW * 0.62
sx = mx + mw + 6 * mm
sw = ML + CW - 5 * mm - sx
yy = y - 4.5 * mm
micro(c, "DHPC letter  ·  First published 5 Nov", mx, yy - 2 * mm, size=5.4, spacing=0.7, color=DEEP)
c.setFillColor(INK)
c.rect(mx, yy - 7 * mm, mw * 0.78, 2.4 * mm, stroke=0, fill=1)
c.rect(mx, yy - 10.6 * mm, mw * 0.5, 2.4 * mm, stroke=0, fill=1)
yy -= 15 * mm


def sec(num, title, yy):
    micro(c, num + "  " + title, mx, yy, size=5.4, spacing=0.7, color=INK)
    rule(c, mx, yy - 1.5 * mm, mx + mw, RULE)
    return yy - 4.4 * mm


yy = sec("02", "Where the ingredient is named", yy)
for frac, hl in [(0.92, None), (0.85, (0.30, 0.17)), (0.6, (0.08, 0.17))]:
    bars(c, mx, yy, mw * frac)
    if hl:
        c.setFillColor(MARK)
        c.rect(mx + mw * hl[0] - 0.6 * mm, yy - 1 * mm, mw * hl[1] + 1.2 * mm, 3.6 * mm, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Sans-B", 6)
        c.drawString(mx + mw * hl[0], yy + 0.1 * mm, "lornoxicam")
    yy -= 3.9 * mm
tag(c, mx + mw * 0.47 + 6 * mm, yy + 9 * mm, "E")
yy -= 2 * mm
yy = sec("03", "The original document", yy)
pw, ph_ = 12.5 * mm, 15.5 * mm
for k in range(3):
    px = mx + k * (pw + 2.6 * mm)
    c.setFillColor(WHITE)
    c.setStrokeColor(RULE)
    c.rect(px, yy - ph_, pw, ph_, stroke=1, fill=1)
    c.setFillColor(SURFACE2)
    for j in range(5):
        c.rect(px + 1.8 * mm, yy - 3.4 * mm - j * 2.4 * mm, pw - 3.6 * mm - (j % 3) * 1.4 * mm, 0.9 * mm,
               stroke=0, fill=1)
c.setFillColor(INK)
c.setFont("Sans-B", 6.3)
c.drawString(mx + 3 * (pw + 2.6 * mm) + 2 * mm, yy - 8 * mm, "Download the original")
tag(c, mx + 3 * (pw + 2.6 * mm) + 30 * mm, yy - 7.3 * mm, "F")
c.setFillColor(SURFACE2)
c.rect(sx, y - fh2 + 4.5 * mm, sw, fh2 - 9 * mm, stroke=0, fill=1)
rule(c, sx, y - 4.5 * mm, sx + sw, INK, 0.8)
micro(c, "Decision", sx + 3 * mm, y - 9 * mm, size=5.6, spacing=0.8, color=INK)
oy = y - 12 * mm
for k, opt in enumerate(["Reviewed", "Relevant", "Not relevant"]):
    c.setFillColor(WHITE)
    c.setStrokeColor(INK if k == 1 else RULE)
    c.setLineWidth(0.8 if k == 1 else 0.6)
    c.rect(sx + 3 * mm, oy - 5 * mm, sw - 6 * mm, 5 * mm, stroke=1, fill=1)
    c.setFillColor(INK)
    c.setFont("Sans-B" if k == 1 else "Sans", 6.6)
    c.drawString(sx + 5.5 * mm, oy - 3.4 * mm, opt)
    oy -= 6.2 * mm
c.setFillColor(WHITE)
c.setStrokeColor(RULE)
c.setLineWidth(0.6)
c.rect(sx + 3 * mm, oy - 7.5 * mm, sw - 6 * mm, 7.5 * mm, stroke=1, fill=1)
c.setFillColor(MUTED)
c.setFont("Sans", 6)
c.drawString(sx + 5 * mm, oy - 3.4 * mm, "Comment")
oy -= 9.5 * mm
c.setFillColor(INK)
c.rect(sx + 3 * mm, oy - 5.2 * mm, sw - 6 * mm, 5.2 * mm, stroke=0, fill=1)
c.setFillColor(WHITE)
c.setFont("Sans-B", 6.6)
c.drawString(sx + 5.5 * mm, oy - 3.5 * mm, "Record: Relevant")
tag(c, sx + sw - 1.5 * mm, y - 8.5 * mm, "G")
y -= fh2 + 3.5 * mm
y = legend(c, [("E", "Highlighted words", "Exactly where our ingredient is named."),
               ("F", "The original", "The real PDF, kept in the locked archive."),
               ("G", "Decision", "Saved with your name and the time.")], y, 3) - 9 * mm

# how to review
y = label(c, "How to review a notice", y)
colw = (CW - 8 * mm) / 2
top = y
yl = steps(c, ["Click the <b>New</b> tile, then open the first row.",
               "Read the highlighted words. Is it really our ingredient?",
               "Read the original PDF under it."], ML, y, colw)
yr = steps(c, ["Choose <b>Reviewed</b>, <b>Relevant</b> or <b>Not relevant</b> and press <b>Record</b>. "
               "For Not relevant, a reason is required.",
               "A decision is never edited. To change it, record a new one."], ML + colw + 8 * mm, top, colw, start=4)
y = min(yl, yr) - 6 * mm
y = label(c, "The four statuses", y)
cw4s = (CW - 21 * mm) / 4
for i, (t, s) in enumerate([("New", "Nobody has decided yet."), ("Reviewed", "Read. Decision to come."),
                            ("Relevant", "It concerns our products."), ("Not relevant", "It does not. Say why.")]):
    x = ML + i * (cw4s + 7 * mm)
    c.setFillColor(WHITE)
    c.setStrokeColor(INK if i == 0 else RULE)
    c.setLineWidth(0.8 if i == 0 else 0.6)
    c.rect(x, y - 8 * mm, cw4s, 8 * mm, stroke=1, fill=1)
    if i == 0:
        dot(c, x + 3 * mm, y - 5 * mm, BEACON)
    c.setFillColor(INK)
    c.setFont("Sans-B", 9)
    c.drawString(x + (6.5 if i == 0 else 3.5) * mm, y - 5.3 * mm, t)
    p, ph = ptext(s, tiny, cw4s)
    p.drawOn(c, x, y - 9.6 * mm - ph)
    if i < 3:
        ax = x + cw4s + 1.5 * mm
        c.setStrokeColor(DEEP)
        c.setLineWidth(0.8)
        c.line(ax, y - 4 * mm, ax + 3.4 * mm, y - 4 * mm)
        c.setFillColor(DEEP)
        p2 = c.beginPath()
        p2.moveTo(ax + 4 * mm, y - 4 * mm)
        p2.lineTo(ax + 2.6 * mm, y - 3 * mm)
        p2.lineTo(ax + 2.6 * mm, y - 5 * mm)
        p2.close()
        c.drawPath(p2, stroke=0, fill=1)
y -= 9.6 * mm + 4 * mm
check(2, y)
c.showPage()

# ═════════════════════════ PAGE 3 · INGREDIENTS AND SOURCES ═════════════════════════
page_furniture(c, 3, TOTAL, "Ingredients and Sources")
y = running_head(c, "02  Ingredients  ·  03  Sources")
y = head(c, "02", "Ingredients: what PHAROS looks for", y, sub="A drawing, not real data")
y = para(c, "The watchlist. Each active ingredient, with every name it is searched under, in every language.",
         what_st, ML, y, CW) - 3 * mm
dw = CW * 0.54
sxs = ML + dw + 7 * mm
sws = W - MR - sxs
fh3 = 54 * mm
frame(c, ML, y, dw, fh3)
button(c, ML + dw - 4 * mm, y - 3.5 * mm, "Add ingredient", size=6.2)
ix = ML + 4 * mm
iw = dw - 8 * mm
yy = y - 13 * mm
for lab, off in [("Ingredient", 0), ("Names looked for", 30), ("Confirmed", 62), ("Watched", 82)]:
    micro(c, lab, ix + off * mm, yy, size=5.2, spacing=0.7)
rule(c, ix, yy - 1.8 * mm, ix + iw, INK, 0.7)
yy -= 7.5 * mm
c.setFillColor(INK)
c.setFont("Sans-B", 7.4)
c.drawString(ix, yy, "Lornoxicam")
c.setFillColor(MUTED)
c.setFont("Sans", 5.8)
c.drawString(ix, yy - 2.6 * mm, "M01AC05")
c.setFillColor(INK)
c.setFont("Sans", 6.6)
c.drawString(ix + 30 * mm, yy, "Names in 15 languages")
bars(c, ix + 62 * mm, yy, 14 * mm)
switch(c, ix + 82 * mm, yy - 0.4 * mm, on=True)
rule(c, ix, yy - 4.6 * mm, ix + iw, RULE)
yy -= 9 * mm
micro(c, "Click the name: every term", ix, yy, size=5.2, spacing=0.7, color=DEEP)
yy -= 4.6 * mm
for lang, term, kind in [("en", "lornoxicam", "name  ·  word start"), ("sv", "lornoxikam", "name  ·  word start"),
                         ("fi", "lornoksikaami", "name  ·  word start"), ("en", "Xefo", "brand  ·  whole word")]:
    c.setFillColor(MUTED)
    c.setFont("Mono", 6.2)
    c.drawString(ix, yy, lang)
    c.setFillColor(INK)
    c.setFont("Sans", 6.8)
    c.drawString(ix + 7 * mm, yy, term)
    c.setFillColor(MUTED)
    c.setFont("Sans", 6)
    c.drawString(ix + 32 * mm, yy, kind)
    yy -= 3.8 * mm
label(c, "How to add an active ingredient", y, sxs)
steps(c, ["Press <b>Add ingredient</b>.",
          "Type its name in any language or spelling.",
          "Pick the right one from the list. Check the ATC code. Press <b>Confirm</b>.",
          "Check the names PHAROS suggests for each language. Add or remove any. "
          "<b>Never when it is</b> keeps look-alike drugs out.",
          "Press <b>Test against archive</b>, then <b>Save</b>. The watch starts on the next round."],
      sxs, y - 12, sws)
y -= fh3 + 4 * mm
y = label(c, "What you see on the table", y)
y = para(c, "<b>Names looked for:</b> how many names, in how many languages.   <b>Confirmed:</b> who checked "
            "it, and when. Press <b>Confirm</b> if nobody has.   <b>Watched:</b> switch it off to pause an "
            "ingredient without losing it.", ParagraphStyle("cn", parent=tiny, textColor=INK, fontSize=8.2,
                                                          leading=11.6), ML, y, CW) - 10 * mm

y = head(c, "03", "Sources: where PHAROS reads", y)
y = para(c, "Every regulator's safety page, grouped by country, with a light that says if it is working.",
         what_st, ML, y, CW) - 3 * mm
fh4 = 50 * mm
frame(c, ML, y, dw, fh4)
button(c, ML + dw - 4 * mm, y - 3.5 * mm, "Add a source", size=6.2)
ix = ML + 4 * mm
yy = y - 13 * mm
for lab, off in [("Source", 0), ("Health", 34), ("Activity", 62), ("Read", 84)]:
    micro(c, lab, ix + off * mm, yy, size=5.2, spacing=0.7)
rule(c, ix, yy - 1.8 * mm, ix + iw, INK, 0.7)
yy -= 6.5 * mm
c.setFillColor(INK)
c.setFont("Sans-B", 7)
c.drawString(ix, yy, "Germany")
c.setFillColor(MUTED)
c.setFont("Sans", 5.8)
c.drawString(ix + 13 * mm, yy, "2 sources")
yy -= 5 * mm
for reg, kind, hl, col, act, on in [("BfArM", "Safety notices · news feed", "Working", SEA, "Checked 2 h ago", True),
                                     ("BfArM", "Safety notices · web page", "Needs a look", BEACON, "Checked 2 h ago", True),
                                     ("A source you switched off", "", "Working", SEA, "Not read", False)]:
    c.setFillColor(INK)
    c.setFont("Sans", 6.8)
    c.drawString(ix, yy, reg)
    c.setFillColor(MUTED)
    c.setFont("Sans", 5.8)
    c.drawString(ix, yy - 2.6 * mm, kind)
    dot(c, ix + 34 * mm, yy - 0.2 * mm, col)
    c.setFillColor(INK)
    c.setFont("Sans", 6.4)
    c.drawString(ix + 37 * mm, yy, hl)
    c.setFillColor(MUTED)
    c.setFont("Sans", 6)
    c.drawString(ix + 62 * mm, yy, act)
    switch(c, ix + 84 * mm, yy - 0.4 * mm, on=on)
    rule(c, ix, yy - 4.4 * mm, ix + iw, RULE)
    yy -= 8.2 * mm
label(c, "How to add a source", y, sxs)
steps(c, ["Press <b>Add a source</b>.",
          "Paste the link of the regulator's safety page or news feed.",
          "Press <b>Test this link</b>. PHAROS reads it and shows the notices it found.",
          "Choose the regulator, <b>What it publishes</b>, <b>How often to read it</b> and the languages.",
          "Press <b>Save this source</b>. It can be saved only if the test found notices."],
      sxs, y - 12, sws)
y -= fh4 + 4 * mm
y = label(c, "What you see on the table", y)
y = para(c, "<b>Health:</b> the light below.   <b>Activity:</b> when it was last checked, and the date of its "
            "newest notice.   <b>Last 48 hours:</b> runs, items seen, new, matched.   <b>Read:</b> on or off.",
         ParagraphStyle("cn2", parent=tiny, textColor=INK, fontSize=8.2, leading=11.6), ML, y, CW) - 5 * mm
y = label(c, "The health lights", y)
hx = ML
for name, col, hollow in [("Working", SEA, False), ("Needs a look", BEACON, False), ("Not reachable", DANGER, False),
                          ("Blocks automated reading", MUTED, False), ("Not checked yet", None, True)]:
    dot(c, hx, y - 2.6 * mm, col, hollow)
    c.setFillColor(INK)
    c.setFont("Sans", 7.6)
    c.drawString(hx + 3.4 * mm, y - 2.5 * mm, name)
    hx += pdfmetrics.stringWidth(name, "Sans", 7.6) + 10 * mm
y -= 6 * mm
y = para(c, "Switch <b>Read</b> off to stop reading a source. If a source is not working, PHAROS has already "
            "messaged the administrators.", tiny, ML, y, CW) - 9 * mm
y = label(c, "Good to know", y)
cw3g = (CW - 12 * mm) / 3
hmax = 0
for i, (t, s) in enumerate([("A new ingredient", "PHAROS looks for it from the next round. Its product leaflets are "
                                                 "watched within a day."),
                            ("A new source", "Its first read is quiet: what it finds is saved, but no message "
                                             "goes out for old news."),
                            ("A site that blocks reading", "PHAROS never forces its way in. Such regulators are "
                                                           "read from their email newsletters instead.")]):
    x = ML + i * (cw3g + 6 * mm)
    rule(c, x, y, x + cw3g, INK, 0.8)
    c.setFillColor(INK)
    c.setFont("Sans-B", 8.6)
    c.drawString(x, y - 5 * mm, t)
    p, ph = ptext(s, tiny, cw3g)
    p.drawOn(c, x, y - 6.6 * mm - ph)
    hmax = max(hmax, 6.6 * mm + ph)
y -= hmax
check(3, y)
c.showPage()

# ═════════════════════════ PAGE 4 · REPORTS, PEOPLE, MY ACCOUNT ═════════════════════════
page_furniture(c, 4, TOTAL, "Reports, People, My account")
y = running_head(c, "04  Reports  ·  05  People  ·  My account")
colw = (CW - 9 * mm) / 2
x2 = ML + colw + 9 * mm


def half_head(c, num, title, x, y, w):
    c.setFillColor(DEEP)
    c.setFont("Serif", 16)
    c.drawString(x, y - 13, num)
    c.setFillColor(INK)
    c.setFont("Serif-B", 12.5)
    c.drawString(x + 9.5 * mm, y - 12.5, title)
    rule(c, x, y - 18, x + w, INK, 0.8)
    return y - 24


top = y
yl = half_head(c, "04", "Reports", ML, y, colw)
yl = para(c, "Our proof that we looked, month by month.", what_st, ML, yl, colw) - 3 * mm
for t, s in [("Monthly reports", "An Excel file and a PDF for every month, made by itself on the 1st at "
                                 "05:00 for the month before. Download and file them."),
             ("Screening log", "Pick a month. See every source: checks, failures, items read, new and "
                               "matched."),
             ("Tip", "On Notifications, <b>Export to Excel</b> saves the table as you filtered it.")]:
    c.setFillColor(INK)
    c.setFont("Sans-B", 8.6)
    c.drawString(ML, yl - 3.2 * mm, t)
    yl = para(c, s, tiny, ML, yl - 4.6 * mm, colw) - 3 * mm

yr = half_head(c, "05", "People", x2, top, colw)
yr = para(c, "Who can sign in, what each person may do, and what messages they get.", what_st, x2, yr, colw) - 3 * mm
micro(c, "How to invite a person", x2, yr - 5, color=INK, size=6.6)
yr = steps(c, ["Press <b>Invite a person</b>.",
               "Write the full name and work email. Choose the role.",
               "Press <b>Send the invitation</b>. They get an email to choose a password."],
           x2, yr - 9, colw)
yr -= 1 * mm
yr = para(c, "In the table: change a <b>Role</b>, switch <b>Can sign in</b> off to stop someone at once, and "
             "choose their <b>Messages</b>.", tiny, x2, yr, colw)
y = min(yl, yr) - 12 * mm

# roles
y = label(c, "The three roles", y)
cw3 = (CW - 12 * mm) / 3
for i, (t, s) in enumerate([("Reader", "Sees everything."),
                            ("Reviewer", "Also records decisions and links or splits copies."),
                            ("Administrator", "Everything: ingredients, sources, people, Telegram. Dr Sama Mossad's role.")]):
    x = ML + i * (cw3 + 6 * mm)
    c.setFillColor(SURFACE2 if i == 2 else PAPER)
    c.rect(x, y - 20 * mm, cw3, 20 * mm, stroke=0, fill=1)
    rule(c, x, y, x + cw3, INK, 0.8)
    c.setFillColor(INK)
    c.setFont("Sans-B", 9.2)
    c.drawString(x + (3 if i == 2 else 0) * mm, y - 5.2 * mm, t)
    p, ph = ptext(s, tiny, cw3 - (6 if i == 2 else 0) * mm)
    p.drawOn(c, x + (3 if i == 2 else 0) * mm, y - 6.8 * mm - ph)
y -= 31 * mm

# my account
y = head(c, "", "My account", y)
top = y
micro(c, "Connect Telegram", ML, y - 5, color=INK, size=6.6)
yl = steps(c, ["Press <b>Connect Telegram</b>.",
               "Open the link on your phone and press <b>Start</b>. It works for 24 hours.",
               "Under <b>What I receive</b>, choose your messages."], ML, y - 9, colw)
micro(c, "Turn on real Telegram messages", x2, y - 5, color=INK, size=6.6)
yr = steps(c, ["Press <b>Send me a test message</b> and check your phone.",
               "Read <b>What would have gone</b>: the messages kept while in test mode.",
               "Tick the approval box, then press <b>Turn real messages on</b>. "
               "<b>Back to dry run</b> stops them again."], x2, y - 9, colw)
y = min(yl, yr) - 11 * mm

y = label(c, "The messages PHAROS sends", y)
cw4 = (CW - 18 * mm) / 4
hmax = 0
for i, (t, s) in enumerate([("Immediate message", "A new notice about one of our ingredients."),
                            ("Daily digest", "News that names only the drug group. About 10:00."),
                            ("Source health", "A source stopped working. Administrators."),
                            ("Monthly report", "The PDF on the 1st. Administrators.")]):
    x = ML + i * (cw4 + 6 * mm)
    rule(c, x, y, x + cw4, INK, 0.8)
    c.setFillColor(INK)
    c.setFont("Sans-B", 8.6)
    c.drawString(x, y - 5 * mm, t)
    p, ph = ptext(s, tiny, cw4)
    p.drawOn(c, x, y - 6.6 * mm - ph)
    hmax = max(hmax, 6.6 * mm + ph)
y -= hmax + 11 * mm

# remember band
band_gap = 6.4 * mm
rules_txt = ["A decision is never edited. You add a new one after it.",
             "Comments stay in PHAROS. They never go by Telegram.",
             "Every time on screen is Cairo time.",
             "PHAROS finds and shows. A person decides."]
band_h = 12 * mm + len(rules_txt) * band_gap
c.setFillColor(INK)
c.rect(ML, y - band_h, CW, band_h, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(ML, y - 1.1 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
micro(c, "Remember", ML + 7 * mm, y - 7 * mm, color=BEACON, size=6.8)
ry = y - 13.5 * mm
for i, t in enumerate(rules_txt):
    c.setFillColor(BEACON)
    c.setFont("Serif-B", 10)
    c.drawString(ML + 7 * mm, ry - 1, str(i + 1))
    c.setFillColor(WHITE)
    c.setFont("Serif", 10.5)
    c.drawString(ML + 14 * mm, ry - 1, t)
    ry -= band_gap
y -= band_h + 8 * mm
centred(c, "Prepared by hand for Dr Sama Mossad and the pharmacovigilance team of Sato Pharma.", "Serif-I", 9, y,
        MUTED)
y -= 2 * mm
check(4, y)
c.save()
print("\n".join(report))
