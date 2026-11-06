# PHAROS computerised-system validation summary

PHAROS (Pharmaceutical Alerts & Regulatory Observation System), by Sato Pharma. This summary is written for
a pharmacovigilance (GVP Module VI and IX) context. It takes a risk-based approach in the spirit of GAMP 5
and EU GMP Annex 11.

## 1. Intended use

PHAROS is a **screening aid** for the Sato Pharma pharmacovigilance team. On a schedule it reads the public
safety communications of 25 reference regulators: DHPCs, safety alerts and updates, recalls, PSUSA
outcomes and label changes. It screens each one in its original language for the active ingredients the
team watches, and presents what it finds for human review.

- PHAROS **does not** decide whether a notice is relevant. A named reviewer decides, and the decision is
  recorded.
- PHAROS **does not** translate. Titles and texts are kept and shown exactly as the regulator published them.
- PHAROS **does not** replace the team's literature-screening procedure. It supports and evidences it. If
  PHAROS is unavailable, the team falls back to the manual procedure, using the corrected source list.
- Telegram messages carry public regulatory content only, never reviewer comments.

**Category.** The collectors, matching and merging are bespoke software (GAMP category 5). The hosting
services (GitHub Actions, Supabase, Cloudflare R2 and Pages, Telegram) are configured infrastructure
(category 1 and 4). The risk is moderate: a missed notice could delay a safety assessment. This is why the
controls below focus on completeness (the screening log, source health and the watchdog) and integrity
(hashes, the bucket lock, the audit trail).

## 2. Requirements and acceptance tests

