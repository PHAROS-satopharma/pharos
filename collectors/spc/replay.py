"""PHAROS — replay a real past revision of a label through the label watch's change detector (dry run).

The proof that the label watch catches a real change: two published versions of one label are read the way
the watch reads them (``dailymed.parse_spl``), compared section by section (``diff.diff_sections``), and the
sections that would alert are named (``sections.watched_changes``). Nothing is written to the database and no
message is sent; ``replay.yml`` runs it from GitHub and puts the result in the run's summary.

* DailyMed: ``getFile.cfm?type=zip&setid=<set id>&version=<n>`` serves every past version as a zip holding the
  SPL XML. (``/services/v2/spls/<set id>.xml?version=<n>`` ignores the version.) A zip that comes back cut short
  (6 Nov 2026: version 31 of Corlanor, the first time) is asked for again, up to ``TRIES`` times.

    python -m collectors.spc.replay dailymed <set id> <from version> <to version>

* Korea nedrug: the change history of a label's precautions (``getItemChangeHistList?itemSeq=…&docType=NB``)
  holds every version's XML in its rows; the two newest are compared, read the way ``nedrug.doc_sections``
  reads the label (Procoralan 5 mg, item 200906066: 23 Sep 2017 against 10 Nov 2017).

    python -m collectors.spc.replay nedrug <item code>
"""

from __future__ import annotations

import io
import os
import sys
import zipfile

from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.spc import nedrug
from collectors.spc.dailymed import parse_spl
from collectors.spc.diff import diff_sections
from collectors.spc.sections import watched_changes

DAILYMED_VERSION = ("https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?type=zip&setid={setid}"
                    "&version={version}")
TRIES = 3


class ReplayError(Exception):
    """A version could not be read."""


def spl_from_zip(content: bytes) -> bytes:
    """The SPL XML inside a DailyMed version zip; ``ReplayError`` for a zip cut short or without one."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".xml")]
            if len(names) != 1:
                raise ReplayError(f"{len(names)} XML files in the zip, expected 1")
            return z.read(names[0])
    except zipfile.BadZipFile as exc:
        raise ReplayError(f"not a whole zip ({exc})") from None


def dailymed_version(ctx, setid: str, version: int | str) -> tuple[dict[str, str], object]:
    url = DAILYMED_VERSION.format(setid=setid, version=version)
    last = "no answer"
    for _ in range(TRIES):
        if hasattr(ctx, "forget"):
            ctx.forget(url)
        f = ctx.get(url, accept="application/zip, */*;q=0.8")
        if f.status != 200:
            last = f"HTTP {f.status}"
            continue
        try:
            return parse_spl(spl_from_zip(f.content))
        except ReplayError as exc:
            last = str(exc)
    raise ReplayError(f"DailyMed {setid} version {version}: {last}")


def compare(before: dict[str, str], after: dict[str, str]) -> dict:
    changes = diff_sections(before, after)
    changed = [c["section"] for c in changes]
    return {"changed": changed, "alerting": watched_changes(changed), "changes": changes}


def replay_dailymed(ctx, setid: str, v_from, v_to) -> dict:
    (a, date_a), (b, date_b) = dailymed_version(ctx, setid, v_from), dailymed_version(ctx, setid, v_to)
    out = compare(a, b)
    out.update(source="DailyMed", label=setid, versions=(str(v_from), str(v_to)), dates=(date_a, date_b))
    return out


def nedrug_versions(text: str) -> list[tuple[str, str]]:
    """``(date, XML)`` of every version in a nedrug change-history page, newest first."""
    import html

    rows = [(day, html.unescape(xml)) for xml, day in nedrug._HIST_ROW.findall(text)]
    return sorted(rows, key=lambda r: r[0], reverse=True)


def replay_nedrug(ctx, seq: str) -> dict:
    url = nedrug.HISTORY.format(seq=seq, doc="NB")
    if hasattr(ctx, "forget"):
        ctx.forget(url)
    f = ctx.get(url)
    if f.status != 200:
        raise ReplayError(f"nedrug {seq} change history: HTTP {f.status}")
    versions = nedrug_versions(f.text)
    if len(versions) < 2:
        raise ReplayError(f"nedrug {seq} change history: {len(versions)} version(s), two are needed")
    (date_b, b), (date_a, a) = versions[0], versions[1]
    out = compare(nedrug.doc_sections(a, "NB"), nedrug.doc_sections(b, "NB"))
    out.update(source="Korea nedrug", label=seq, versions=(date_a, date_b), dates=(date_a, date_b))
    return out


def summary(result: dict) -> str:
    lines = [f"## Label change replay: {result['source']} {result['label']}",
             f"Version {result['versions'][0]} ({result['dates'][0]}) against version {result['versions'][1]} "
             f"({result['dates'][1]}).", "",
             f"- Sections changed: {', '.join(result['changed']) or 'none'}",
             f"- Sections that would alert: {', '.join(result['alerting']) or 'none'}"]
    for c in result["changes"][:12]:
        first = next((x for x in c.get("changes") or [] if x.get("after")), None)
        if first:
            lines.append(f"  - {c['section']}: added \"{first['after'][:160]}\"")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if not ((len(argv) == 4 and argv[0] == "dailymed") or (len(argv) == 2 and argv[0] == "nedrug")):
        print(__doc__)
        return 2
    ctx = FetchContext(None, "spc-replay", archive=Archive(enabled=False), public_only=True)
    try:
        result = replay_dailymed(ctx, *argv[1:]) if argv[0] == "dailymed" else replay_nedrug(ctx, argv[1])
    finally:
        ctx.close()
    text = summary(result)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if result["alerting"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
