"""PHAROS — AEMPS (Spain), « Cartas de seguridad a los profesionales sanitarios ».

Source: ``aemps-dhpc``; ``source.url``: ``https://docswebaemps.aemps.es/php/mostrar.php``

AEMPS does not post its DHPCs to the site news, so the whole-site feed (``aemps-feed``) missed
them: on 5 Nov 2026 the feed held the last 30 posts (2 Oct – 5 Nov) and not the Ocrevus letter of
8 Oct. The letters page (aemps.gob.es → Farmacovigilancia → Cartas de seguridad) embeds
``https://docswebaemps.aemps.es/cartasfarmacovigilancia``, which reads this JSON: one array with
the whole archive since 2007 (412 rows), no paging. Each row:

* ``id``; ``principioActivo``; ``nombreComercial``; ``asunto`` (the subject as published);
* ``rutaPDF`` → the letter at ``https://docswebaemps.aemps.es/PDF/<rutaPDF>`` (URL-encoded);
* ``fecha`` ("Octubre 2026", "enero-2007"); ``fecha_publicacion_programada``
  ("2026-10-08 07:00:00", Madrid time; empty on old rows). A row scheduled for later is not
  public yet and is skipped.

The title is the row as the list shows it, in Spanish: "OCREVUS (Ocrelizumab): NUEVO RIESGO …".
Rows older than ``since_days`` (400) are left out: the archive back to 2007 is not screened again.

Options: ``since_days`` (400); ``doc_type`` (``dhpc``); ``lang`` (``es``); ``include_keywords`` /
``exclude_keywords``.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from collectors.parsers._html_util import clean, keep, local_date
from collectors.parsers.base import Item, ParseError, SourceConfig

PDF_BASE = "https://docswebaemps.aemps.es/PDF/"
MADRID = ZoneInfo("Europe/Madrid")
REQUIRED = {"id", "asunto", "rutaPDF", "fecha"}


def _scheduled(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp.strip()[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=MADRID)
    except ValueError:
        return None


def parse_rows(rows: list, source: SourceConfig, *, now: datetime | None = None) -> list[Item]:
    if not isinstance(rows, list):
        raise ParseError("AEMPS letters answer is not a list")
    if rows and not REQUIRED <= set(rows[0]):
        raise ParseError(f"AEMPS letters changed shape: {sorted(rows[0])[:10]}")
    opts = source.options or {}
    lang = source.lang or "es"
    now = now or datetime.now(MADRID)
    oldest = now.date() - timedelta(days=int(opts.get("since_days", 400)))
    items: list[Item] = []
    for row in rows:
        subject, path = clean(row.get("asunto")), clean(row.get("rutaPDF"))
        brand, substance = clean(row.get("nombreComercial")), clean(row.get("principioActivo"))
        if not subject or not path:
            continue
        scheduled = _scheduled(row.get("fecha_publicacion_programada"))
        if scheduled and scheduled > now:
            continue                                    # not public yet
        published: date | None = scheduled.date() if scheduled else local_date(row.get("fecha"), lang)
        if published is None or published < oldest:
            continue
        if not keep(source, brand, substance, subject):
            continue
        head = f"{brand} ({substance})" if brand and substance else (brand or substance)
        url = PDF_BASE + quote(path)
        items.append(Item(
            external_id=f"aemps-dhpc:{row['id']}", url=url,
            title=f"{head}: {subject}" if head else subject, published=published,
            doc_type=opts.get("doc_type", "dhpc"), lang=lang,
            body_text="\n".join(x for x in (brand, substance, subject) if x), attachment_urls=[url],
            structured={"id": row["id"], "principio_activo": substance, "nombre_comercial": brand,
                        "fecha": row.get("fecha")}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    f = ctx.get(source.url, accept="application/json")
    if f.status == 304:
        return []
    try:
        rows = json.loads(f.content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ParseError(f"AEMPS letters did not answer JSON: {exc}") from exc
    return parse_rows(rows, source)
