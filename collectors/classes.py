"""Drug classes from the ATC code: ``python -m collectors.classes [--dry-run]``, run by the daily collection.

Many safety notices name a whole class ("Fluorochinolone", "fluoroquinolones", "フルオロキノロン") and never
the ingredient. For every watched ingredient with an ATC code, its level-4 group (the first five characters:
levofloxacin J01MA12 → J01MA, Fluoroquinolones) becomes a drug class, and the class words are searched in
each regulator's own language. A class word only matches in its own language, and a notice that names only
the class is history-free news for the daily digest, never an immediate message (``collectors/run.py``).

The level-3 class above the group (the first four characters: J01M, Quinolone antibacterials) is made and
linked too, as the ingredient's *parent* class, but its words are NOT searched until an administrator has read
them and switched it on (ingredient_class.enabled, migration 0049): a wide class's words from Wikidata carry
noise ("girase inhibitors"), and each English word costs a 12-month look-back on PubMed and PubMed Central.

Where the words come from:
  1. WHO's ATC index names the group in English (atcddd.fhi.no, the class's name in the app).
  2. Wikidata: the item whose ATC code (P267) is the group, its labels and aliases in the 15 languages.
  3. No item carries that code (M01AC Oxicams has none): a Wikidata search for WHO's name among drug
     classes (P31 = Q2585617), accepted only when the item's English label or alias IS that name.
  4. Nothing found: WHO's English name alone when it is a usable word, else a class with no words that an
     administrator fills in on the Ingredients page.
Junk is dropped (codes, digits, punctuation, phrases), a plural is cut back to the stem that finds singular
and plural alike, and a word another word of the same language already finds is dropped. Japanese, Korean
and Chinese words match anywhere in the text; a short capital acronym only as a whole word.

An existing class (same code) is never changed, whoever made it: an ingredient is only linked to it. A new
class's words are due for the check of the past (``collectors/rematch.py``) like any new word.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from collectors.core.context import ParseError
from collectors.matching import Matcher, Term, norm

log = logging.getLogger("collectors.classes")

LANGS = ("en", "de", "fr", "it", "es", "pt", "nl", "da", "nb", "sv", "fi", "is", "ja", "ko", "ar")
WHO_URL = "https://atcddd.fhi.no/atc_ddd_index/"
SPARQL_URL = "https://query.wikidata.org/sparql"
API_URL = "https://www.wikidata.org/w/api.php"
DRUG_CLASS_QID = "Q2585617"
UA = f"PHAROS/1.0 (pharmacovigilance screening aid; {os.environ.get('CONTACT_EMAIL') or 'pharos@satopharma.com'})"

_LEVEL4 = re.compile(r"^[A-Z]\d{2}[A-Z]{2}$")
_LEVEL3 = re.compile(r"^[A-Z]\d{2}[A-Z]$")
_QID = re.compile(r"^Q\d+$")
_CJK = ("ja", "ko", "zh")
_JUNK_CHARS = set("()[]{}:;/\\,\"!?=+*&%$#@|<>_~^`")
# Plural endings cut from the LAST word of a Latin-script word, longest first. Stem matching then finds
# the singular and the plural alike (the stem takes up to 6 more letters).
_PLURAL: dict[str, tuple[str, ...]] = {
    "en": ("s",), "fr": ("s",), "es": ("s",), "pt": ("s",),
    "it": ("i", "e", "o", "a"),
    "de": ("en", "um", "e"),
    "nl": ("en", "s"),
    "sv": ("erna", "er"), "da": ("erne", "er"), "nb": ("ene", "er"),
    "fi": ("it", "i"),
}
_MIN_STEM = 4
# A German compound with a generic head ("Fluorchinolonantibiotikum") also gives its class part
# ("Fluorchinolon"), which is what notices write: "Fluorchinolone", "fluorchinolonhaltige Arzneimittel".
_DE_HEADS = ("antibiotikum", "antibiotika", "arzneimittel", "präparate", "präparat", "medikamente", "wirkstoffe")
# WHO group names that are no class word: "Other quinolones", "Combinations of …", "Various …".
_WHO_NOT_A_WORD = re.compile(r"^(other|others|various|combinations?|plain|comb\.?)\b| and | with | in comb",
                             re.IGNORECASE)

Fetch = Callable[[str, dict], bytes]


def level4(atc: str | None) -> str | None:
    """J01MA12 → J01MA; None when the code is too short to have a level-4 group."""
    code = (atc or "").strip().upper()[:5]
    return code if _LEVEL4.match(code) else None


def level3(atc: str | None) -> str | None:
    """J01MA12 → J01M, the class above the group; None when the code is too short."""
    code = (atc or "").strip().upper()[:4]
    return code if _LEVEL3.match(code) else None


def sentence_case(name: str) -> str:
    """WHO writes a level-3 class in capitals ("QUINOLONE ANTIBACTERIALS"); the app writes it as a name."""
    return name[:1] + name[1:].lower() if name and not any(ch.islower() for ch in name) else name


# ───────────────────────────── the words ─────────────────────────────

def usable(value: str, lang: str) -> bool:
    """A class word: no digits or punctuation, 4 to 50 characters (2 for Japanese, Korean, Chinese), at most
    four words."""
    v = " ".join((value or "").split())
    if not v or any(ch.isdigit() for ch in v) or any(ch in _JUNK_CHARS for ch in v):
        return False
    low = 2 if lang in _CJK else 4
    return low <= len(v) <= 50 and len(v.split(" ")) <= 4


def _acronym(value: str) -> bool:
    return bool(re.fullmatch(r"[A-ZÀ-Þ]{2,6}", value))


def mode_for(value: str, lang: str) -> str:
    if lang in _CJK:
        return "substring"
    if _acronym(value):
        return "exact"
    return "stem"


def stem(value: str, lang: str) -> str:
    """Cut the plural ending of the last word so that one stem finds singular and plural."""
    v = " ".join(value.split())
    if lang not in _PLURAL or _acronym(v) or not re.search(r"[A-Za-zÀ-ɏ]$", v):
        return v
    head, _, last = v.rpartition(" ")
    for suffix in _PLURAL[lang]:
        if last.lower().endswith(suffix) and not (suffix == "s" and last.lower().endswith("ss")):
            cut = last[: len(last) - len(suffix)]
            if len(cut) >= _MIN_STEM:
                return f"{head} {cut}" if head else cut
            break
    return v


@dataclass
class Label:
    lang: str
    kind: str        # label | alt | who
    value: str


def class_words(labels: list[Label]) -> list[dict]:
    """The class words for these labels: junk dropped, plurals cut, and a word another word of the same
    language already finds dropped. Main labels go before aliases, shorter before longer."""
    order = {"label": 0, "who": 1, "alt": 2}
    cands: list[tuple[int, int, str, str, str]] = []
    for lab in labels:
        lang = lab.lang.lower()
        if lang not in LANGS or not usable(lab.value, lang):
            continue
        mode = mode_for(lab.value.strip(), lang)
        word = stem(lab.value, lang) if mode == "stem" else " ".join(lab.value.split())
        cands.append((order.get(lab.kind, 3), len(norm(word)), lang, word, mode))
        if lang == "de" and mode == "stem":
            head, _, last = " ".join(lab.value.split()).rpartition(" ")
            for h in _DE_HEADS:
                part = last[: len(last) - len(h)].rstrip("-")
                if last.lower().endswith(h) and len(part) >= 6:
                    part = stem(f"{head} {part}" if head else part, lang)
                    cands.append((order.get(lab.kind, 3), len(norm(part)), lang, part, mode))
                    break
    kept: list[dict] = []
    for _rank, _n, lang, word, mode in sorted(cands, key=lambda c: (c[2], c[1], c[0])):
        same = [Term(id=str(k), term=t["term"], lang=t["lang"], mode=t["mode"], class_id="c", kind="class")
                for k, t in enumerate(kept) if t["lang"] == lang]
        if any(norm(t.term) == norm(word) for t in same):
            continue
        if same and any(h.start == 0 and h.end == len(word) for h in Matcher(same).match_text(word, "title", lang=lang)):
            continue
        source = "who" if _rank == 1 else "wikidata"
        kept.append({"lang": lang, "term": word, "mode": mode, "source": source})
    return sorted(kept, key=lambda t: (LANGS.index(t["lang"]), norm(t["term"])))


# ───────────────────────────── the sources ─────────────────────────────

def who_name(fetch: Fetch, code: str) -> str | None:
    """WHO's English name of an ATC group, or None when WHO does not know the code."""
    raw = fetch(WHO_URL, {"code": code, "showdescription": "no"})
    page = raw.decode("iso-8859-1")
    rows = re.findall(r"(?<![A-Z0-9])([A-Z][0-9A-Z]{0,6}) <b><a href=\"[^\"]*\">([^<]+)</a></b>", page)
    if not rows:
        raise ParseError("the WHO ATC index page changed shape: no group lines")
    for found, name in rows:
        if found == code:
            return " ".join(html.unescape(name).split())
    return None


