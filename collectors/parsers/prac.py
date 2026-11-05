"""PHAROS — EMA PRAC: recommendations on safety signals, and PRAC meeting highlights.

Source: ``ema-prac`` (English; EMA translates the signal recommendations into every EU language).

1. ``source.url`` — the signals page
   ``https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/pharmacovigilance-post-authorisation/signal-management/prac-recommendations-safety-signals``.
   Each document is a ``div.bcl-file[data-ema-document-type="prac-recommendation"]`` holding
   ``p.file-title`` ("PRAC recommendations on signals adopted at the 28 September-1 October 2026
   PRAC meeting"), a "Reference Number" ``span.value`` (EMA/PRAC/206892/2026), the English PDF link
   (``…-prac_en.pdf``) with ``time[datetime]`` (first published), and ``div.file-translations`` with
   one link per language ``/xx/documents/…-prac_xx.pdf``. One item per document, doc_type
   ``signal``, ``lang`` ``en``; the translations go to ``structured.translations`` as
   ``{lang: url}`` (the contract has no per-attachment language). The page is large (> 1 MB).
2. ``options.highlights_url`` (default: the PRAC committee page
   ``https://www.ema.europa.eu/en/committees/pharmacovigilance-risk-assessment-committee-prac``) —
   ``h3.teaser-title a[href^="/en/news/"]`` whose text has "highlights", with the date in the card's
   ``div.metadata-item`` ("30 October 2026"). doc_type ``safety_update``; detail body ``main``.
3. ``options.meetings_url`` (default: ``…/en/committees/prac/prac-agendas-minutes-highlights``) — the
   agendas and minutes of PRAC meetings, ``div.bcl-file[data-ema-document-type="agenda"|"minutes"]`` with
   ``.file-title`` ("Agenda of the PRAC meeting 26 - 29 October 2026"), the Reference Number, the English PDF
   and ``time[datetime]``. An agenda names every substance PRAC will discuss, weeks before a recommendation:
   the early warning. One item per PDF, doc_type ``safety_update``, ``structured.kind`` ``prac_agenda`` or
   ``prac_minutes``; the PDF is screened as the attachment. An agenda is published as a draft and may be
   replaced under the same address: the URL is the identity.

(checked 4 Nov 2026; agendas 5 Nov 2026)

Options: ``highlights_url`` / ``meetings_url`` (``""`` switches either off), ``attach_languages`` — translation languages
whose PDFs are also downloaded as attachments (default none: the English original is screened),
``include_keywords`` / ``exclude_keywords``.
"""

from __future__ import annotations

import logging
import re

from collectors.parsers._html_util import (absolute, clean, fill_detail, keep, local_date,
                                           node_text, require)
from collectors.parsers.base import Item, SourceConfig, soup

HOST = "https://www.ema.europa.eu"
COMMITTEE = HOST + "/en/committees/pharmacovigilance-risk-assessment-committee-prac"
MEETINGS = HOST + "/en/committees/prac/prac-agendas-minutes-highlights"
_MEETING_KIND = {"agenda": "prac_agenda", "minutes": "prac_minutes"}
_PDF_LANG = re.compile(r"_([a-z]{2})\.pdf$", re.I)
_PATH_LANG = re.compile(r"^/([a-z]{2})/documents/")
_REF = re.compile(r"EMA/PRAC/\d+/\d{4}")
log = logging.getLogger(__name__)


def _lang_of(href: str) -> str | None:
    m = _PDF_LANG.search(href.split("?")[0])
    if m:
        return m.group(1).lower()
    m = _PATH_LANG.search(href)
    return m.group(1).lower() if m else None


