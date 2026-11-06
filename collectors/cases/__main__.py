"""Individual case reports (migration 0059).

    python -m collectors.cases --case ID       read one case now (the case-read workflow, on the reviewer's click)
    python -m collectors.cases --e2b ID        make one case's E2B(R3) file now
    python -m collectors.cases --code ID       suggest one case's codes again now (collectors/coding)
    python -m collectors.cases --mail          open a case for each report forwarded to the PHAROS mailbox
    python -m collectors.cases --waiting       read every case still waiting, suggest the codes of every case read
                                               and make every E2B file asked for
                                               (the "Cases" step of every collection run: the safety net when
                                               GitHub could not be reached from the app)

--mail and --waiting go together in collect.yml. A failure is logged and recorded on the case; the exit status is
1 only when the database or the archive cannot be reached.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys

log = logging.getLogger("collectors.cases")

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _uuid(value: str) -> str:
    if not UUID.match(value or ""):
        raise argparse.ArgumentTypeError("not a case id")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.cases", description=__doc__.split("\n\n")[0])
    ap.add_argument("--case", type=_uuid, help="read this case now")
    ap.add_argument("--e2b", type=_uuid, help="make this case's E2B(R3) file now")
    ap.add_argument("--code", type=_uuid, help="suggest this case's codes again now")
    ap.add_argument("--mail", action="store_true", help="open cases from the PHAROS mailbox")
    ap.add_argument("--waiting", action="store_true", help="read waiting cases and make waiting E2B files")
    args = ap.parse_args(argv)
    if not (args.case or args.e2b or args.code or args.mail or args.waiting):
        ap.error("say what to do: --case, --e2b, --code, --mail or --waiting")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from collectors.core.context import install_log_redaction

    install_log_redaction()
    from collectors.cases import e2b, mail, read
    from collectors.coding import coder
    from collectors.core.archive import Archive
    from collectors.core.db import Db
    from collectors.core.imap_inbox import NOT_CONFIGURED

    db = Db()
    archive = Archive()
    if archive.backend != "r2" and os.environ.get("GITHUB_ACTIONS"):
        log.error("the archive is not connected (R2 variables missing)")
        return 1
    if args.mail:
        try:
            print("mail:", mail.collect(db, archive))
        except RuntimeError as exc:
            if str(exc) != NOT_CONFIGURED:
                raise
            log.info("mail: %s", NOT_CONFIGURED)
    reader = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if (args.case or args.waiting) and not reader:
        log.warning("the reader is not set up (ANTHROPIC_API_KEY is missing): the cases wait unread")
    if args.case and reader:
        print("read:", read.read_waiting(db, archive, case_id=args.case))
    if args.waiting and reader:
        print("read:", read.read_waiting(db, archive))
    # Codes are suggested from the form as read (MeSH and RxNorm), with or without the reader. Coding never
    # stops the run: a case it could not code shows why, with "Suggest the codes again".
    if args.case or args.code or args.waiting:
        try:
            print("coding:", coder.code_waiting(db, case_id=args.case or args.code, make_reader=coder.default_reader))
        except Exception:  # noqa: BLE001
            log.exception("coding: the cases could not be coded")
    if args.e2b:
        print("e2b:", e2b.make(db, archive, args.e2b))
    if args.waiting:
        print("e2b:", e2b.make(db, archive))
    return 0


if __name__ == "__main__":
    sys.exit(main())
