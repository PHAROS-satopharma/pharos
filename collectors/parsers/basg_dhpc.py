"""PHAROS — BASG (Austria), « Sicherheitsinformationen (DHPC) ».

Source: ``basg-dhpc``; ``source.url``:
``https://www.basg.gv.at/gesundheitsberufe/sicherheitsinformationen-dhpc``

BASG's whole-site RSS (``basg-whatsnew``) carries no DHPC at all: on 5 Nov 2026 it held 56 items
from 25 Sep to 3 Nov, while the Caelyx (3 Nov) and Ocrevus (12 Oct) letters were posted in that
window. The letters are only on this page.

Page structure relied on (checked 5 Nov 2026): one upload list per year, each letter one
``ul.ce-uploads li.list-item``:

* ``a[href]`` → ``/fileadmin/redakteure/06_Gesundheitsberufe/DHPC/<YYYY>/<YYMMDD>_<Name>.pdf``,
  the letter itself (item URL, external id and attachment);
* ``.ce-uploads-fileName`` — "261103_Caelyx": the product name is often only here;
* ``.ce-uploads-description`` — "Wichtige Information des Bundesamtes … über …", the title as
  published;
* ``.ce-uploads-date`` — ``dd.mm.yyyy``.

Options: ``include_keywords`` / ``exclude_keywords``; ``doc_type`` (``dhpc``); ``lang`` (``de``).
"""

from __future__ import annotations

from collectors.parsers._html_util import absolute, keep, local_date, node_text, require
from collectors.parsers.base import Item, SourceConfig, soup


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "de"
    items: list[Item] = []
    seen: set[str] = set()
    for li in doc.select("ul.ce-uploads li.list-item"):
        link = li.select_one("a[href]")
        if link is None:
            continue
        url = absolute(link["href"], base_url)
        if not url or url in seen:
            continue
        name = node_text(li.select_one(".ce-uploads-fileName"))
        description = node_text(li.select_one(".ce-uploads-description"))
        when = node_text(li.select_one(".ce-uploads-date"))
        title = description or name
        if not title or not keep(source, name, description):
            continue
        seen.add(url)
        items.append(Item(
            external_id=url, url=url, title=title, published=local_date(when, lang),
            doc_type=(source.options or {}).get("doc_type", "dhpc"), lang=lang,
            body_text="\n".join(x for x in (name, description) if x),
            attachment_urls=[url] if url.lower().endswith(".pdf") else [],
            structured={"file_name": name, "date_text": when}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    f = ctx.get(source.url)
    if f.status == 304:
        return []
    items = parse_list(f, f.final_url, source)
    require(items or soup(f).select("ul.ce-uploads li.list-item"), f, marker="ce-uploads")
    return items
