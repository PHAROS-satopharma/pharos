"""PHAROS — can GitHub's network read each drug database the label watch is to read? (``probe-databases.yml``)

Run by hand before a database's reader is built (the label-watch plan of 6 Nov 2026, phase 4). Each check
fetches the database's list address and, where the list names a label, that label. It records the status, the
time taken, the size and whether the expected text came back. Nothing is bypassed: a bot check, a licence or
terms page, a sign-in or a site that times out is reported as it is, and that database is listed as blocked.
Plain requests only, through ``FetchContext`` (polite, public addresses only); nothing is archived or stored.

The run log is public: a key a site ships in its own page (Ireland, Austria) is reported as found or not, never
printed. The results also go to the job summary (``GITHUB_STEP_SUMMARY``) as one table.

    python -m collectors.spc.probe_databases [part of a name …]
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass

from collectors.core.archive import Archive
from collectors.core.context import FetchContext, SourceBlocked


@dataclass
class Check:
    name: str
    url: str
    expect: str                                   # a regex the answer must contain
    method: str = "GET"
    json: dict | None = None
    follow: tuple[str, str, str] | None = None    # (regex on the answer, label URL with {0}, regex in the label)


@dataclass
class Result:
    name: str
    status: str
    seconds: float
    size: int
    found: bool
    label: str = ""
    error: str = ""


CHECKS = [
    # outside Europe
    Check("Korea nedrug list",
          "https://nedrug.mfds.go.kr/searchDrug?searchYn=true&page=1&ingrEngName=ivabradine", r"itemSeq=\d+",
          follow=(r"itemSeq=(\d+)", "https://nedrug.mfds.go.kr/pbp/cmn/xml/drb/{0}/NB", r"<ARTICLE|<PARAGRAPH")),
    Check("Korea nedrug history",
          "https://nedrug.mfds.go.kr/searchDrug?searchYn=true&page=1&ingrEngName=ivabradine", r"itemSeq=\d+",
          follow=(r"itemSeq=(\d+)",
                  "https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemChangeHistList?itemSeq={0}&docType=NB&page=1",
                  r"data-docdata")),
    Check("Health Canada DPD",
          "https://health-products.canada.ca/api/drug/activeingredient/?lang=en&type=json&ingredientname=ivabradine",
          r"drug_code",
          follow=(r'"drug_code"\s*:\s*(\d+)', "https://health-products.canada.ca/dpd-bdpp/info?lang=eng&code={0}",
                  r"pdf\.hres\.ca/dpd_pm/\d+\.PDF")),
    Check("Health Canada monograph", "https://pdf.hres.ca/dpd_pm/00080705.PDF", r"^%PDF"),
    Check("Medsafe data sheets", "https://www.medsafe.govt.nz/profs/Datasheet/datasheet.htm", r"\.pdf"),
    Check("Medsafe updates", "https://www.medsafe.govt.nz/other/Updates-Data-sheets-and-CMIs.asp", r"(?i)data sheet"),
    Check("DailyMed past version",
          "https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?type=zip&setid=181aee35-8fb2-35e4-e063-6394a90a6b3b"
          "&version=3", r"^PK"),
    Check("EC Union Register", "https://ec.europa.eu/health/documents/community-register/html/h343.htm",
          r"dataSet_proc"),
    # Europe
    Check("Netherlands CBG", "https://www.geneesmiddeleninformatiebank.nl/metadata.csv", r"SMPC_FILENAAM"),
    Check("Belgium FAMHP", "https://medicinesdatabase.be/download/documents", r"(?i)url"),
    Check("Italy AIFA",
          "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/formadosaggio/ricerca?query=ivabradina&page=0",
          r"totalElements"),
    Check("Italy AIFA RCP",
          "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4136/farmaci/044509/stampati?ts=RCP",
          r"^%PDF"),
    Check("Sweden MPA", "https://www.lakemedelsverket.se/api/lmfrest/searchmedprod", r"totalCountMedprod",
          method="POST", json={"substName": "ivabradin", "status": "0", "take": 20, "skip": 0}),
    Check("Sweden MPA product", "https://www.lakemedelsverket.se/api/lmfrest/medprod?id=20151029000022",
          r"SmPC"),
    Check("Sweden MPA SmPC",
          "https://docetp.mpa.se/LMF/Ivabradin%20Krka%20film-coated%20tablet%20SmPC_09001bee807a5196.pdf", r"^%PDF"),
    Check("Portugal Infomed", "https://extranet.infarmed.pt/INFOMED-fo/", r"javax\.faces\.ViewState"),
    Check("Iceland sitemap", "https://www.serlyfjaskra.is/sitemap.xml", r"<loc>"),
    Check("Ireland HPRA list", "https://assets.hpra.ie/products/xml/latestHumanlist.xml", r"<"),
    Check("Ireland HPRA key", "https://www.hpra.ie/find-a-medicine/for-human-use/authorised-medicines",
          r"sfapi\.hpra\.ie/api/HumanApprovedProducts\?code=[A-Za-z0-9_\-=]+"),
    Check("Austria BASG", "https://medikamente.basg.gv.at/", r"(?i)<script"),
    Check("Austria BASG PDF", "https://medikamente.basg.gv.at/documents/1-18930__DOTC_FACH_INFO.pdf", r"^%PDF"),
    Check("France BDPM RCP",
          "https://base-donnees-publique.medicaments.gouv.fr/affichageDoc.php?specid=60073914&typedoc=R",
          r"4\.4|(?i:mises en garde)"),
    # reported blocked on 6 Nov 2026 from a desktop: checked again from GitHub, never worked around
    Check("Finland Fimea", "https://fimea.fi/en/databases_and_registers/fimeaweb", r"(?i)fimea"),
    Check("Norway DMP", "https://www.legemiddelsok.no/", r"(?i)legemiddel"),
    Check("Germany AMIce", "https://www.pharmnet-bund.de/PharmNet/EN/Public/Drug-information-system/_node.html",
          r"(?i)amice|drug"),
    Check("Switzerland AIPS", "https://www.swissmedicinfo.ch/?Lang=EN", r"(?i)swissmedic"),
    Check("Australia TGA",
          "https://www.tga.gov.au/products/australian-register-therapeutic-goods-artg/product-information",
          r"(?i)product information"),
    Check("Singapore HSA", "https://eservice.hsa.gov.sg/prism/common/enquirepublic/SearchDRBProduct.do?action=load",
          r"(?i)product"),
]


def _fetch(ctx: FetchContext, check: Check):
    if check.method == "POST":
        return ctx.post(check.url, json=check.json, accept="application/json", raise_for_status=False)
    return ctx.get(check.url, raise_for_status=False)


def _text(content: bytes) -> str:
    return content.decode("utf-8", "replace") if content else ""


def run_check(ctx: FetchContext, check: Check) -> Result:
    t0 = time.monotonic()
    try:
        f = _fetch(ctx, check)
    except SourceBlocked as exc:
        return Result(check.name, "blocked", time.monotonic() - t0, 0, False, error=str(exc)[:160])
    except Exception as exc:  # noqa: BLE001 - a timeout or a refused connection is the answer
        return Result(check.name, type(exc).__name__, time.monotonic() - t0, 0, False, error=str(exc)[:160])
    body = _text(f.content)
    r = Result(check.name, str(f.status), time.monotonic() - t0, len(f.content),
               bool(re.search(check.expect, body, re.M)))
    if r.found and check.follow and f.status == 200:
        m = re.search(check.follow[0], body)
        if m:
            try:
                g = ctx.get(check.follow[1].format(m.group(1)), raise_for_status=False)
                r.label = f"{g.status}, {'label text' if re.search(check.follow[2], _text(g.content)) else 'no label text'}"
            except SourceBlocked:
                r.label = "blocked"
            except Exception as exc:  # noqa: BLE001
                r.label = type(exc).__name__
    return r


def table(results: list[Result]) -> str:
    rows = ["| Database | Answer | Seconds | Bytes | Expected text | Label |", "|---|---|---|---|---|---|"]
    for r in results:
        answer = r.status + (f" ({r.error})" if r.error else "")
        rows.append(f"| {r.name} | {answer} | {r.seconds:.1f} | {r.size:,} | {'yes' if r.found else 'no'} "
                    f"| {r.label} |")
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    wanted = [a.casefold() for a in argv]
    checks = [c for c in CHECKS if not wanted or any(w in c.name.casefold() for w in wanted)]
    ctx = FetchContext(None, "probe-databases", archive=Archive(enabled=False), public_only=True,
                       max_bytes=150_000_000)      # Belgium's documents file is larger than 40 MB
    results = []
    try:
        for c in checks:
            r = run_check(ctx, c)
            results.append(r)
            print(f"{r.name}: {r.status} in {r.seconds:.1f} s, {r.size} bytes, expected text "
                  f"{'found' if r.found else 'not found'}{', label ' + r.label if r.label else ''}"
                  f"{' (' + r.error + ')' if r.error else ''}", flush=True)
    finally:
        ctx.close()
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Drug databases, read from GitHub\n\n" + table(results) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
