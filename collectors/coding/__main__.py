"""Medical coding (migration 0061).

    python -m collectors.coding --mesh [--file desc2026.gz] [--force]
                                         load the newest MeSH release (the "PHAROS dictionaries" workflow)
    python -m collectors.coding --meddra    load the newest MedDRA upload asked for on the Cases screen (0102)
    python -m collectors.coding --meddra --file MedDRA_28_1_English.zip
                                         load a saved release (its zip, or a MedAscii folder) directly
    python -m collectors.coding --case ID   suggest the codes of one case now
    python -m collectors.coding --waiting   suggest the codes of every case asked for or read since last coded
    python -m collectors.coding --papers    keep the MeSH headings of the literature papers (0062)
    python -m collectors.coding --labels [--force]
                                         find the MeSH names in our labels and the reference labels (0062)
    python -m collectors.coding --terminology ncit [--file Thesaurus.FLAT.zip]
                                         load the newest release of a free terminology (0103): the first one at
                                         once, a later one staged for an administrator's review; "all" loads each
"""

from __future__ import annotations

import argparse
import logging
import re
import sys

log = logging.getLogger("collectors.coding")

TERMINOLOGIES = ("ncit",)     # collectors/coding/terminology/<name>.py, each with run()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.coding", description=__doc__.split("\n\n")[0])
    p.add_argument("--mesh", action="store_true", help="load the newest MeSH release")
    p.add_argument("--meddra", action="store_true", help="load the newest MedDRA upload asked for")
    p.add_argument("--terminology", choices=["all", *TERMINOLOGIES],
                   help="load the newest release of a free terminology (or all of them)")
    p.add_argument("--file", help="with --mesh, --meddra or one --terminology: load this saved release instead")
    p.add_argument("--force", action="store_true",
                   help="with --mesh: load even when the same release is loaded; with --labels: code every label")
    p.add_argument("--case", help="suggest the codes of this case")
    p.add_argument("--waiting", action="store_true", help="suggest the codes of every case waiting for them")
    p.add_argument("--papers", action="store_true", help="keep the MeSH headings of the literature papers")
    p.add_argument("--labels", action="store_true", help="find the MeSH names in the labels")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.terminology == "all" and args.file:
        p.error("--file takes one terminology, not all")
    if args.case and not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", args.case):
        p.error("--case takes a case id")

    from collectors.core.context import install_log_redaction

    install_log_redaction()   # the run logs are public: no request address (a product's name) is printed
    from collectors.coding import coder, labels, meddra, mesh, papers
    from collectors.core.db import Db

    db = Db()
    try:
        if args.meddra:
            if args.file:
                from pathlib import Path

                src = Path(args.file)
                paths = sorted(src.iterdir()) if src.is_dir() else [src]
                print("meddra:", meddra.load_files(db, {p.name: p.read_bytes() for p in paths if p.is_file()},
                                                   source=src.name))
            else:
                print("meddra:", meddra.load_waiting(db))
        if args.mesh:
            if args.file:
                with open(args.file, "rb") as fh:
                    data = fh.read()
                year = re.search(r"(\d{4})", args.file)
                print("mesh:", mesh.load(db, data, year=int(year.group(1)) if year else None,
                                         url=args.file.replace("\\", "/").rsplit("/", 1)[-1], force=args.force))
            else:
                print("mesh:", mesh.load(db, force=args.force))
        if args.terminology:
            failed = terminology(db, args.terminology, args.file)
            if failed:
                return 1
        if args.case or args.waiting:
            print("coding:", coder.code_waiting(db, case_id=args.case, make_reader=coder.default_reader))
        if args.papers:
            print("papers:", papers.code_papers(db))
        if args.labels:
            print("labels:", labels.code_labels(db, force=args.force))
    finally:
        db.close()
    return 0


def terminology(db, which: str, file: str | None) -> int:
    """Each terminology asked for; how many could not be loaded (each is tried even when one fails)."""
    import importlib

    from collectors.coding.terminology.base import TerminologyError, default_notify
    from collectors.core.archive import Archive

    archive, notify = Archive(), default_notify(db)
    failed = 0
    for name in TERMINOLOGIES if which == "all" else (which,):
        module = importlib.import_module(f"collectors.coding.terminology.{name}")
        data = None
        if file:
            with open(file, "rb") as fh:
                data = fh.read()
        try:
            print(f"{name}:", module.run(db, data=data, archive=archive, notify=notify))
        except TerminologyError as exc:
            print(f"::error::{name}: {exc}")
            failed += 1
        except Exception as exc:
            # Never the database's own message: a COPY error quotes the line, and the run log is public.
            print(f"::error::{name}: the load stopped ({type(exc).__name__})")
            failed += 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