def _labels_query(where: str) -> str:
    langs = ", ".join(f'"{x}"' for x in LANGS)
    return ("SELECT ?item ?kind ?val WHERE { " + where + " "
            '{ ?item rdfs:label ?val . BIND("label" AS ?kind) } UNION '
            '{ ?item skos:altLabel ?val . BIND("alt" AS ?kind) } '
            f"FILTER(LANG(?val) IN ({langs})) }}")


def query_by_atc(code: str) -> str:
    if not (_LEVEL4.match(code) or _LEVEL3.match(code)):
        raise ValueError(f"not an ATC level-3 or level-4 code: {code!r}")
    return _labels_query(f'?item wdt:P267 "{code}" .')


def query_by_items(qids: list[str]) -> str:
    if not qids or not all(_QID.match(q) for q in qids):
        raise ValueError(f"not Wikidata ids: {qids!r}")
    return _labels_query("VALUES ?item { " + " ".join(f"wd:{q}" for q in qids) + " }")


def _sparql(fetch: Fetch, query: str) -> dict[str, list[Label]]:
    data = json.loads(fetch(SPARQL_URL, {"query": query, "format": "json"}))
    try:
        bindings = data["results"]["bindings"]
    except (KeyError, TypeError) as exc:
        raise ParseError(f"Wikidata answered without results: {exc}") from exc
    out: dict[str, list[Label]] = {}
    for b in bindings:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        out.setdefault(qid, []).append(Label(b["val"].get("xml:lang", ""), b["kind"]["value"], b["val"]["value"]))
    return out


