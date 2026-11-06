# spc-mpa (PHAROS fixture)

Läkemedelsverket, Läkemedelsfakta, saved 7 November 2026.

* `search_ivabradine.json`: `POST https://www.lakemedelsverket.se/api/lmfrest/searchmedprod` with
  `{"substName": "ivabradine", "status": "0", "take": 500, "skip": 0}`: 20 rows.
* `medprod_20151029000022.json`: `GET …/api/lmfrest/medprod?id=20151029000022`, Ivabradin Krka (national; its
  SmPC covers both strengths, approved 25 September 2023).
* `medprod_20040607009420.json`: the same for Corlentor (centrally authorised: `isCentralProcedure`).

The SmPC PDFs are on `docetp.mpa.se`, which does not answer from this machine; `read_check.py` reads them from
GitHub.