def parse_signals(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    attach = {x.lower() for x in (source.options or {}).get("attach_languages") or []}
    items: list[Item] = []
    seen: set[str] = set()
    for block in doc.select('div.bcl-file[data-ema-document-type="prac-recommendation"]'):
        title = node_text(block.select_one("p.file-title"))
        translations: dict[str, str] = {}
        tr_box = block.select_one("div.file-translations")
        if tr_box is not None:
            for a in tr_box.select("a[href$='.pdf']"):
                lang = _lang_of(a["href"])
                if lang:
                    translations.setdefault(lang, absolute(a["href"], base_url))
            tr_box.extract()
        english = None
        for a in block.select("a[href]"):
            if a["href"].lower().endswith(".pdf"):
                english = absolute(a["href"], base_url)
                break
        if not title or not english or english in seen or not keep(source, title):
            continue
        seen.add(english)
        t = block.select_one("time[datetime]")
        ref = _REF.search(node_text(block))
        attachments = [english] + [u for lg, u in translations.items() if lg in attach]
        items.append(Item(
            external_id=ref.group(0) if ref else english, url=english, title=title,
            published=local_date((t["datetime"] if t else "")[:10], "en"), doc_type="signal",
            lang="en", attachment_urls=attachments,
            structured={"reference": ref.group(0) if ref else None,
                        "translations": translations or None}))
    return items


def parse_highlights(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    items: list[Item] = []
    seen: set[str] = set()
    for a in doc.select("h3.teaser-title a[href]"):
        href = a["href"]
        title = node_text(a)
        if "/news/" not in href or "highlight" not in title.casefold():
            continue
        url = absolute(href, base_url)
        if url in seen or not keep(source, title):
            continue
        seen.add(url)
        card = a.find_parent("article") or a.find_parent("div")
        meta = " ".join(node_text(m) for m in card.select("div.metadata-item")) if card else ""
        items.append(Item(external_id=url, url=url, title=title, published=local_date(meta, "en"),
                          doc_type="safety_update", lang="en"))
    return items


def parse_meetings(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    items: list[Item] = []
    seen: set[str] = set()
    for block in doc.select("div.bcl-file[data-ema-document-type]"):
        kind = _MEETING_KIND.get(block.get("data-ema-document-type", ""))
        if kind is None:
            continue
        title = node_text(block.select_one(".file-title"))
        pdf = next((absolute(a["href"], base_url) for a in block.select("a[href]")
                    if a["href"].lower().split("?")[0].endswith("_en.pdf")), None)
        if not title or not pdf or pdf in seen or not keep(source, title):
            continue
        seen.add(pdf)
        t = block.select_one("time[datetime]")
        ref = _REF.search(node_text(block))
        items.append(Item(
            external_id=pdf, url=pdf, title=title,
            published=local_date((t["datetime"] if t else "")[:10], "en"), doc_type="safety_update",
            lang="en", attachment_urls=[pdf],
            structured={"reference": ref.group(0) if ref else None, "kind": kind}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    out: list[Item] = []
    f = ctx.get(source.url)
    if f.status != 304:
        got = parse_signals(f, f.final_url, source)
        require(got or soup(f).select('div[data-ema-document-type="prac-recommendation"]'), f,
                marker="prac-recommendation")
        out.extend(got)
    hl = (source.options or {}).get("highlights_url", COMMITTEE)
    if hl:
        g = ctx.get(hl)
        if g.status != 304:
            out.extend(parse_highlights(g, g.final_url, source))
    meetings = (source.options or {}).get("meetings_url", MEETINGS)
    if meetings:
        m = ctx.get(meetings)
        if m.status != 304:
            got = parse_meetings(m, m.final_url, source)
            if not got:
                # never fail the signals over the agendas page: warn, and the signals still count
                log.warning("ema-prac: no PRAC agenda or minutes found on %s", meetings)
            out.extend(got)
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    if item.url.lower().endswith(".pdf"):
        return item
    return fill_detail(item, ctx.get(item.url), "main", patterns=(".pdf",))


__all__ = ["clean", "fetch_detail", "list_items", "parse_highlights", "parse_meetings", "parse_signals"]
