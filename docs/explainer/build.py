"""PHAROS in Simple Words: a four-page explainer for a new member of the pharmacovigilance team.

It uses the handbook's drawing kit (fonts, colours, page furniture), so it looks like the handbook.

    python build.py ["PHAROS in Simple Words.pdf"]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "handbook"))

from kit import (BEACON, BRAND, CW, DEEP, H, INK, MAST_MUTED, ML, MR, MUTED, PAPER, RULE, SEA, SURFACE2, W, WHITE, body,
                 micro, para, rule)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

OUT = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("PHAROS in Simple Words.pdf"))
TOTAL = 4
BOTTOM = 19 * mm
report = []

txt = ParagraphStyle("txt", parent=body, fontSize=9.4, leading=13.6)
txt_w = ParagraphStyle("txt_w", parent=txt, textColor=WHITE)
small = ParagraphStyle("small", parent=body, fontSize=8.4, leading=11.8)
small_m = ParagraphStyle("small_m", parent=small, textColor=MUTED)
what = ParagraphStyle("what", parent=body, fontName="Serif-I", fontSize=10.6, leading=15, textColor=SEA)
big = ParagraphStyle("big", parent=body, fontName="Serif", fontSize=15, leading=21, textColor=WHITE)

PAGE = 0
c = canvas.Canvas(OUT, pagesize=(W, H))
c.setTitle("PHAROS in Simple Words")
c.setAuthor("Sato Pharma")
c.setSubject("What PHAROS is, why the pharmacovigilance team uses it, and how it works, for a new team member")
c.setCreator("Sato Pharma")
c.setKeywords("PHAROS, pharmacovigilance, introduction, explainer, onboarding")
c._doc.info.producer = "Sato Pharma"


def new_page(label_):
    global PAGE
    PAGE += 1
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    rule(c, ML, 14 * mm, W - MR, RULE)
    micro(c, f"PHAROS in simple words  ·  {label_}", ML, 9.6 * mm)
    micro(c, f"Page {PAGE} of {TOTAL}", W - MR, 9.6 * mm, align="right")
    c.drawImage(BRAND + "sato-pharma.png", W / 2 - 9 * mm, 7.6 * mm, width=18 * mm, height=18 * mm * 116 / 307,
                mask="auto")


def running_head(title):
    c.drawImage(BRAND + "pharos-logo.png", ML, H - 19 * mm, width=33 * mm, height=33 * mm * 667 / 2000, mask="auto")
    micro(c, title, W - MR, H - 13.4 * mm, align="right", color=INK)
    rule(c, ML, H - 21.5 * mm, W - MR, INK, 0.8)
    c.setFillColor(BEACON)
    c.rect(ML, H - 22.6 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
    return H - 30 * mm


def check(y):
    report.append(f"page {PAGE}: {round((y - BOTTOM) / mm, 1)} mm spare")
    if y < BOTTOM:
        raise SystemExit(f"page {PAGE} overflows by {round((BOTTOM - y) / mm, 1)} mm")


def head(num, title, y, sub=None):
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


def label(text, y, x=ML, color=INK):
    micro(c, text, x, y - 6, color=color, size=6.8)
    return y - 12


def centred(text, font, size, y, color=INK):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawCentredString(W / 2, y, text)


def ph(text, style, width):
    p = Paragraph(text, style)
    return p, p.wrap(width, 2000)[1]


def rows(items, y, keyw=44 * mm, style=small, keyfont="Serif-B", keysize=9.6, gap=2.4 * mm):
    """A two-column list: a serif key on the left, plain words on the right, hairlines between."""
    for k, v in items:
        p, h = ph(v, style, CW - keyw)
        rule(c, ML, y, W - MR, RULE)
        c.setFillColor(INK)
        c.setFont(keyfont, keysize)
        c.drawString(ML, y - gap - 9, k)
        p.drawOn(c, ML + keyw, y - gap - h)
        y -= h + 2 * gap
    rule(c, ML, y, W - MR, RULE)
    return y


def numbered(items, x, y, w, numw=7 * mm, gap=2.6 * mm, style=small):
    for i, t in enumerate(items, 1):
        p, h = ph(t, style, w - numw)
        c.setFillColor(DEEP)
        c.setFont("Serif-B", 11)
        c.drawString(x, y - 9.6, str(i))
        p.drawOn(c, x + numw, y - h)
        y -= h + gap
    return y


def arrow(x1, y_, x2, color=DEEP):
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(0.8)
    c.line(x1, y_, x2 - 1.6 * mm, y_)
    p = c.beginPath()
    p.moveTo(x2, y_)
    p.lineTo(x2 - 2 * mm, y_ + 1.1 * mm)
    p.lineTo(x2 - 2 * mm, y_ - 1.1 * mm)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def down_arrow(x, y1, y2, color=DEEP):
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(0.8)
    c.line(x, y1, x, y2 + 1.6 * mm)
    p = c.beginPath()
    p.moveTo(x, y2)
    p.lineTo(x - 1.1 * mm, y2 + 2 * mm)
    p.lineTo(x + 1.1 * mm, y2 + 2 * mm)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def box(x, y_top, w, h, fill=WHITE, stroke=RULE):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.6)
    c.rect(x, y_top - h, w, h, stroke=1, fill=1)


# ═════════════════════════ PAGE 1 · COVER: WHAT IT IS AND WHY ═════════════════════════
new_page("What it is")
c.setStrokeColor(INK)
c.setLineWidth(0.7)
c.rect(5 * mm, 5 * mm, W - 10 * mm, H - 10 * mm, stroke=1, fill=0)
c.setStrokeColor(DEEP)
c.setLineWidth(0.3)
c.rect(6.4 * mm, 6.4 * mm, W - 12.8 * mm, H - 12.8 * mm, stroke=1, fill=0)
micro(c, "Sato Pharma  ·  Pharmacovigilance", ML, H - 16 * mm, color=INK)
micro(c, "For new team members  ·  November 2026", W - MR, H - 16 * mm, align="right")
rule(c, ML, H - 19.5 * mm, W - MR, INK, 0.8)

lw = 70 * mm
lh = lw * 1024 / 1536
c.drawImage(BRAND + "pharos-logo-stacked.png", W / 2 - lw / 2, H - 23 * mm - lh, width=lw, height=lh, mask="auto")
y = H - 23 * mm - lh - 4 * mm
centred("PHAROS in Simple Words", "Serif-B", 28, y - 20)
y -= 30
centred("What it is, why we use it, and how it works, in four pages", "Serif-I", 12, y - 10, MUTED)
y -= 19
c.setFillColor(BEACON)
c.rect(W / 2 - 9 * mm, y - 1, 18 * mm, 1.1 * mm, stroke=0, fill=1)
y -= 9 * mm

# the idea in one sentence: a navy band
p, h = ph("PHAROS is a <b>watchman</b> for our medicines. Every day it reads what the world’s drug authorities "
          "publish about medicine safety, and if any of them says something about one of <b>our</b> active "
          "ingredients, it shows it to us at once.", big, CW - 14 * mm)
band_h = h + 18 * mm
c.setFillColor(INK)
c.rect(ML, y - band_h, CW, band_h, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(ML, y - 1.1 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
micro(c, "The idea in one sentence", ML + 7 * mm, y - 7.5 * mm, color=BEACON, size=6.8)
p.drawOn(c, ML + 7 * mm, y - 11.5 * mm - h)
y -= band_h + 8 * mm

# where the name comes from
y = head("", "Why the name PHAROS?", y, sub="Alexandria, Egypt")
c.setFillColor(INK)
c.setFont("Serif", 30)
c.drawString(ML, y - 10 * mm, "Φάρος")
c.setFillColor(MUTED)
c.setFont("Serif-I", 8.4)
c.drawString(ML, y - 15 * mm, "the lighthouse of Alexandria")
p, h = ph("Pharos was the great lighthouse of Alexandria, one of the seven Wonders of the ancient world. "
          "A lighthouse does not steer the ship. <b>It keeps the light on, so the ship never sails in the dark.</b> "
          "PHAROS does the same for us: it does not decide anything, it makes sure we see.<br/>"
          "The letters also spell its full name: <b>Ph</b>armaceutical <b>A</b>lerts &amp; <b>R</b>egulatory "
          "<b>O</b>bservation <b>S</b>ystem.", txt, CW - 52 * mm)
p.drawOn(c, ML + 52 * mm, y - h)
c.setStrokeColor(RULE)
c.setLineWidth(0.6)
c.line(ML + 47 * mm, y, ML + 47 * mm, y - max(h, 17 * mm))
y -= max(h, 17 * mm) + 8 * mm

# why we need it: before and with
y = head("", "Why do we need it?", y, sub="The job it does for us")
y = para(c, "Pharmacovigilance means watching the safety of our medicines after they are on the market. Part of "
            "that job is to know <b>every</b> safety notice a drug authority publishes about our active ingredients, "
            "and to act on it in time.", txt, ML, y, CW) - 5 * mm
colw = (CW - 6 * mm) / 2
before = ["Open dozens of authority websites, one by one, every week.",
          "Read pages in many languages and hope nothing was missed.",
          "Copy findings into Excel by hand.",
          "Rebuild the proof for an inspector from memory and screenshots."]
withp = ["PHAROS opens all of them by itself, many times a day.",
         "It searches each one in its own language, by every name of the medicine.",
         "Every finding lands in one table, ready for review.",
         "Everything it read is kept, unchanged, as proof for the inspector."]
top = y
for i, (title, items, color) in enumerate([("Before: by hand", before, MUTED), ("Now: with PHAROS", withp, INK)]):
    x = ML + i * (colw + 6 * mm)
    c.setFillColor(color)
    c.setFont("Serif-B", 11.5)
    c.drawString(x, top - 10, title)
    rule(c, x, top - 15, x + colw, color, 0.8)
    yy = top - 21
    for t in items:
        p, h = ph(t, ParagraphStyle("b", parent=small, textColor=color), colw - 5 * mm)
        c.setFillColor(BEACON if i else RULE)
        c.rect(x, yy - 6.4, 1.6 * mm, 1.6 * mm, stroke=0, fill=1)
        p.drawOn(c, x + 5 * mm, yy - h)
        yy -= h + 2.4 * mm
    y = min(y, yy)
check(y)
c.showPage()

# ═════════════════════════ PAGE 2 · HOW IT WORKS ═════════════════════════
new_page("How it works")
y = running_head("How it works")
y = head("01", "How it works, in five steps", y, sub="It runs by itself, day and night")
y = para(c, "Think of PHAROS as a very fast, very patient colleague who never sleeps. This is everything it does, "
            "in order.", what, ML, y, CW) - 6 * mm

stepsx = [("1", "You tell it", "what to watch"), ("2", "It reads", "25 authorities"), ("3", "It searches",
          "for our medicines"), ("4", "It keeps", "a copy of everything"), ("5", "It shows you", "table + Telegram")]
gap = 5 * mm
bw = (CW - 4 * gap) / 5
bh = 22 * mm
for i, (n, t1, t2) in enumerate(stepsx):
    x = ML + i * (bw + gap)
    box(x, y, bw, bh, fill=INK if i == 4 else WHITE, stroke=INK)
    fg = WHITE if i == 4 else INK
    c.setFillColor(BEACON if i == 4 else DEEP)
    c.setFont("Serif", 16)
    c.drawString(x + 3 * mm, y - 8 * mm, n)
    c.setFillColor(fg)
    c.setFont("Serif-B", 10.4)
    c.drawString(x + 3 * mm, y - 14 * mm, t1)
    c.setFont("Sans", 7.6)
    c.setFillColor(MUTED if i < 4 else MAST_MUTED)
    c.drawString(x + 3 * mm, y - 18.4 * mm, t2)
    if i < 4:
        arrow(x + bw + 0.6 * mm, y - bh / 2, x + bw + gap - 0.6 * mm)
y -= bh + 7 * mm

explain = [
    ("1  You tell it", "A person adds the <b>active ingredients</b> we market, for example <i>lornoxicam</i> or "
                       "<i>levofloxacin</i>. This list is called the <b>watchlist</b>. PHAROS also learns the "
                       "ingredient’s other names and its drug class by itself."),
    ("2  It reads", "On a timetable it visits the safety pages, news, letters and PDFs of <b>25 reference "
                    "authorities</b> (for example the FDA in the USA, EMA in Europe, MHRA in the UK and the Egyptian "
                    "Drug Authority), plus our team mailbox and the medical literature (PubMed)."),
    ("3  It searches", "In everything it read, it looks for our ingredients by every name, <b>in the language of "
                       "that country</b>. Nothing is translated. When it finds one, that is a <b>finding</b>."),
    ("4  It keeps", "Every page and PDF is saved in a <b>locked archive</b>: nobody can change or delete it. So we can "
                    "always show an inspector exactly what the authority published, and when we saw it."),
    ("5  It shows you", "The findings appear in one simple table in the PHAROS app. Open any row for the details. "
                        "Team members who linked their Telegram also get a short message."),
]
y = rows(explain, y, keyw=36 * mm, style=small, keysize=9.8)
y -= 7 * mm

# the golden line
band_h = 18 * mm
c.setFillColor(SURFACE2)
c.rect(ML, y - band_h, CW, band_h, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(ML, y - band_h, 1.4 * mm, band_h, stroke=0, fill=1)
c.setFillColor(INK)
c.setFont("Serif-B", 15)
c.drawString(ML + 8 * mm, y - 8.4 * mm, "PHAROS reads. A person decides.")
c.setFillColor(MUTED)
c.setFont("Sans", 8.4)
c.drawString(ML + 8 * mm, y - 13.6 * mm, "It never judges a finding by itself. Every finding is read and decided by "
                                         "a member of the team.")
y -= band_h + 8 * mm

# two ways to look
y = head("02", "Two ways to look: by medicine and by country", y)
colw = (CW - 8 * mm) / 2
top = y
for i, (eyebrow, title, tab, words) in enumerate([
    ("Vertical", "One medicine, every country", "Ingredients tab",
     "Pick one ingredient and see everything said about it, in every country and in the literature, for the days "
     "you choose. The question it answers: <b>did anyone, anywhere, mention our medicine?</b>"),
    ("Horizontal", "One country, everything new", "Sources tab",
     "Pick one country and see everything it published since you last looked, even items that do not name our "
     "ingredients. It is the <b>safety net</b> for anything the first way might miss."),
]):
    x = ML + i * (colw + 8 * mm)
    # a tiny grid drawing: rows are countries, the band is the direction of the look
    gx, gy, gw, gh = x, top, 30 * mm, 24 * mm
    box(gx, gy, gw, gh)
    for r in range(1, 4):
        rule(c, gx, gy - r * gh / 4, gx + gw, RULE)
    for k in range(1, 4):
        c.setStrokeColor(RULE)
        c.line(gx + k * gw / 4, gy, gx + k * gw / 4, gy - gh)
    c.setFillColor(BEACON)
    if i == 0:
        c.rect(gx + gw / 4, gy - gh, gw / 4, gh, stroke=0, fill=1)
    else:
        c.rect(gx, gy - gh / 4, gw, gh / 4, stroke=0, fill=1)
    micro(c, "columns: medicines  ·  rows: countries", gx, gy - gh - 3.4 * mm, size=5.2, spacing=0.6)
    tx = x + gw + 5 * mm
    tw = colw - gw - 5 * mm
    micro(c, eyebrow, tx, top - 6, color=DEEP, size=6.4)
    c.setFillColor(INK)
    c.setFont("Serif-B", 10.6)
    c.drawString(tx, top - 17, title)
    micro(c, tab, tx, top - 26, size=6)
    p, h = ph(words, small, colw)
    p.drawOn(c, x, top - gh - 7 * mm - h)
    y = min(y, top - gh - 7 * mm - h)
check(y)
c.showPage()

# ═════════════════════════ PAGE 3 · WHAT YOU DO ═════════════════════════
new_page("What you do")
y = running_head("What you do")
y = head("03", "What happens when PHAROS finds something", y)
y = para(c, "This is the part that needs you. A finding is only a question: <i>does this concern us?</i>",
         what, ML, y, CW) - 6 * mm

# a flow: finding -> you read -> decision -> two outcomes
fw = 34 * mm
fh = 17 * mm
fx = [ML, ML + fw + 8 * mm, ML + 2 * (fw + 8 * mm)]
for x, (t1, t2) in zip(fx, [("A finding", "PHAROS shows it"), ("You read it", "open the row"),
                            ("You decide", "record a decision")]):
    box(x, y, fw, fh, stroke=INK)
    c.setFillColor(INK)
    c.setFont("Serif-B", 10.4)
    c.drawString(x + 3.4 * mm, y - 7 * mm, t1)
    c.setFillColor(MUTED)
    c.setFont("Sans", 7.4)
    c.drawString(x + 3.4 * mm, y - 12 * mm, t2)
for i in range(2):
    arrow(fx[i] + fw + 0.8 * mm, y - fh / 2, fx[i + 1] - 0.8 * mm)
ox = fx[2] + fw + 8 * mm
ow = W - MR - ox
oh = 13 * mm
mid = y - fh / 2
for k, (t1, t2, fill, fg, sub) in enumerate([
        ("Doesn’t concern us", "recorded, and that is the end", SURFACE2, INK, MUTED),
        ("Concerns us", "the five-day clock starts", INK, WHITE, BEACON)]):
    oy = mid + oh + 1.5 * mm if k == 0 else mid - 1.5 * mm
    box(ox, oy, ow, oh, fill=fill, stroke=INK if k else RULE)
    c.setFillColor(fg)
    c.setFont("Serif-B", 10)
    c.drawString(ox + 3.4 * mm, oy - 5.6 * mm, t1)
    c.setFillColor(sub)
    c.setFont("Sans", 7.2)
    c.drawString(ox + 3.4 * mm, oy - 10 * mm, t2)
    ty = oy - oh / 2
    c.setStrokeColor(DEEP)
    c.setLineWidth(0.8)
    jx = fx[2] + fw + 4 * mm
    c.line(fx[2] + fw + 0.8 * mm, mid, jx, mid)
    c.line(jx, mid, jx, ty)
    arrow(jx, ty, ox - 0.8 * mm)
y -= fh + 12 * mm

y = label("When it concerns us: the five-day clock", y)
y = numbered([
    "A finding that concerns us must reach the <b>Egyptian Drug Authority within five days</b>. PHAROS counts the "
    "days for you and shows one line under the decision, for example <i>“Authority: due Fri 6 Nov, 3 days left”</i>.",
    "When it has been sent, press <b>Sent to the authority</b>, give the day it was sent, and the clock stops.",
    "If it is not sent in time the line turns into <i>“late by 2 days”</i>, and every morning at 07:00 Cairo the "
    "team gets a Telegram reminder until it is done.",
    "Nothing is ever deleted. Every decision keeps the name of the person and the time, for the inspector.",
], ML, y, CW) - 6 * mm

y = head("04", "When PHAROS reads", y, sub="All times are Cairo time")
y = rows([
    ("Every 4 hours", "The authorities’ news, web pages and lists, and the team mailbox (some authorities send "
                      "their news only by e-mail)."),
    ("Every day", "The medical literature (PubMed and others), and sites that need a full browser to read."),
    ("Every Monday", "The <b>label watch</b>: has the official product information (SmPC) of a medicine with our "
                     "ingredient changed?"),
    ("Every morning", "At 07:00, a <b>daily report</b> for the day before. On Sunday at 05:00, a <b>weekly report</b> "
                      "for the week. Both as PDF and Excel."),
], y, keyw=36 * mm)
y -= 7 * mm

y = head("05", "The screens in the app", y, sub="One line each")
y = rows([
    ("Ingredients", "The watchlist. Open one ingredient to see everything found about it. PHAROS opens here."),
    ("Sources", "One card per country: what it published since you last looked."),
    ("Products, Cases", "Our own products, and the case reports of side effects we send to the authority."),
    ("Quality", "Missed deadlines, audits and corrective actions (CAPA)."),
    ("Reports", "The daily and weekly reports, and the proof packs for an inspection."),
    ("People, Me", "Who may sign in; your own settings, such as linking Telegram."),
], y, keyw=36 * mm, gap=1.9 * mm)
check(y)
c.showPage()

# ═════════════════════════ PAGE 4 · WORDS AND RULES ═════════════════════════
new_page("Words and rules")
y = running_head("Words and rules")
y = head("06", "Words you will hear", y, sub="A small dictionary")
y = rows([
    ("Pharmacovigilance", "Watching the safety of medicines after they are sold, and acting on any new risk."),
    ("Active ingredient", "The substance in the medicine that does the work, such as <i>lornoxicam</i>. PHAROS "
                          "watches ingredients, not brand names."),
    ("Authority", "A government body that controls medicines in a country, such as the FDA (USA) or the Egyptian "
                  "Drug Authority. Also called a <b>regulator</b>."),
    ("Safety notice", "Anything an authority publishes about a risk: an alert, a letter to doctors (DHPC), a "
                      "change to the leaflet, a recall."),
    ("Finding", "A safety notice in which PHAROS found one of our ingredients. It waits for a person to review it."),
    ("Review", "A team member reads the finding and decides: <b>Concerns us</b> or <b>Doesn’t concern us</b>."),
    ("SmPC, label", "The official product information for doctors. When it changes, the label watch tells us."),
    ("Signal", "A hint that a medicine may have a new risk, which the team then studies step by step."),
    ("Case report", "A report of a side effect in one patient, sent to the authority."),
    ("Deviation, CAPA", "A deviation is a step we missed, such as a late deadline. CAPA is what we do to fix it and "
                        "stop it happening again."),
    ("Archive", "The locked store of every page and PDF PHAROS read. Nothing in it can be changed or deleted."),
], y, keyw=41 * mm, gap=1.9 * mm)
y -= 8 * mm

y = head("07", "Three rules to remember", y)
colw = (CW - 2 * 6 * mm) / 3
top = y
for i, (title, words) in enumerate([
    ("Nothing is translated", "Every authority is read in its own language. Titles stay exactly as the authority "
                              "wrote them, and every link opens the authority’s own page."),
    ("Nothing is deleted", "Pages, PDFs, decisions and reports are kept for good, with who did what and when. That "
                           "is our proof for an inspection."),
    ("A person decides", "PHAROS finds and reminds. It never decides whether a notice concerns us: a member of the "
                         "team always does."),
]):
    x = ML + i * (colw + 6 * mm)
    c.setFillColor(DEEP)
    c.setFont("Serif", 22)
    c.drawString(x, top - 9 * mm, str(i + 1))
    c.setFillColor(INK)
    c.setFont("Serif-B", 10.6)
    c.drawString(x, top - 15 * mm, title)
    rule(c, x, top - 17.5 * mm, x + colw, INK, 0.8)
    p, h = ph(words, small, colw)
    p.drawOn(c, x, top - 20 * mm - h)
    y = min(y, top - 20 * mm - h)
y -= 9 * mm

# closing band
band_h = 26 * mm
c.setFillColor(INK)
c.rect(ML, y - band_h, CW, band_h, stroke=0, fill=1)
c.setFillColor(BEACON)
c.rect(ML, y - 1.1 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
micro(c, "In short", ML + 7 * mm, y - 7.5 * mm, color=BEACON, size=6.8)
c.setFillColor(WHITE)
c.setFont("Serif", 15)
c.drawString(ML + 7 * mm, y - 15 * mm, "PHAROS reads for the team. The team decides.")
c.setFillColor(MAST_MUTED)
c.setFont("Sans", 8.4)
c.drawString(ML + 7 * mm, y - 21 * mm, "Questions about a finding go to the Qualified Person for Pharmacovigilance.")
y -= band_h
check(y)
c.showPage()
c.save()
print("\n".join(report))
print("wrote", OUT)
