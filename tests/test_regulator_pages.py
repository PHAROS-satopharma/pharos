"""Dr Sama's pages (the regulator_page seed in 0032_sources_horizontal.sql) against the catalogue
(collectors/sources.yaml), and every source's human page (`page:`). Nothing here touches a database."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from collectors.core.memstore import MemoryStore
from collectors.core.registry import CatalogueError, load_catalogue, sync_catalogue

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "0032_sources_horizontal.sql"
ROW = re.compile(r"^\s*\('([A-Z_]+)', '(database|dhpc|safety)', (\d+), '((?:[^']|'')*)', '([^']+)', "
                 r"'\{([^}]*)\}', (true|false), (null|'(?:[^']|'')*')\),?$")
# The same rule as new_items() in the migration and isFeedUrl() in web/src/features/sources/horizontal.ts.
FEED = r"(\.(xml|json|rss|atom)([?#]|$)|/(rss|feed|atom)(/|[?#]|$)|^https?://api\.)"
IS_FEED = re.compile(FEED, re.I)

REGULATORS, SOURCES, _ = load_catalogue()
BY_ID = {s.id: s for s in SOURCES}


def _text(quoted: str) -> str | None:
    return None if quoted == "null" else quoted[1:-1].replace("''", "'")


def pages() -> list[dict]:
    sql = MIGRATION.read_text(encoding="utf-8")
    seed = sql.split("insert into regulator_page", 1)[1].split("on conflict", 1)[0]
    rows = []
    for line in seed.splitlines()[1:]:          # the first line names the columns
        if not line.strip():
            continue
        m = ROW.match(line)
        assert m, f"not one page per line: {line[:90]}"
        reg, kind, sort, label, url, read_by, partial, note = m.groups()
        rows.append({"regulator": reg, "kind": kind, "sort": int(sort), "label": label.replace("''", "'"),
                     "url": url, "read_by": [x for x in read_by.split(",") if x],
                     "partial": partial == "true", "note": _text(note)})
    return rows


PAGES = pages()


def test_her_25_authorities_are_known_to_the_catalogue():
    regs = {p["regulator"] for p in PAGES}
    assert len(regs) == 25
    assert regs <= {r["id"] for r in REGULATORS}
    assert "EMA" in regs                                   # the European Union is one of her 25


def test_each_page_once_and_in_her_order():
    seen = set()
    for p in PAGES:
        key = (p["regulator"], p["url"])
        assert key not in seen, key
        seen.add(key)
    for reg in {p["regulator"] for p in PAGES}:
        sorts = [p["sort"] for p in PAGES if p["regulator"] == reg]
        assert sorts == list(range(1, len(sorts) + 1)), reg


def test_read_by_names_switched_on_sources_of_the_same_authority():
    for p in PAGES:
        for sid in p["read_by"]:
            src = BY_ID.get(sid)
            assert src is not None, f"{p['url']}: unknown source {sid}"
            assert src.enabled, f"{p['url']}: {sid} is switched off"
            assert src.regulator_id == p["regulator"], f"{p['url']}: {sid} belongs to {src.regulator_id}"


def test_a_database_page_is_read_by_the_label_watch_only():
    for p in PAGES:
        kinds = {BY_ID[s].kind for s in p["read_by"]}
        if p["kind"] == "database":
            assert kinds <= {"spc"}, p["url"]
            if kinds:
                assert "Label watch" in (p["note"] or ""), p["url"]
        else:
            assert "spc" not in kinds, p["url"]


def test_a_page_read_from_the_mailbox_says_so():
    for p in PAGES:
        by_mail = any(BY_ID[s].channel == "email" for s in p["read_by"])
        assert by_mail == (p["note"] or "").startswith("By e-mail subscription"), p["url"]


def test_partly_read_pages_are_read_and_explained():
    for p in PAGES:
        if p["partial"]:
            assert p["read_by"] and p["note"], p["url"]


def test_her_pages_are_web_pages_not_feeds():
    for p in PAGES:
        assert p["url"].startswith("https://"), p["url"]
        assert not IS_FEED.search(p["url"]), p["url"]
        assert p["label"] and len(p["label"]) <= 60, p["label"]


def test_her_exact_addresses_are_kept():
    urls = {p["url"] for p in PAGES}
    # moved or broken since her list was written: kept as she wrote them, with a note
    for url in ("https://www.cbg-meb.nl/onderwerpen/medicijninformatie-nieuws-over-veiligheid-van-medicijnen",
                "https://www.hpra.ie/homepage/about-us/publications-forms/newsletters",
                "https://cns.public.lu/en/legislations/textes-coordonnes/liste-med-comm.html"):
        assert url in urls
        assert next(p for p in PAGES if p["url"] == url)["note"]
    fda = next(p for p in PAGES if p["regulator"] == "FDA" and p["kind"] == "safety")
    assert fda["label"] == "Press announcements (bottom of the FDA home page)" and not fda["read_by"]


def test_new_items_uses_the_same_feed_rule():
    assert f"d.url ~* '{FEED}'" in MIGRATION.read_text(encoding="utf-8")


def test_every_catalogue_source_has_a_human_page():
    for s in SOURCES:
        assert s.page_url, f"{s.id}: no page"
        assert s.page_url.startswith("https://"), s.id
        assert not IS_FEED.search(s.page_url), f"{s.id}: {s.page_url} is a feed or an API"


def test_the_page_reaches_the_source_row():
    store = MemoryStore()
    sync_catalogue(store)
    assert store.source["fda-enforcement"]["page_url"] == "https://www.accessdata.fda.gov/scripts/ires/index.cfm"
    assert store.source["bfarm-rhb"]["page_url"].endswith("/Rote-Hand-Briefe/_node.html")


def test_a_page_that_is_not_a_web_address_is_refused(tmp_path):
    cat = tmp_path / "sources.yaml"
    cat.write_text(
        "regulators:\n"
        "  - {id: X, country_code: XX, country_name: Nowhere, name: X, languages: [en]}\n"
        "sources:\n"
        "  - {id: x, regulator: X, kind: safety, channel: rss, url: 'https://x.test/feed.xml',\n"
        "     page: 'x.test/news', parser: feed, languages: [en], schedule: 4h}\n", encoding="utf-8")
    with pytest.raises(CatalogueError, match="page"):
        load_catalogue(cat)