| # | Requirement | Acceptance test | How it is run |
|---|---|---|---|
| 1 | Historical EMA data is captured without alerting | After backfill, lornoxicam PSUSA/00001911/202412 "Maintenance" appears as an issue, and no Telegram message is sent | Live dry run (backfill.yml) |
| 2 | Ingredients are identified safely | Typing "laura noxicam" offers lornoxicam and tenoxicam; nothing is saved until confirmed; the saved ingredient is M01AC05 | Web app, `ingredient-lookup` |
| 3 | Label changes are detected per section | CIMA: 7 lornoxicam products are watched; a changed section 4.4 in a test copy is shown in Spanish | pytest (fixtures) + live weekly run |
| 4 | Matching works in each language without translation | fi `lornoksikaamia`, ja `ロルノキシカム` inside a PDF and `Lornoxi-\ncam` all match; `tenoksikaami` and `meloxicam` do not; de `NSAR-haltigen` goes to the digest only | pytest |
| 5 | National copies of one EU issue form one row | One EMA DHPC plus its BfArM, ANSM and AIFA copies gives one issue with 4 documents, with the highlights in each language | pytest |
| 6 | Originals cannot be altered | Recomputed hashes equal the stored ones; an overwrite is refused; an UPDATE or DELETE on `review_event` is rejected | verify-archive (weekly) + CI database checks |
| 7 | Every screening is logged | Each run writes a `source_run` row for every enabled source, including runs with zero matches | pytest + `run`/`source_run` tables |
| 8 | Source failures are visible | 3 failures in a row alert the admin only; Fimea shows "blocked", not "down" | pytest + Sources screen |
| 9 | Missed runs are noticed | With no run for 6 h, the admin is alerted (logged only in dry run), at most once every 6 h | CI database checks + pg_cron |
| 10 | Access is controlled | "Not relevant" without a comment is refused; a reader cannot change status or queue a probe; the public key reads nothing and cannot call the functions | CI database checks |
| 11 | Telegram linking is safe | A deep link connects the chat; the code is stored only as its hash and works once; a reused or expired code is refused; an unlinked chat gets nothing | CI database checks + live dry run |
| 12 | The weekly report is complete and fixed | The XLSX and the PDF of a Sunday-to-Saturday Cairo week cover every source read, with run and failure counts, each watched ingredient by country as its Ingredients screen answers, the NCBI literature, everything new and what to check by hand, with the decisions, and are stored with their SHA-256 | Live run (report.yml) |
| 13 | It stays inside the free plans | Under 300 Actions minutes a week, the database under 150 MB after backfill, $0 a month | docs/operations.md budget + watchdog |
| 14 | Tests are meaningful | A regression test counts only if breaking the fix makes it fail; the code is then restored from a copy | Recorded in the pull request |
| 15 | What users see is what was checked | The rendered output is checked by reading the deployed Pages site, never only the source code | Recorded in the pull request |
| 16 | A case report is kept whole and confirmed by a person | An upload stores the original under its SHA-256 and a tampered original is never read; a reader cannot open a case; a case without a reporter and a reaction is refused at confirmation and says what is missing; a change made from an older view is refused; a confirmed non-serious case is due 90 days after day zero; every step is one append-only `case_event` row; the E2B file is refused without each reaction's MedDRA code and version | CI database checks (`supabase/tests/case_intake.sql`) + pytest (`tests/test_cases.py`) + Deno (`case-intake/sniff_test.ts`) |
| 17 | A code is suggested, never decided | The reader chooses only among the descriptors MeSH returned (an invented code is dropped); the suggestions are kept beside the form and change neither the form nor its version; only confirmed cases teach the next suggestion; nobody in the app writes the dictionary; without the reader or without RxNav the coder still suggests | CI database checks (`supabase/tests/medical_coding.sql`) + pytest (`tests/test_coding.py`) + vitest (`caseForm.test.ts`) |
| 18 | A count is shown, never judged | Only coded reactions are counted (a paper's heading without "chemically induced" or C25, a suggested link and a case not valid are not); the days before are the same number of days; a broader heading in a label lists the reactions beneath it and our label comes before the reference label; a topic holds its seeds and what is beneath them; nobody in the app writes the topics or the label terms | CI database checks (`supabase/tests/medical_coding_signals.sql`) + pytest (`tests/test_coding_signals.py`) |
| 19 | A report count is FDA's, never ours | openFDA's "No matches found" is a zero, not a failure; a 429 or a server error is asked again; PRR, ROR, their 95% intervals and Yates' chi-squared match numbers worked by hand, and a zero cell gives no value instead of a division by zero; the flag needs at least 3 reports, PRR at least 2 and chi-squared at least 4; a quarter that did not list every reaction leaves a missing one unknown; a reaction MeSH does not have gets no label tag; no MedDRA code is stored; nobody in the app writes the counts; the run log names no ingredient | CI database checks (`supabase/tests/faers_counts.sql`) + pytest (`tests/test_faers.py`) |

Each pull request records the test evidence it touches. CI results are kept with every pull request in
GitHub.

## 3. Audit trail

| Record | What it holds | Protection |
|---|---|---|
| `review_event` | Every status change: from, to, comment, person and time. "Not relevant" requires a comment | Append-only: a trigger rejects UPDATE and DELETE |
| `audit_log` | Insert, update and delete, with the old and new row and the actor, on ingredients, terms, sources, people, subscriptions, settings, products and issue links | Written by trigger; no API write access |
| `run`, `source_run` | The screening log: every run, every source, HTTP status, counts, errors and the code version (`git_sha`) | Service role only |
| `notification` | Who was told what and when, dry run or real, and the Telegram message id | Service role only |
| `ops_alert_log` | Every watchdog alert, sent or not | Service role only; admins can read it |
| `archive_check` | Each weekly integrity check: objects sampled, mismatches, missing objects, lock result | Service role only |
| `probe_result` | Who tested which link and what was found | Admins queue probes as themselves |

Times are stored in UTC and shown in Cairo time. People are named; nobody acts as a shared account.

## 4. Archive integrity

- Every original the collectors read is stored in Cloudflare R2 under its SHA-256 (`sha256/<2>/<hash>`):
  listings, notice pages, PDFs and inbound newsletter emails. The hash is also stored in the database.
- Bucket lock rules forbid any overwrite or delete of the originals.
- Every week, 50 random originals are downloaded again and re-hashed against the database. The check also
  confirms that an overwrite is refused. The result is written to `archive_check`, and a failure fails the
  job.
- The database is backed up every night to R2 and kept for 90 days.

## 5. Access control

- Sign-in is invite-only: public sign-up is off. An admin invites each person with a role (admin, reviewer
  or reader).
- Row-level security enforces the roles in the database itself, not only in the screens. The public key
  reads nothing.
- Archive files are served through 10-minute signed links, and only for files that a record the person can
  read points to. Backups are never served to the app.
- Every account that runs PHAROS belongs to the company mailbox pharos@satopharma.com and has 2-step
  login.

## 6. Change control

- All code and configuration live in the private GitHub repository `pharos`. Every change is a pull
  request.
- CI runs on every pull request: linting and tests for the collectors, a typecheck and build of the web app,
  every database migration applied to a clean Postgres with the access-control checks above, and a
  typecheck of the server functions.
- A change is merged only on the owner's word, one pull request at a time. Merging to `main` deploys the
  database, the functions and the website automatically. Each collection run records the code version it
  ran (`run.git_sha`).
- Secrets are held only in GitHub, Supabase and Cloudflare secret stores, never in the repository.

## 7. Periodic review

Monthly, using the weekly reports: check source health (any `blocked`, `down` or long-`degraded` source),
the archive checks, the Actions minutes and the database size. Once a year, confirm the source list against
the regulators' own sites and re-run acceptance tests 2 to 11.

## 8. Known limitations

- Coverage depends on what each regulator publishes and on whether its site can be read. A bot-checked site
  is never bypassed; it is read through its newsletter or marked `blocked`.
- Scanned PDFs are read by OCR. A fuzzy OCR hit is marked "possible" and goes to review only, never to an
  alert.
- National brand names must be added by hand in the term editor. The ingredient lookup lists the gaps it
  knows about.
- Cases: the reader fills the form from the document; a reviewer checks every field against the document and
  confirms. MedDRA coding is done by the reviewer. The E2B(R3) file has not yet been validated against the ICH
  schema or the Egyptian Drug Authority's gateway: until it has, it is a prepared draft, checked before sending.
- Coding: reactions, indications and medical history are coded with MeSH and products with RxNorm and UNII, all
  free from the U.S. National Library of Medicine and the FDA. MeSH is not MedDRA: signal counts and searches run
  on MeSH, and the E2B file still needs the MedDRA code typed from the authority's or a partner's coding.
- The free plans have limits (database 500 MB, Actions 2,000 minutes, R2 10 GB). The watchdog and the budget
  above keep PHAROS inside them.
