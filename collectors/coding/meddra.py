"""MedDRA, from the company's own MSSO subscription files (migration 0102).

An administrator uploads the release on the Cases screen: the zip as MSSO sends it, or the ``.asc`` files of its
``MedAscii`` folder. They land in the private storage bucket ``meddra`` under ``uploads/<UTC time>/`` and the upload
is asked for (``meddra_upload``). ``load_waiting()`` takes the newest upload asked for, reads the ASCII files and
replaces the dictionary in one transaction; older uploads still waiting are marked replaced.

The files are MedDRA's own (ICH's, licensed to the subscriber): nothing of them is printed, so the public run log
names only the version, the language and the counts.

The ASCII files are ``$``-separated, one record a line, with a trailing ``$``:
    meddra_release.asc  version$language$…
    llt.asc             llt_code$llt_name$pt_code$…(6 legacy codes)…$llt_currency$…
    pt.asc              pt_code$pt_name$null$pt_soc_code$…
    mdhier.asc          pt_code$hlt_code$hlgt_code$soc_code$pt_name$hlt_name$hlgt_name$soc_name$soc_abbrev$null$
                        pt_soc_code$primary_soc_fg$
"""

from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from typing import Any, Callable

log = logging.getLogger("collectors.coding.meddra")

NEEDED = ("meddra_release.asc", "llt.asc", "pt.asc", "mdhier.asc")
CODE = re.compile(r"^[0-9]{8}$")
VERSION = re.compile(r"^[0-9]{1,2}\.[0-9]$")
MAX_FILE = 200 * 1024 * 1024     # what one unzipped file may be; MedDRA's largest is a few tens of MB


class MeddraError(Exception):
    """What is wrong with the files, in words the administrator can act on."""


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _rows(data: bytes) -> list[list[str]]:
    out = []
    for line in _text(data).splitlines():
        if line.strip():
            fields = line.split("$")
            out.append([f.strip() for f in fields])
    return out


