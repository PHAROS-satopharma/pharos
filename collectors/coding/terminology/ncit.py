"""The NCI Thesaurus: its adverse-event and disease/finding branches, and every CTCAE term (migration 0103).

NCI EVS publishes the whole thesaurus as ``Thesaurus.FLAT.zip`` (about 17 MB; one ``Thesaurus.txt`` inside, 90 MB),
refreshed each month. Each line has nine tab-separated columns:

    code  <IRI>  parents (|)  synonyms (| the first is the preferred name)  definition  display name
    concept status  semantic type  subsets (|)

PHAROS keeps the descendants of C41331 (Adverse Event) and C7057 (Disease, Disorder or Finding), and every concept
in a CTCAE subset (the terms and their grades), about 51,000 concepts and 130,000 names. A Retired or Obsolete
concept is left out (a code that was loaded before is then marked retired, never deleted).

The NCI Thesaurus is free to use with credit to NCI (its terms of use), and NCI does not endorse PHAROS.
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections import defaultdict
from typing import Any, Callable

from collectors.coding.terminology.base import Concept, Release, TerminologyError, fetch, load

log = logging.getLogger("collectors.coding.terminology.ncit")

URL = "https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/Thesaurus.FLAT.zip"
ROOTS = ("C41331", "C7057")         # Adverse Event; Disease, Disorder or Finding
SKIP_STATUS = ("Retired", "Obsolete")
MIN_CONCEPTS = 20000                # the slice kept was 51,230 concepts in October 2026
MAX_TEXT = 400 * 1024 * 1024


def text_of(data: bytes) -> tuple[str, str | None]:
    """Thesaurus.txt from the zip (or the text itself), and the date of the file inside the zip."""
    if data[:2] != b"PK":
        return data.decode("utf-8"), None
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise TerminologyError("NCI Thesaurus: the download is not a zip that opens.") from exc
    with zf:
        infos = [i for i in zf.infolist() if i.filename.rsplit("/", 1)[-1].lower() == "thesaurus.txt"]
        if not infos:
            raise TerminologyError("NCI Thesaurus: the zip has no Thesaurus.txt.")
        if infos[0].file_size > MAX_TEXT:
            raise TerminologyError("NCI Thesaurus: Thesaurus.txt is far larger than it has ever been.")
        y, m, d = infos[0].date_time[:3]
        return zf.read(infos[0]).decode("utf-8"), f"{y:04d}-{m:02d}-{d:02d}"


def parse(text: str) -> dict[str, Concept]:
    """The concepts PHAROS keeps, by code."""
    rows: dict[str, list[str]] = {}
    children: dict[str, list[str]] = defaultdict(list)
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 9 or not f[0]:
            continue
        rows[f[0]] = f
        for p in f[2].split("|"):
            if p:
                children[p].append(f[0])
    if not all(r in rows for r in ROOTS):
        raise TerminologyError("NCI Thesaurus: the Adverse Event or the Disease, Disorder or Finding branch is "
                               "missing; the file's format may have changed.")
    keep: set[str] = set()
    stack = list(ROOTS)
    while stack:
        code = stack.pop()
        if code not in keep:
            keep.add(code)
            stack.extend(children.get(code, ()))
    keep |= {code for code, f in rows.items() if "CTCAE" in f[8]}

    out: dict[str, Concept] = {}
    for code in sorted(keep):
        f = rows.get(code)
        if f is None or any(s in f[6] for s in SKIP_STATUS):
            continue
        synonyms = [s.strip() for s in f[3].split("|") if s.strip()]
        display = f[5].strip()
        name = synonyms[0] if synonyms else display
        if not name:
            continue
        names = [(s, "en", i == 0) for i, s in enumerate(synonyms)]
        if display:
            names.append((display, "en", False))
        out[code] = Concept(code=code, name=name, definition=f[4].strip() or None, names=names,
                            parents=[p for p in f[2].split("|") if p],
                            subsets=[s.strip() for s in f[8].split("|") if s.strip()],
                            uri=f[1].strip().strip("<>") or None)
    return out


def release(data: bytes, *, url: str = URL, last_modified: str | None = None) -> Release:
    text, dated = text_of(data)
    version = dated or (last_modified or "").strip() or "unversioned"
    return Release(source="ncit", version=version, url=url, data=data, concepts=parse(text))


def run(db: Any, *, data: bytes | None = None, archive: Any = None,
        notify: Callable[[str], None] | None = None, get: Callable[[str], tuple[bytes, dict]] = fetch) -> str:
    headers: dict = {}
    if data is None:
        data, headers = get(URL)
    rel = release(data, last_modified=headers.get("last-modified"))
    return load(db, rel, min_concepts=MIN_CONCEPTS, archive=archive, notify=notify)
