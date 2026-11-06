"""Products: the watched ingredient a product names (its brands and names on the watchlist), else RxNorm.

RxNorm is looked up on RxNav, the National Library of Medicine's free service (no licence; at most 20 requests a
second; NLM is named as the source and never as endorsing PHAROS). Each suggestion is at the ingredient level
(RxNorm IN, or MIN for a combination) with the ingredients' UNII codes (FDA's substance identifiers).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from collectors.coding.norm import norm

log = logging.getLogger("collectors.coding.drugs")

RXNAV = "https://rxnav.nlm.nih.gov/REST"
HEADERS = {"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"}


def _words(text: str) -> str:
    return " " + norm(text) + " "


def watchlist(db: Any) -> list[dict]:
    """The active ingredients with every name they are known by (brands included) and their RxNorm code."""
    rows = db.fetchall(
        """select i.id::text as id, i.inn_en, i.rxcui,
                  coalesce(array_agg(distinct t.term) filter (where t.term is not null), '{}') as terms
             from ingredient i
             left join ingredient_term t on t.ingredient_id = i.id
            where i.active
            group by i.id, i.inn_en, i.rxcui
            order by i.inn_en""")
    return [{"id": r["id"], "inn_en": r["inn_en"], "rxcui": r["rxcui"],
             "names": sorted({norm(r["inn_en"]), *[norm(t) for t in r["terms"] if t]} - {""})} for r in rows]


def on_watchlist(text: str, ingredients: list[dict]) -> list[dict]:
    """The watched ingredients whose name or brand appears, as whole words, in ``text``."""
    said = _words(text)
    hits = []
    for ing in ingredients:
        name = next((n for n in ing["names"] if f" {n} " in said), None)
        if name:
            hits.append({**ing, "matched": name})
    return hits


class RxNav:
    """A small RxNav client that remembers what it was told for the run."""

    def __init__(self, get: Any = None) -> None:
        if get is None:
            import httpx

            client = httpx.Client(timeout=20, headers=HEADERS)
            get = client.get
        self._get = get
        self._memo: dict[str, Any] = {}

    def _json(self, path: str, **params: Any) -> dict:
        key = path + repr(sorted(params.items()))
        if key not in self._memo:
            res = self._get(f"{RXNAV}{path}", params=params)
            res.raise_for_status()
            self._memo[key] = res.json() or {}
        return self._memo[key]

    def approximate(self, text: str, n: int = 4) -> list[str]:
        """RxNorm codes closest to ``text`` (RxNorm's own concepts only), best first."""
        got = self._json("/approximateTerm.json", term=text[:200], maxEntries=n)
        out: list[str] = []
        for c in (got.get("approximateGroup") or {}).get("candidate") or []:
            if c.get("source") in (None, "RXNORM") and c.get("rxcui") and c["rxcui"] not in out:
                out.append(c["rxcui"])
        return out

    def by_name(self, name: str) -> list[str]:
        """RxNorm codes whose name is ``name`` (normalised: case, spaces, salt words), at most three."""
        got = self._json("/rxcui.json", name=name[:200], search=2)
        return list(((got.get("idGroup") or {}).get("rxnormId") or [])[:3])

    def ingredients(self, rxcui: str) -> list[dict]:
        """The ingredient-level concepts (IN, MIN) of an RxNorm code; the code itself when it is one."""
        got = self._json(f"/rxcui/{rxcui}/related.json", tty="IN MIN")
        out = []
        for group in (got.get("relatedGroup") or {}).get("conceptGroup") or []:
            for p in group.get("conceptProperties") or []:
                out.append({"rxcui": p["rxcui"], "name": p["name"], "tty": p.get("tty") or group.get("tty")})
        return out

    def unii(self, rxcui: str) -> str | None:
        got = self._json(f"/rxcui/{rxcui}/property.json", propName="UNII_CODE")
        for p in (got.get("propConceptGroup") or {}).get("propConcept") or []:
            if p.get("propName") == "UNII_CODE" and re.fullmatch(r"[0-9A-Z]{10}", p.get("propValue") or ""):
                return p["propValue"]
        return None

    def name(self, rxcui: str) -> str | None:
        got = self._json(f"/rxcui/{rxcui}/properties.json")
        return (got.get("properties") or {}).get("name")


def _suggestion(rx: RxNav, concept: dict, came_from: str, reason: str) -> dict:
    """One suggestion at the ingredient level: a MIN (combination) lists its ingredients."""
    parts = [concept]
    if concept.get("tty") == "MIN":
        parts = [p for p in rx.ingredients(concept["rxcui"]) if p.get("tty") == "IN"] or [concept]
    return {"rxcui": concept["rxcui"], "name": concept["name"], "tty": concept.get("tty") or "IN",
            "ingredients": [{"rxcui": p["rxcui"], "name": p["name"], "unii": rx.unii(p["rxcui"])} for p in parts],
            "from": came_from, "reason": reason}


def suggest(product: dict, ingredients: list[dict], rx: RxNav | None,
            memory: list[dict] | None = None) -> list[dict]:
    """Suggestions for one product of the form: what the team chose before, the watched ingredient it names,
    then RxNorm's closest ingredients. Never more than four."""
    name = product.get("name") or ""
    active = product.get("active_ingredient") or ""
    out: list[dict] = []
    for m in memory or []:
        out.append({"rxcui": m["code"], "name": m["label"], "tty": "IN", "ingredients": [], "from": "memory",
                    "reason": f"Chosen for these words in {m['cases']} confirmed case(s)."})
    for ing in on_watchlist(f"{name} {active}", ingredients):
        reason = f"“{ing['matched']}” is a name of {ing['inn_en']} on the watchlist."
        if ing.get("rxcui") and rx is not None:
            try:
                found = _suggestion(rx, {"rxcui": ing["rxcui"], "name": ing["inn_en"].lower(), "tty": "IN"},
                                    "watchlist", reason)
                out.append({**found, "ingredient_id": ing["id"]})
                continue
            except Exception as exc:  # noqa: BLE001 - RxNav away: the watchlist alone still answers
                log.info("RxNav: %s", type(exc).__name__)
        out.append({"rxcui": ing.get("rxcui") or "", "name": ing["inn_en"].lower(), "tty": "IN", "ingredients": [],
                    "from": "watchlist", "reason": reason, "ingredient_id": ing["id"]})
    if rx is not None and (active or name):
        try:
            for text in [t for t in (active, name) if t]:
                for code in rx.approximate(text):
                    for concept in rx.ingredients(code):
                        if concept.get("tty") in ("IN", "MIN"):
                            out.append(_suggestion(rx, concept, "rxnorm", f"RxNorm's closest match to “{text}”."))
                if len(out) >= 4:
                    break
        except Exception as exc:  # noqa: BLE001 - one product's lookup never stops the case
            log.info("RxNav: %s", type(exc).__name__)
    seen: set[str] = set()
    unique = []
    for s in out:
        key = s["rxcui"] or s["name"]
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:4]