def search_drug_class(fetch: Fetch, name: str) -> list[str]:
    params = {"action": "query", "list": "search", "srsearch": f"{name} haswbstatement:P31={DRUG_CLASS_QID}",
              "srlimit": "5", "format": "json"}
    data = json.loads(fetch(API_URL, params))
    try:
        hits = data["query"]["search"]
    except (KeyError, TypeError) as exc:
        raise ParseError(f"the Wikidata search answered without results: {exc}") from exc
    return [h["title"] for h in hits if _QID.match(h.get("title", ""))]


def _same_name(a: str, b: str) -> bool:
    return norm(stem(a, "en")) == norm(stem(b, "en"))


@dataclass
class BuiltClass:
    code: str
    name_en: str
    wikidata_qid: str | None
    terms: list[dict] = field(default_factory=list)
    how: str = ""


def build_class(fetch: Fetch, code: str) -> BuiltClass:
    """Name and words of the ATC group ``code``. Network and changed-page errors propagate: the
    ingredient is simply tried again on the next daily run."""
    name = sentence_case(who_name(fetch, code) or "") or None
    found = _sparql(fetch, query_by_atc(code))
    how = "the ATC code on Wikidata"
    if not found and name:
        candidates = search_drug_class(fetch, name)
        if candidates:
            labels = _sparql(fetch, query_by_items(candidates))
            for qid in candidates:
                english = [lab.value for lab in labels.get(qid, []) if lab.lang == "en"]
                if any(_same_name(e, name) for e in english):
                    found = {qid: labels[qid]}
                    how = f"the Wikidata drug class named {name}"
                    break
    qid = next(iter(found), None)
    labels = [lab for labs in found.values() for lab in labs]
    if name and usable(name, "en") and not _WHO_NOT_A_WORD.search(name):
        labels.append(Label("en", "who", name))
    if not found:
        how = "WHO's English name only" if labels else "no words found"
    if not name:
        english = sorted((lab.value for lab in labels if lab.lang == "en" and lab.kind == "label"), key=len)
        name = english[0][:1].upper() + english[0][1:] if english else code
    return BuiltClass(code=code, name_en=name, wikidata_qid=qid, terms=class_words(labels), how=how)


