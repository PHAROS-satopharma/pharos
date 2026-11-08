"""WHO ICD-11 for Mortality and Morbidity Statistics (MMS), English and Arabic, stored exactly as WHO publishes it
(migration 0103).

WHO publishes each release's simple tabulation once a year at
``https://icdcdn.who.int/static/releasefiles/<YYYY>-01/SimpleTabulation-ICD-11-MMS-<lang>.zip``; the newest is
found by asking for next January's folder, then this one's, and so on back. Inside is a tab-separated text file:

    Foundation URI  Linearization URI  Code  BlockId  Title  ClassKind  DepthInKind  IsResidual  ChapterNo  …  Parent

(the Arabic file has TitleEN before Title). A coding note may run over several lines; a record starts with a
Foundation URI. Each chapter, block and category is kept under its code (a category), its BlockId (a block; WHO's
entity number for a block that has none) or its chapter number, with the title (the leading "- - " that shows the depth taken off), its URI and its parent.

ICD-11 is WHO's, licensed CC BY-ND 3.0 IGO: no title is changed, translated or merged, and ICD-11 is never compared
with another source (term_source.maps is false for it).
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from datetime import date
from typing import Any, Callable

from collectors.coding.terminology.base import Concept, Release, TerminologyError, fetch, load

log = logging.getLogger("collectors.coding.terminology.icd11")

URL = "https://icdcdn.who.int/static/releasefiles/{folder}/SimpleTabulation-ICD-11-MMS-{lang}.zip"
LANGS = ("en", "ar")
MIN_CONCEPTS = 30000                # 37,052 rows in the 2026-01 release
ENTITY = "http://id.who.int/icd/entity/"
DEPTH = re.compile(r"^(?:-\s)+")


def text_of(data: bytes, lang: str) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise TerminologyError(f"ICD-11 ({lang}): the download is not a zip that opens.") from exc
    with zf:
        names = [n for n in zf.namelist() if n.lower().endswith(f"-mms-{lang}.txt")]
        if not names:
            raise TerminologyError(f"ICD-11 ({lang}): the zip has no SimpleTabulation text file.")
        return zf.read(names[0]).decode("utf-8-sig")


def records(text: str) -> list[dict[str, str]]:
    """The rows by column name; a line that does not start with a Foundation URI continues the row before."""
    lines = text.splitlines()
    if not lines:
        raise TerminologyError("ICD-11: the text file is empty.")
    header = [h.strip().lstrip("\ufeff") for h in lines[0].split("\t")]
    joined: list[str] = []
    for line in lines[1:]:
        if line.startswith(ENTITY) or not joined:
            joined.append(line)
        else:
            joined[-1] += " " + line       # a coding note over several lines (not kept)
    out = []
    for row in csv.reader(joined, delimiter="\t", quotechar='"'):
        if row and row[0].startswith(ENTITY):
            out.append({h: (row[i] if i < len(row) else "") for i, h in enumerate(header)})
    if not out or "Linearization URI" not in header or "Title" not in header:
        raise TerminologyError("ICD-11: the text file does not have the columns of a simple tabulation.")
    return out


def title(text: str) -> str:
    return DEPTH.sub("", " ".join((text or "").split()))


def code_for(r: dict[str, str]) -> str:
    """A category's code, a block's BlockId, a chapter's number; a block without a BlockId (chapters V and X)
    goes by WHO's own entity number, the last part of its URI."""
    code = (r.get("Code") or r.get("BlockId") or "").strip()
    if code:
        return code
    if (r.get("ClassKind") or "").strip() == "chapter":
        return (r.get("ChapterNo") or "").strip()
    return (r.get("Linearization URI") or "").rstrip("/").rsplit("/", 1)[-1].strip()


def parse(en: str, ar: str | None = None) -> dict[str, Concept]:
    rows = records(en)
    arabic = {r["Linearization URI"]: title(r.get("Title", "")) for r in records(ar)} if ar else {}
    code_of: dict[str, str] = {}
    for r in rows:
        r["_code"] = code_for(r)
        if r["_code"] and r.get("IsResidual", "").lower() != "true":
            code_of.setdefault(r["Foundation URI"], r["_code"])
    out: dict[str, Concept] = {}
    for r in rows:
        code, name = r["_code"], title(r.get("Title", ""))
        if not code or not name or code in out:
            continue
        names = [(name, "en", True)]
        if arabic.get(r["Linearization URI"]):
            names.append((arabic[r["Linearization URI"]], "ar", True))
        parent = code_of.get((r.get("Parent") or "").strip())
        out[code] = Concept(code=code, name=name, names=names, parents=[parent] if parent else [],
                            subsets=[k for k in [(r.get("ClassKind") or "").strip()] if k],
                            uri=(r.get("Linearization URI") or "").strip() or None)
    return out


def newest(get: Callable[[str], tuple[bytes, dict]], today: date | None = None) -> tuple[str, dict[str, bytes]]:
    """The newest release folder WHO serves, with its English and Arabic zips."""
    year = (today or date.today()).year + 1
    for y in range(year, year - 4, -1):
        folder = f"{y}-01"
        try:
            files = {lang: get(URL.format(folder=folder, lang=lang))[0] for lang in LANGS}
        except TerminologyError:
            log.info("ICD-11 %s: not served", folder)
            continue
        return folder, files
    raise TerminologyError("WHO serves no ICD-11 simple tabulation of the last three years.")


def release(folder: str, files: dict[str, bytes]) -> Release:
    concepts = parse(text_of(files["en"], "en"), text_of(files["ar"], "ar") if "ar" in files else None)
    url = URL.format(folder=folder, lang="en")
    extra = [(files["ar"], "application/zip")] if "ar" in files else []
    return Release(source="icd11", version=folder, url=url, data=files["en"], concepts=concepts, extra=extra)


def run(db: Any, *, data: bytes | None = None, archive: Any = None,
        notify: Callable[[str], None] | None = None, get: Callable[[str], tuple[bytes, dict]] = fetch) -> str:
    if data is not None:
        # A saved English zip loaded by hand: its release folder is the date of the file inside.
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            y, m = zf.infolist()[0].date_time[:2]
        folder, files = f"{y:04d}-01", {"en": data}
    else:
        folder, files = newest(get)
    return load(db, release(folder, files), min_concepts=MIN_CONCEPTS, archive=archive, notify=notify)
