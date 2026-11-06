"""Medical coding (migration 0061).

    python -m collectors.coding --mesh [--file desc2026.gz] [--force]
                                         load the newest MeSH release (the "PHAROS dictionaries" workflow)
    python -m collectors.coding --case ID   suggest the codes of one case now
    python -m collectors.coding --waiting   suggest the codes of every case asked for or read since last coded
"""

from __future__ import annotations

import argparse
import logging
import re
import sys

log = logging.getLogger("collectors.coding")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.coding", description=__doc__.split("\n\n")[0])
    p.add_argument("--mesh", action="store_true", help="load the newest MeSH release")
    p.add_argument("--file", help="with --mesh: load this saved release instead of downloading it")
    p.add_argument("--force", action="store_true", help="with --mesh: load even when the same release is loaded")
    p.add_argument("--case", help="suggest the codes of this case")
    p.add_argument("--waiting", action="store_true", help="suggest the codes of every case waiting for them")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.case and not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", args.case):
        p.error("--case takes a case id")

    from collectors.core.context import install_log_redaction

    install_log_redaction()   # the run logs are public: no request address (a product's name) is printed
    from collectors.coding import coder, mesh
    from collectors.core.db import Db

    db = Db()
    try:
        if args.mesh:
            if args.file:
                with open(args.file, "rb") as fh:
                    data = fh.read()
                year = re.search(r"(\d{4})", args.file)
                print("mesh:", mesh.load(db, data, year=int(year.group(1)) if year else None,
                                         url=args.file.replace("\\", "/").rsplit("/", 1)[-1], force=args.force))
            else:
                print("mesh:", mesh.load(db, force=args.force))
        if args.case or args.waiting:
            print("coding:", coder.code_waiting(db, case_id=args.case, make_reader=coder.default_reader))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
