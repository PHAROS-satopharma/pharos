"""Writing the gap check to ``label_gap`` (migration 0043).

``gap_for_change`` runs when the label watch records a change: the change against every current version of our
label for the ingredient. ``recompute_gaps`` runs on every collection run and catches up: the changes of the last
year that have no row yet for a current version of our label (a new version uploaded on the screen is compared
with them all on the next run). Both upsert on (change, label), so a run that is repeated changes nothing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from collectors.labels.gap import label_gap

log = logging.getLogger(__name__)

RECOMPUTE_DAYS = 365
RECOMPUTE_LIMIT = 500          # per run; what is left waits for the next one

READ_SQL = """
select sc.id::text as change_id, sc.diff,
       ol.id::text as label_id, ol.lang as our_lang, ol.sections as our_sections,
       coalesce(d.lang, s.languages[1]) as their_lang
  from spc_change sc
  join spc_product sp on sp.id = sc.spc_product_id
  join source s on s.id = sp.source_id
  join our_label ol on ol.ingredient_id = sp.ingredient_id and ol.superseded_at is null
  left join issue i on i.id = sc.issue_id
  left join document d on d.id = i.anchor_document_id
 where sc.created_at >= now() - make_interval(days => %(days)s)
   and not exists (select 1 from label_gap lg where lg.spc_change_id = sc.id and lg.our_label_id = ol.id)
 order by sc.created_at desc, sc.id, ol.uploaded_at desc
 limit %(limit)s
"""

LABELS_SQL = """
select id::text as id, lang, sections
  from our_label
 where ingredient_id = %(i)s and superseded_at is null
 order by uploaded_at desc, id
"""

WRITE_SQL = """
insert into label_gap (spc_change_id, our_label_id, gap, computed_at)
values (%(c)s, %(l)s, %(g)s, now())
on conflict (spc_change_id, our_label_id) do update set gap = excluded.gap, computed_at = now()
"""


def _jsonb(value: Any) -> Any:
    try:
        from collectors.core.db import jsonb

        return jsonb(value)
    except ImportError:  # pragma: no cover - fixture tests without the db layer
        return json.dumps(value, ensure_ascii=False)


def store_gap(db: Any, change_id: str, label_id: str, gap: dict) -> None:
    """One row per (change, version of our label); computed again on conflict."""
    db.execute(WRITE_SQL, {"c": change_id, "l": label_id, "g": _jsonb(gap)})


def gap_for_change(db: Any, change_id: str, ingredient_id: str, diff: Any, their_lang: str | None) -> int:
    """The change just recorded against every current version of our label for the ingredient. -> rows written."""
    labels = db.fetchall(LABELS_SQL, {"i": ingredient_id})
    for label in labels:
        gap = label_gap(diff, label.get("sections"), label.get("lang"), their_lang)
        store_gap(db, change_id, str(label["id"]), gap)
    return len(labels)


def recompute_gaps(db: Any, days: int = RECOMPUTE_DAYS, limit: int = RECOMPUTE_LIMIT) -> int:
    """The changes of the last ``days`` with no gap yet for a current version of our label. -> rows written."""
    rows = db.fetchall(READ_SQL, {"days": days, "limit": limit})
    for row in rows:
        gap = label_gap(row.get("diff"), row.get("our_sections"), row.get("our_lang"), row.get("their_lang"))
        store_gap(db, str(row["change_id"]), str(row["label_id"]), gap)
    if rows:
        log.info("label gap: %d comparison(s) written", len(rows))
    return len(rows)
