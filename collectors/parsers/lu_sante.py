"""PHAROS — Direction de la santé (Luxembourg), DHPC page on santesecu.public.lu.

Source: ``lu-dhpc``; ``source.url``:
``https://santesecu.public.lu/fr/espace-professionnel/departement-sante/pharmacies-et-medicaments/pharmacovigilance/gestion-riques/dhcp.html``

Page structure relied on (checked 4 Nov 2026): an accordion (``div.accordionItem``, one per year) of
``div.cmp-text ul li``, each entry being

``<a href="//santesecu.public.lu/dam-assets/…/dhpc-ocrevus-lu-fr.pdf">Ocrevus (ocrelizumab): (Pdf - 259 Ko)</a>
Nouveau risque de lésion hépatique … | 08.10.2026``

The title is the entry's own text with the file-size marker "(Pdf - 259 Ko)" and the trailing
" | dd.mm.yyyy" removed — nothing else changes. The item URL is the PDF (also its attachment).
Circulars titled « Brèves de pharmacovigilance » are ``safety_update``; everything else ``dhpc``.

Options: ``include_keywords`` / ``exclude_keywords``; ``lang`` (``fr``).
"""

from __future__ import annotations

import re

from collectors.parsers._html_util import absolute, clean, keep, local_date, node_text, require
from collectors.parsers.base import Item, SourceConfig, soup

_SIZE = re.compile(r"\(\s*(?:pdf|docx?|xlsx?)\s*-\s*[\d.,]+\s*(?:ko|mo|kb|mb|o)\s*\)", re.I)
_TRAIL_DATE = re.compile(r"\s*\|\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*$")


def tidy_title(text: str) -> tuple[str, str | None]:
    """-> (title without size marker and trailing date, the date text)."""
    t = clean(text)
    m = _TRAIL_DATE.search(t)
    when = m.group(1) if m else None
    if m:
        t = t[: m.start()]
    t = clean(_SIZE.sub("", t)).strip(" |")
    return t, when


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "fr"
    scope = doc.select_one("main") or doc
    items: list[Item] = []
    seen: set[str] = set()
    for li in scope.select("div.cmp-text li"):
        a = li.select_one("a[href]")
        if a is None or ".pdf" not in a["href"].lower():
            continue
        url = absolute(a["href"], base_url)
        title, when = tidy_title(node_text(li))
        if url in seen or not title or not keep(source, title):
            continue
        seen.add(url)
        name = clean(_SIZE.sub("", node_text(a))).rstrip(" :")
        items.append(Item(
            external_id=url, url=url, title=title, published=local_date(when, lang),
            doc_type="safety_update" if title.casefold().startswith("brèves") else "dhpc",
            lang=lang, body_text=title, attachment_urls=[url],
            structured={"product": name or None, "date_text": when}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    f = ctx.get(source.url)
    if f.status == 304:
        return []
    items = parse_list(f, f.final_url, source)
    require(items or soup(f).select("div.cmp-text li a[href$='.pdf']"), f, marker="cmp-text")
    return items