def files_of_zip(data: bytes) -> dict[str, bytes]:
    """The ``.asc`` files of a release zip, by lower-case base name (a zip inside the zip is opened too)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise MeddraError("The file is not a zip that can be opened. Upload the zip as MSSO sent it, "
                          "or the .asc files of its MedAscii folder.") from exc
    out: dict[str, bytes] = {}
    with zf:
        for info in zf.infolist():
            base = info.filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if info.is_dir() or not (base.endswith(".asc") or base.endswith(".zip")):
                continue
            if info.flag_bits & 0x1:
                raise MeddraError("The zip is locked with a password. Open it on your computer with the password "
                                  "MSSO gave, then upload the .asc files of its MedAscii folder.")
            if info.file_size > MAX_FILE:
                raise MeddraError(f"{base} is larger than any MedDRA file: this is not a MedDRA release.")
            body = zf.read(info)
            if base.endswith(".zip"):
                for k, v in files_of_zip(body).items():
                    out.setdefault(k, v)
            elif base in NEEDED:
                out.setdefault(base, body)
    return out


def parse(files: dict[str, bytes]) -> dict:
    """The release from its ASCII files: version, language, pts {code: row}, llts [rows]."""
    missing = [n for n in NEEDED if n not in files]
    if missing:
        raise MeddraError("These MedDRA files are missing: " + ", ".join(missing)
                          + ". Upload the whole MedAscii folder, or the zip as MSSO sent it.")
    release = _rows(files["meddra_release.asc"])
    version = release[0][0] if release and release[0] else ""
    language = release[0][1] if release and len(release[0]) > 1 else ""
    if not VERSION.match(version):
        raise MeddraError("meddra_release.asc does not name a MedDRA version such as 28.1.")

    pts: dict[str, dict] = {}
    for r in _rows(files["pt.asc"]):
        if len(r) < 4 or not CODE.match(r[0]) or not r[1]:
            raise MeddraError("pt.asc has a line that is not a MedDRA Preferred Term.")
        pts[r[0]] = {"code": r[0], "name": r[1], "hlt_code": None, "hlt_name": None, "hlgt_code": None,
                     "hlgt_name": None, "soc_code": r[3] if CODE.match(r[3]) else None, "soc_name": None,
                     "soc_abbrev": None}
    for r in _rows(files["mdhier.asc"]):
        if len(r) < 12 or not CODE.match(r[0]):
            raise MeddraError("mdhier.asc has a line that is not a MedDRA hierarchy line.")
        pt = pts.get(r[0])
        if pt is None:
            continue
        primary = r[11].upper() == "Y"
        if primary or pt["hlt_code"] is None:   # the primary path; any path until the primary one is read
            pt.update({"hlt_code": r[1], "hlt_name": r[5], "hlgt_code": r[2], "hlgt_name": r[6],
                       "soc_code": r[3], "soc_name": r[7], "soc_abbrev": r[8] or None})

    llts = []
    for r in _rows(files["llt.asc"]):
        if len(r) < 10 or not CODE.match(r[0]) or not r[1] or not CODE.match(r[2]):
            raise MeddraError("llt.asc has a line that is not a MedDRA Lowest Level Term.")
        if r[2] not in pts:
            raise MeddraError("llt.asc names a Preferred Term that pt.asc does not have: the files are of two "
                              "releases. Upload one release's files together.")
        llts.append({"code": r[0], "name": r[1], "pt_code": r[2], "current": r[9].upper() != "N"})
    if not llts:
        raise MeddraError("llt.asc has no terms.")
    return {"version": version, "language": language, "pts": pts, "llts": llts}


def store(db: Any, parsed: dict, *, source: str, sha: str) -> dict[str, int]:
    """Replace the dictionary in one transaction; counts."""
    cols = ("code", "name", "hlt_code", "hlt_name", "hlgt_code", "hlgt_name", "soc_code", "soc_name", "soc_abbrev")
    with db.transaction():
        db.execute("delete from meddra_llt")
        db.execute("delete from meddra_pt")
        with db.conn.cursor() as cur:
            with cur.copy(f"copy meddra_pt ({', '.join(cols)}) from stdin") as cp:
                for pt in parsed["pts"].values():
                    cp.write_row(tuple(pt[c] for c in cols))
            with cur.copy("copy meddra_llt (code, name, pt_code, current) from stdin") as cp:
                for llt in parsed["llts"]:
                    cp.write_row((llt["code"], llt["name"], llt["pt_code"], llt["current"]))
        version = f"MedDRA {parsed['version']}" + (f" {parsed['language']}" if parsed["language"] else "")
        db.execute(
            """insert into coding_dictionary (name, version, release, source_url, sha256, descriptors, terms,
                                              loaded_at)
               values ('meddra', %(v)s, %(r)s, %(u)s, %(s)s, %(d)s, %(t)s, now())
               on conflict (name) do update set version = excluded.version, release = excluded.release,
                      source_url = excluded.source_url, sha256 = excluded.sha256,
                      descriptors = excluded.descriptors, terms = excluded.terms, loaded_at = excluded.loaded_at""",
            {"v": version, "r": parsed["version"], "u": source, "s": sha, "d": len(parsed["pts"]),
             "t": len(parsed["llts"])})
    return {"pts": len(parsed["pts"]), "llts": len(parsed["llts"])}


def load_files(db: Any, uploaded: dict[str, bytes], *, source: str) -> str:
    """Load one upload (its files by name); what was done, in words."""
    from collectors.core.archive import sha256_hex

    files: dict[str, bytes] = {}
    for name, body in uploaded.items():
        base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base.endswith(".zip"):
            for k, v in files_of_zip(body).items():
                files.setdefault(k, v)
        elif base in NEEDED:
            files[base] = body
    parsed = parse(files)
    sha = sha256_hex(b"".join(files[n] for n in NEEDED))
    counts = store(db, parsed, source=source, sha=sha)
    return (f"MedDRA {parsed['version']} {parsed['language']}".rstrip()
            + f": {counts['llts']} Lowest Level Terms under {counts['pts']} Preferred Terms")


def storage_get(path: str) -> bytes:
    """One object of the private bucket, with the service key (the workflow's secrets)."""
    import httpx

    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    res = httpx.get(f"{base}/storage/v1/object/authenticated/meddra/{path}", timeout=180,
                    headers={"Authorization": f"Bearer {key}", "apikey": key}, follow_redirects=False)
    if res.status_code != 200:
        raise RuntimeError(f"storage answered HTTP {res.status_code}")
    return res.content


def load_waiting(db: Any, get: Callable[[str], bytes] = storage_get) -> str:
    """Load the newest upload asked for; what was done, in words."""
    waiting = db.fetchall("select folder from meddra_upload where status = 'waiting' order by folder desc")
    if not waiting:
        return "no upload is waiting"
    folder = waiting[0]["folder"]
    older = [w["folder"] for w in waiting[1:]]
    if older:
        db.execute("""update meddra_upload set status = 'replaced', done_at = now(),
                             message = 'A newer upload was loaded in its place.'
                       where folder = any(%s)""", (older,))
    db.execute("update meddra_upload set status = 'loading', message = null where folder = %s", (folder,))
    try:
        names = [r["name"] for r in db.fetchall(
            "select name from storage.objects where bucket_id = 'meddra' and name like %s order by name",
            (folder + "/%",))]
        if not names:
            raise MeddraError("No file arrived with this upload. Upload the files again.")
        said = load_files(db, {n: get(n) for n in names}, source=folder)
    except MeddraError as exc:
        db.execute("update meddra_upload set status = 'failed', message = %s, done_at = now() where folder = %s",
                   (str(exc), folder))
        return f"{folder}: failed ({exc})"
    except Exception as exc:
        db.execute("update meddra_upload set status = 'failed', message = %s, done_at = now() where folder = %s",
                   (f"The load stopped ({type(exc).__name__}); it is tried again when the files are uploaded "
                    "again.", folder))
        # Never the database's own message: a COPY error quotes the line, and the run log is public.
        raise RuntimeError(f"The MedDRA load stopped ({type(exc).__name__})") from None
    db.execute("update meddra_upload set status = 'loaded', message = %s, done_at = now() where folder = %s",
               (said, folder))
    return f"{folder}: {said}"
