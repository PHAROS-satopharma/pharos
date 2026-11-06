"""The MeSH names in the adverse-reactions section of a label (migration 0062).

For each ingredient, two labels: our own (``our_label``, section 4.8, when it is in English) and the reference
product's latest label in English (the product the team follows first, else any English one: SmPC 4.8 or the US
"Adverse reactions"). ``find_terms`` reads the section word by word and takes the longest MeSH name at each place;
body-system headings and generic words (disease, syndrome …) are never taken on their own. The result is
``label_coded`` and ``label_mesh``; ``mesh_listed()`` then says which label lists a reaction. A label is coded again
when it changes or when a new MeSH release is loaded.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from collectors.coding.norm import norm

log = logging.getLogger("collectors.coding.labels")

MAX_WORDS = 8
GENERIC = {
    "disease", "diseases", "syndrome", "syndromes", "disorder", "disorders", "infection", "infections", "pain",
    "reaction", "reactions", "injury", "injuries", "abnormalities", "lesion", "lesions", "death", "fever",
    "weight loss", "weight gain", "body weight", "signs and symptoms", "pathological conditions",
    "drug related side effects and adverse reactions", "chemically induced disorders", "neoplasms",
}

TERMS_SQL = """
select t.ui, t.term
  from mesh_term t join mesh_descriptor d on d.ui = t.ui
 where exists (select 1 from unnest(d.trees) tr where tr like '%.%')
"""

OUR_SQL = """
select distinct on (ingredient_id) ingredient_id::text, id::text as ref, product_name, version,
       sections ->> '4.8' as text
  from our_label
 where superseded_at is null and lang ilike 'en%' and coalesce(sections ->> '4.8', '') <> ''
 order by ingredient_id, uploaded_at desc
"""

REFERENCE_SQL = """
select distinct on (sp.ingredient_id) sp.ingredient_id::text, sn.id::text as ref, sp.product_name,
       sn.doc_date, sn.r2_key
  from spc_product sp
  join source s on s.id = sp.source_id
  join lateral (select id, doc_date, r2_key from spc_snapshot
                 where spc_product_id = sp.id and r2_key is not null
                 order by fetched_at desc limit 1) sn on true
 where sp.active and coalesce(s.languages[1], '') ilike 'en%'
 order by sp.ingredient_id, sp.is_reference desc, sn.doc_date desc nulls last
"""

CODED_SQL = "select ingredient_id::text, source, label_ref, mesh_version from label_coded"


def index(rows: list[dict]) -> dict[str, tuple[str, str]]:
    """norm(name) -> (ui, name), for every name of a descriptor that is not a body-system heading."""
    out: dict[str, tuple[str, str]] = {}
    for r in rows:
        key = norm(r["term"])
        if len(key) >= 4 and key not in GENERIC and len(key.split()) <= MAX_WORDS:
            out.setdefault(key, (r["ui"], r["term"]))
    return out


def find_terms(text: str | None, names: dict[str, tuple[str, str]]) -> dict[str, str]:
    """ui -> the name found, taking the longest name at each place in the text (a plural 's' either way)."""
    words = norm(text).split()
    found: dict[str, str] = {}
    i = 0
    while i < len(words):
        for n in range(min(MAX_WORDS, len(words) - i), 0, -1):
            key = " ".join(words[i:i + n])
            hit = (names.get(key) or (names.get(key + "s") if len(key) >= 4 else None)
                   or (names.get(key[:-1]) if key.endswith("s") and len(key) > 4 else None))
            if hit:
                found.setdefault(hit[0], hit[1])
                i += n
                break
        else:
            i += 1
    return found


def _reference_text(load: Callable[[str], dict | None], r2_key: str) -> str | None:
    body = load(r2_key)
    if not body:
        return None
    sections = body.get("sections") or {}
    return sections.get("4.8") or sections.get("us:adverse_reactions")


def _store(db: Any, ingredient: str, source: str, ref: str, name: str, version: str | None,
           found: dict[str, str]) -> None:
    with db.transaction():
        db.execute(
            """insert into label_coded (ingredient_id, source, label_ref, label_name, mesh_version, terms, coded_at)
               values (%(i)s::uuid, %(s)s, %(r)s, %(n)s, %(v)s, %(t)s, now())
               on conflict (ingredient_id, source) do update set label_ref = excluded.label_ref,
                 label_name = excluded.label_name, mesh_version = excluded.mesh_version, terms = excluded.terms,
                 coded_at = now()""",
            {"i": ingredient, "s": source, "r": ref, "n": name, "v": version, "t": len(found)})
        db.execute("delete from label_mesh where ingredient_id = %(i)s::uuid and source = %(s)s",
                   {"i": ingredient, "s": source})
        if found:
            db.execute(
                """insert into label_mesh (ingredient_id, source, ui, term)
                   select %(i)s::uuid, %(s)s, f ->> 'ui', f ->> 'term' from jsonb_array_elements(%(f)s::jsonb) f""",
                {"i": ingredient, "s": source,
                 "f": json.dumps([{"ui": u, "term": t} for u, t in sorted(found.items())])})


def code_labels(db: Any, load: Callable[[str], dict | None] | None = None, *, force: bool = False) -> str:
    """Code every label that changed since it was coded; what was done, in words."""
    row = db.fetchone("select version, sha256 from coding_dictionary where name = 'mesh'")
    if not row:
        return "MeSH is not loaded: no label coded"
    version = f"{row['version']} ({(row['sha256'] or '')[:12]})"   # a release loaded again is coded again
    if load is None:
        from collectors.core.archive import Archive

        archive = Archive()

        def load(key: str) -> dict | None:
            raw = archive.get(key)
            try:
                return json.loads(raw.decode("utf-8")) if raw else None
            except (ValueError, UnicodeDecodeError):
                return None

    done = {(r["ingredient_id"], r["source"]): (r["label_ref"], r["mesh_version"]) for r in db.fetchall(CODED_SQL)}
    names: dict[str, tuple[str, str]] | None = None
    coded = unread = 0
    wanted: set[tuple[str, str]] = set()
    labels = [("our_label", r) for r in db.fetchall(OUR_SQL)] + [("reference", r) for r in db.fetchall(REFERENCE_SQL)]
    for source, r in labels:
        key = (r["ingredient_id"], source)
        wanted.add(key)
        if not force and done.get(key) == (r["ref"], version):
            continue
        text = r.get("text") if source == "our_label" else _reference_text(load, r["r2_key"])
        if not text:
            unread += 1
            continue
        if names is None:
            names = index(db.fetchall(TERMS_SQL))
        name = (f"{r['product_name']}, {r['version']}" if source == "our_label"
                else f"{r['product_name']}" + (f", {r['doc_date']}" if r.get("doc_date") else ""))
        _store(db, r["ingredient_id"], source, r["ref"], name, version, find_terms(text, names))
        coded += 1
    gone = [k for k in done if k not in wanted]
    for ingredient, source in gone:     # a label withdrawn or no longer in English
        db.execute("delete from label_coded where ingredient_id = %(i)s::uuid and source = %(s)s",
                   {"i": ingredient, "s": source})
    words = f"{coded} labels coded, {len(wanted) - coded - unread} unchanged"
    return words + (f", {unread} could not be read" if unread else "") + (f", {len(gone)} removed" if gone else "")