# ───────────────────────────── the run ─────────────────────────────

@dataclass
class Summary:
    created: list[str] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def run(store: Any, fetch: Fetch, *, dry_run: bool = False) -> Summary:
    """Each watched ingredient's group (level 4, searched) and parent class (level 3, shown but not searched
    until an administrator switches it on). An ingredient already linked to a code is left as it is."""
    out = Summary()
    made: dict[str, str | None] = {}
    for ing in store.ingredients_for_classes():
        have = ing.get("class_codes") or []
        for code, relation in ((level4(ing.get("atc_code")), "group"), (level3(ing.get("atc_code")), "parent")):
            if not code or code in have:
                continue
            if code not in made:
                made[code] = store.drug_class_id(code)
                if made[code] is None:
                    try:
                        built = build_class(fetch, code)
                    except Exception as exc:  # one class failing never stops the others; tried again tomorrow
                        log.warning("%s (%s): the class could not be made: %s", ing["inn_en"], code, exc)
                        out.failed.append(f"{ing['inn_en']} ({code})")
                        continue
                    log.info("%s %s: %d words in %d languages, from %s", code, built.name_en, len(built.terms),
                             len({t["lang"] for t in built.terms}), built.how)
                    for t in built.terms:
                        log.info("  %s  %s  (%s)", t["lang"], t["term"], t["mode"])
                    out.created.append(f"{code} {built.name_en}")
                    made[code] = "dry-run" if dry_run else store.create_drug_class(
                        code=code, name_en=built.name_en, wikidata_qid=built.wikidata_qid, terms=built.terms)
            class_id = made[code]
            if class_id is None:
                continue
            searched = relation == "group"
            if not dry_run:
                store.link_ingredient_class(ing["id"], class_id, relation=relation, enabled=searched)
            out.linked.append(f"{ing['inn_en']} → {code}" + ("" if searched else " (off)"))
    return out


def http_fetch(min_gap_s: float = 1.0) -> Fetch:
    """GET with the PHAROS user agent, one request per host at a time, at least ``min_gap_s`` apart."""
    import httpx

    client = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA})
    last: dict[str, float] = {}

    def fetch(url: str, params: dict) -> bytes:
        host = urlsplit(url).netloc
        wait = last.get(host, 0.0) + min_gap_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            res = client.get(url, params=params,
                             headers={"Accept": "application/sparql-results+json"} if url == SPARQL_URL else None)
        finally:
            last[host] = time.monotonic()
        res.raise_for_status()
        return res.content

    return fetch


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.classes", description=__doc__.split("\n\n")[0])
    p.add_argument("--dry-run", action="store_true", help="look the classes up and print them; write nothing")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from collectors.core.db import Db
    from collectors.core.store import Store

    db = Db()
    try:
        out = run(Store(db), http_fetch(), dry_run=args.dry_run)
    finally:
        db.close()
    log.info("drug classes: %d made, %d ingredients linked, %d could not be made%s", len(out.created),
             len(out.linked), len(out.failed), " (dry run: nothing written)" if args.dry_run else "")
    return 1 if out.failed else 0


if __name__ == "__main__":
    sys.exit(main())
