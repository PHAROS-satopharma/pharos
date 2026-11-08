"""What every free terminology loader shares (migration 0103).

A loader downloads one release, reads it into ``Concept`` records and hands them to ``load()``, which:

  1. skips a release already seen (the same SHA-256);
  2. validates it (codes, names, enough concepts, not too many retired at once);
  3. refuses it when the database would pass ``MAX_DB_BYTES`` (the Supabase free plan stops at 500 MB);
  4. keeps the original write-once in the R2 archive (collectors.core.archive);
  5. applies the first release of a source at once; stages every later one with its differences (term_change),
     which an administrator activates or rejects on the Terminology screen;
  6. tells the administrators on Telegram (Notifier.admin_message) what arrived, or why it was refused.

The run log is public: it names the source, the version and the counts, never the database's own messages.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("collectors.coding.terminology")

MAX_DB_BYTES = 330 * 1024 * 1024      # what the database may reach with a new release; the plan's cap is 500 MB
BYTES_PER_CONCEPT = 900               # the row, its definition and its keys, measured on NCIt (2026-11)
BYTES_PER_NAME = 260                  # the row and its trigram and prefix indexes
MAX_RETIRED_SHARE = 0.2               # a release that retires more than this is a broken file, not a release…
MIN_RETIRED_ALARM = 50                # …once it retires more than a handful (a small source changes by a few)
CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
HEADERS = {"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"}
NAMES = {"ncit": "NCI Thesaurus", "oae": "OAE", "icd11": "ICD-11", "mesh": "MeSH"}


class TerminologyError(Exception):
    """Why a release was not loaded, in words an administrator can act on."""


@dataclass
class Concept:
    code: str
    name: str
    definition: str | None = None
    lang: str = "en"
    names: list[tuple[str, str, bool]] = field(default_factory=list)   # (name, lang, preferred)
    parents: list[str] = field(default_factory=list)
    subsets: list[str] = field(default_factory=list)
    uri: str | None = None

    def snapshot(self) -> dict:
        """The concept as term_change stores it (and as diff() compares it)."""
        return {"name": self.name, "definition": self.definition, "lang": self.lang,
                "subsets": sorted(set(self.subsets)), "uri": self.uri,
                "names": sorted([list(n) for n in self.names], key=lambda n: (not n[2], n[1], n[0])),
                "parents": sorted(set(self.parents))}


@dataclass
class Release:
    source: str
    version: str
    url: str
    data: bytes                     # the original as downloaded: hashed and archived
    concepts: dict[str, Concept]
    mime: str = "application/zip"
    extra: list[tuple[bytes, str]] = field(default_factory=list)   # more originals of the same release (ICD-11 ar)


ARABIC_MARKS = re.compile("[\u0640\u064B-\u065F\u0670]")


def norm(text: str | None) -> str:
    """Words compared as term_norm() compares them (0103): coding_norm(), and Arabic without its vowel marks."""
    from collectors.coding.norm import norm as coding_norm

    return coding_norm(ARABIC_MARKS.sub("", text or ""))


def clean_names(c: Concept) -> None:
    """One name per spelling and language (the database's key), the concept's own name first and preferred."""
    own = (norm(c.name), c.lang)
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, bool]] = []
    for name, lang, preferred in [(c.name, c.lang, True)] + sorted(c.names, key=lambda n: not n[2]):
        name = " ".join((name or "").split())
        key = (norm(name), lang or "en")
        if key[0] and key not in seen:
            seen.add(key)
            # One preferred name a language: the concept's own in its language, the first given in another.
            first_other = bool(preferred) and key[1] != c.lang and not any(o[2] and o[1] == key[1] for o in out)
            out.append((name, key[1], key == own or first_other))
    c.names = out


def validate(source: str, concepts: dict[str, Concept], *, min_concepts: int) -> dict[str, Concept]:
    """The release, checked: every code well formed, every concept named, parents kept only when they are in the
    release (a path never leaves the branch PHAROS keeps). Raises TerminologyError."""
    if len(concepts) < min_concepts:
        raise TerminologyError(f"{NAMES.get(source, source)}: only {len(concepts)} concepts were read, fewer than "
                               f"the {min_concepts} expected. The file may be cut short or its format changed.")
    for code, c in concepts.items():
        if code != c.code or not CODE.match(code):
            raise TerminologyError(f"{NAMES.get(source, source)}: a code is not well formed ({code[:40]!r}).")
        c.name = " ".join((c.name or "").split())
        if not c.name:
            raise TerminologyError(f"{NAMES.get(source, source)}: {code} has no name.")
        c.parents = sorted({p for p in c.parents if p in concepts and p != code})
        c.subsets = sorted({s for s in c.subsets if s})
        if c.definition is not None:
            c.definition = c.definition.strip() or None
        clean_names(c)
    return concepts


def estimate_bytes(concepts: int, names: int) -> int:
    return concepts * BYTES_PER_CONCEPT + names * BYTES_PER_NAME


def current(db: Any, source: str) -> dict[str, dict]:
    """The concepts of ``source`` as loaded now, as snapshots with their status."""
    out: dict[str, dict] = {}
    for r in db.fetchall("select code, name, definition, lang, status, subsets, uri from term_concept "
                         "where source = %s", (source,)):
        out[r["code"]] = {"name": r["name"], "definition": r["definition"], "lang": r["lang"],
                          "subsets": sorted(r["subsets"] or []), "uri": r["uri"], "names": [], "parents": [],
                          "status": r["status"]}
    for r in db.fetchall("select code, name, lang, preferred from term_name where source = %s", (source,)):
        if r["code"] in out:
            out[r["code"]]["names"].append([r["name"], r["lang"], r["preferred"]])
    for r in db.fetchall("select code, parent from term_parent where source = %s", (source,)):
        if r["code"] in out:
            out[r["code"]]["parents"].append(r["parent"])
    for snap in out.values():
        snap["names"].sort(key=lambda n: (not n[2], n[1], n[0]))
        snap["parents"].sort()
    return out


def diff(old: dict[str, dict], new: dict[str, Concept]) -> list[dict]:
    """What the new release changes: added (or back after being retired), changed, retired."""
    changes: list[dict] = []
    for code in sorted(new):
        after = new[code].snapshot()
        before = old.get(code)
        if before is None:
            changes.append({"code": code, "kind": "added", "before": None, "after": after})
        else:
            was = {k: v for k, v in before.items() if k != "status"}
            if before["status"] != "current" or was != after:
                changes.append({"code": code, "kind": "changed", "before": was, "after": after})
    for code in sorted(set(old) - set(new)):
        if old[code]["status"] == "current":
            was = {k: v for k, v in old[code].items() if k != "status"}
            changes.append({"code": code, "kind": "retired", "before": was, "after": None})
    return changes


def database_bytes(db: Any) -> int:
    row = db.fetchone("select pg_database_size(current_database()) as n")
    return int(row["n"]) if row else 0


def _insert_release(db: Any, rel: Release, *, sha: str, key: str | None, status: str, counts: dict,
                    note: str | None = None) -> int:
    row = db.fetchone(
        """insert into term_release (source, version, url, sha256, archive_key, status, concepts, names, added,
                                     changed, retired, activated_at, note)
           values (%(s)s, %(v)s, %(u)s, %(h)s, %(k)s, %(st)s, %(c)s, %(n)s, %(a)s, %(ch)s, %(r)s,
                   case when %(st)s = 'active' then now() end, %(note)s)
           returning id""",
        {"s": rel.source, "v": rel.version, "u": rel.url, "h": sha, "k": key, "st": status,
         "c": counts["concepts"], "n": counts["names"], "a": counts.get("added", 0),
         "ch": counts.get("changed", 0), "r": counts.get("retired", 0), "note": note})
    return int(row["id"])


def apply_first(db: Any, rel: Release, *, sha: str, key: str | None) -> dict[str, int]:
    """The first release of a source, written at once in one transaction."""
    names = sum(len(c.names) for c in rel.concepts.values())
    counts = {"concepts": len(rel.concepts), "names": names, "added": len(rel.concepts)}
    with db.transaction():
        rid = _insert_release(db, rel, sha=sha, key=key, status="active", counts=counts,
                              note="The first release of this source, applied when it was loaded.")
        with db.conn.cursor() as cur:
            with cur.copy("copy term_concept (source, code, name, definition, lang, status, first_release, subsets, "
                          "uri) from stdin") as cp:
                for c in rel.concepts.values():
                    cp.write_row((rel.source, c.code, c.name, c.definition, c.lang, "current", rid, c.subsets, c.uri))
            with cur.copy("copy term_name (source, code, name, lang, preferred) from stdin") as cp:
                for c in rel.concepts.values():
                    for name, lang, preferred in c.names:
                        cp.write_row((rel.source, c.code, name, lang, preferred))
            with cur.copy("copy term_parent (source, code, parent) from stdin") as cp:
                for c in rel.concepts.values():
                    for p in c.parents:
                        cp.write_row((rel.source, c.code, p))
    return counts


def stage(db: Any, rel: Release, changes: list[dict], *, sha: str, key: str | None) -> tuple[int, dict]:
    """A later release, kept with its differences for review; an older release still waiting gives way to it."""
    from collectors.core.db import jsonb

    kinds = {k: sum(1 for c in changes if c["kind"] == k) for k in ("added", "changed", "retired")}
    counts = {"concepts": len(rel.concepts), "names": sum(len(c.names) for c in rel.concepts.values()), **kinds}
    with db.transaction():
        db.execute("""update term_release set status = 'rejected', rejected_at = now(),
                             note = 'A newer release arrived before this one was reviewed.'
                       where source = %s and status = 'staged'""", (rel.source,))
        if not changes:
            # Nothing would change: the release is recorded as the active one without a review.
            db.execute("update term_release set status = 'superseded' where source = %s and status = 'active'",
                       (rel.source,))
            rid = _insert_release(db, rel, sha=sha, key=key, status="active", counts=counts,
                                  note="No differences from the release before; activated by the loader.")
            return rid, counts
        rid = _insert_release(db, rel, sha=sha, key=key, status="staged", counts=counts)
        with db.conn.cursor() as cur:
            with cur.copy("copy term_change (release, source, code, kind, before, after) from stdin") as cp:
                for c in changes:
                    cp.write_row((rid, rel.source, c["code"], c["kind"],
                                  None if c["before"] is None else jsonb(c["before"]),
                                  None if c["after"] is None else jsonb(c["after"])))
    return rid, counts


def default_notify(db: Any) -> Callable[[str], None]:
    def send(text: str) -> None:
        from collectors.alerts import Notifier
        from collectors.core.store import Store

        store = Store(db)
        Notifier(store, store.settings()).admin_message(text)
    return send


def _tell(notify: Callable[[str], None] | None, text: str) -> None:
    if notify is None:
        return
    try:
        notify(text)
    except Exception as exc:   # the load stands; only the message is lost
        log.warning("the administrators could not be told (%s)", type(exc).__name__)


def load(db: Any, rel: Release, *, min_concepts: int, archive: Any = None,
         notify: Callable[[str], None] | None = None, max_bytes: int = MAX_DB_BYTES) -> str:
    """Load one release; what was done, in words. Raises TerminologyError (after telling the administrators)."""
    from collectors.core.archive import sha256_hex

    label = f"{NAMES.get(rel.source, rel.source)} {rel.version}"
    sha = sha256_hex(rel.data + b"".join(body for body, _ in rel.extra))
    seen = db.fetchone("select version, status from term_release where source = %s and sha256 = %s",
                       (rel.source, sha))
    if seen:
        return f"{NAMES.get(rel.source, rel.source)} {seen['version']} was seen already ({seen['status']})"
    if db.fetchone("select 1 from term_release where source = %s and version = %s", (rel.source, rel.version)):
        rel.version = f"{rel.version} ({sha[:8]})"      # the publisher changed the file without a new version
        label = f"{NAMES.get(rel.source, rel.source)} {rel.version}"
    try:
        concepts = validate(rel.source, rel.concepts, min_concepts=min_concepts)
        first = db.fetchone("select 1 from term_release where source = %s and status = 'active'",
                            (rel.source,)) is None
        changes: list[dict] = []
        if first:
            need = estimate_bytes(len(concepts), sum(len(c.names) for c in concepts.values()))
        else:
            old = current(db, rel.source)
            changes = diff(old, concepts)
            retired = sum(1 for c in changes if c["kind"] == "retired")
            live = sum(1 for s in old.values() if s["status"] == "current")
            if retired > MIN_RETIRED_ALARM and retired > MAX_RETIRED_SHARE * live:
                raise TerminologyError(f"{label} would retire {retired} of {live} concepts. That is a broken or "
                                       "different file, not a release: nothing was loaded.")
            # Staged changes are stored twice (the review copy, then the applied rows).
            need = estimate_bytes(len(changes) * 2,
                                  sum(len((c["after"] or {}).get("names", [])) for c in changes) * 2)
        size = database_bytes(db)
        if size + need > max_bytes:
            raise TerminologyError(f"{label} needs about {need // 2**20} MB and the database holds "
                                   f"{size // 2**20} MB: past the {max_bytes // 2**20} MB PHAROS allows itself. "
                                   "Nothing was loaded.")
    except TerminologyError as exc:
        _tell(notify, f"Terminology: {exc}")
        raise
    key = None
    if archive is not None:
        _, key = archive.put(rel.data, rel.mime, meta={"source": rel.source, "version": rel.version,
                                                     "url": rel.url})
        for body, mime in rel.extra:
            archive.put(body, mime, meta={"source": rel.source, "version": rel.version, "url": rel.url})
    if first:
        counts = apply_first(db, rel, sha=sha, key=key)
        db.execute("analyze term_concept, term_name, term_parent")   # else the search plans for empty tables
        said = f"{label}: {counts['concepts']} concepts, {counts['names']} names, loaded (the first release)"
        _tell(notify, f"Terminology: {said}.")
        return said
    rid, counts = stage(db, rel, changes, sha=sha, key=key)
    if not changes:
        return f"{label}: no differences from the release before; recorded as active"
    said = (f"{label}: {counts['added']} added, {counts['changed']} changed, {counts['retired']} retired, "
            "waiting for an administrator's review")
    _tell(notify, f"Terminology: {said} on the Terminology screen (release {rid}).")
    return said


def fetch(url: str, *, timeout: float = 300) -> tuple[bytes, dict[str, str]]:
    """One download: its bytes and headers. Refuses anything but HTTP 200."""
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=True, headers=HEADERS) as client:
        res = client.get(url)
    if res.status_code != 200:
        raise TerminologyError(f"{url} answered HTTP {res.status_code}")
    return res.content, dict(res.headers)
