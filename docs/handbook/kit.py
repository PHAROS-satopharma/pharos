"""Shared drawing kit for the PHAROS handbook: fonts, colours, paragraph styles and page furniture."""
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph

W, H = A4
F = "C:/Windows/Fonts/"
SKILL = "C:/Users/satoh/.claude/skills/sato-pharma-identity/assets/fonts/"
# The app's own logo files, in this checkout (never another checkout's copy).
BRAND = str(Path(__file__).resolve().parents[2] / "web" / "public" / "brand") + "/"

for name, path in [
    ("Serif", F + "NotoSerif-Regular.ttf"), ("Serif-B", F + "NotoSerif-Bold.ttf"),
    ("Serif-I", F + "NotoSerif-Italic.ttf"),
    ("Sans", F + "NotoSans-Regular.ttf"), ("Sans-B", F + "NotoSans-Bold.ttf"),
    ("Sans-I", F + "NotoSans-Italic.ttf"),
    ("Mono", F + "consola.ttf"), ("Script", SKILL + "certificate-name.ttf"),
]:
    pdfmetrics.registerFont(TTFont(name, path))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-B", italic="Sans-I", boldItalic="Sans-B")
pdfmetrics.registerFontFamily("Serif", normal="Serif", bold="Serif-B", italic="Serif-I", boldItalic="Serif-B")

INK = HexColor("#02224C")
PAPER = HexColor("#F6F4EF")
SURFACE2 = HexColor("#EFECE4")
RULE = HexColor("#D9D5CC")
MUTED = HexColor("#5B6670")
SEA = HexColor("#1F4E5F")
BEACON = HexColor("#E3A336")
DEEP = HexColor("#8A5A0B")
WHITE = HexColor("#FFFFFF")
MAST_MUTED = HexColor("#B4C0CF")

ML, MR = 16 * mm, 16 * mm
CW = W - ML - MR

body = ParagraphStyle("body", fontName="Sans", fontSize=8.6, leading=12.2, textColor=INK)
small = ParagraphStyle("small", parent=body, fontSize=7.8, leading=10.8)
note = ParagraphStyle("note", parent=body, fontSize=7.6, leading=10.6, textColor=MUTED)
lead = ParagraphStyle("lead", parent=body, fontName="Serif", fontSize=11.2, leading=16, textColor=INK)
h2 = ParagraphStyle("h2", fontName="Serif-B", fontSize=13, leading=16, textColor=INK)
h3 = ParagraphStyle("h3", fontName="Sans-B", fontSize=8.8, leading=11.5, textColor=SEA)


def para(c, text, style, x, y_top, width):
    """Draw a paragraph with its top at y_top; return the y just under it."""
    p = Paragraph(text, style)
    _, h = p.wrap(width, 1000)
    p.drawOn(c, x, y_top - h)
    return y_top - h


def micro(c, text, x, y, color=MUTED, size=6.4, spacing=1.1, align="left"):
    c.setFillColor(color)
    c.setFont("Mono", size)
    t = text.upper()
    width = sum(pdfmetrics.stringWidth(ch, "Mono", size) + spacing for ch in t) - spacing
    if align == "right":
        x -= width
    to = c.beginText(x, y)
    to.setFont("Mono", size)
    to.setCharSpace(spacing)
    to.textOut(t)
    to.setCharSpace(0)
    c.drawText(to)
    return width


def rule(c, x1, y, x2, color=RULE, w=0.6):
    c.setStrokeColor(color)
    c.setLineWidth(w)
    c.line(x1, y, x2, y)


def section_head(c, num, title, y, sub=None):
    """Numbered section head: outline-free serif number in beacon-deep, title, ink rule under it."""
    c.setFillColor(DEEP)
    c.setFont("Serif", 20)
    c.drawString(ML, y - 17, num)
    c.setFillColor(INK)
    c.setFont("Serif-B", 15)
    c.drawString(ML + 12 * mm, y - 15, title)
    if sub:
        micro(c, sub, W - MR, y - 14, align="right")
    rule(c, ML, y - 22, W - MR, INK, 0.8)
    return y - 30


def page_furniture(c, page, total, label):
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    # foot
    rule(c, ML, 14 * mm, W - MR, RULE)
    micro(c, f"PHAROS handbook  ·  {label}", ML, 9.6 * mm)
    micro(c, f"Page {page} of {total}", W - MR, 9.6 * mm, align="right")
    c.drawImage(BRAND + "sato-pharma.png", W / 2 - 9 * mm, 7.6 * mm, width=18 * mm, height=18 * mm * 116 / 307,
                mask="auto")


def running_head(c, title):
    c.drawImage(BRAND + "pharos-logo.png", ML, H - 19 * mm, width=33 * mm, height=33 * mm * 667 / 2000, mask="auto")
    micro(c, title, W - MR, H - 13.4 * mm, align="right", color=INK)
    rule(c, ML, H - 21.5 * mm, W - MR, INK, 0.8)
    c.setFillColor(BEACON)
    c.rect(ML, H - 22.6 * mm, 18 * mm, 1.1 * mm, stroke=0, fill=1)
    return H - 30 * mm
