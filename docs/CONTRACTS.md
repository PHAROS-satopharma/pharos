# Internal contracts (binding for every part of the build)

The schema is in `supabase/migrations/0001_core.sql`. Nothing below may contradict it. If a part needs
another table, it goes in that part's own migration file, listed under "Who owns what".

## Who owns what

| Owner | Paths |
|---|---|
| Collectors core (A1) | `collectors/core/`, `collectors/parsers/{__init__,base,feed,ema_dhpc,ema_psusa,govuk,openfda_enforcement,hc_recalls,pubmed}.py`, `collectors/{run,matching,pdf,merge,alerts,report,backfill,probe,classes,rematch}.py`, `collectors/report_templates/`, `collectors/sources.yaml`, `collectors/requirements.txt`, `supabase/migrations/0003_seed_watchlist.sql`, `tests/test_{matching,merge,alerts,feed,ema,run,classes,rematch,pubmed_ncbi}*.py`, `supabase/migrations/0034_drug_classes_and_rematch.sql`, `supabase/migrations/0035_literature_search.sql`, `tests/fixtures/{ema-*,fda-*,mhra-*,bfarm-rhb,basg-*,aemps-*,hsa-*,hc-*,pubmed,atc-classes}/` |
| Collectors sources and SPC (A2) | `collectors/parsers/<every HTML, browser and email parser>.py`, `collectors/spc/`, `tests/test_{parsers,spc}*.py`, `tests/fixtures/<their sources>/` |
| Platform (C) | `supabase/migrations/0002_ops.sql`, `supabase/functions/`, `supabase/config.toml`, `workers/`, `.github/workflows/`, `docs/{setup,operations,validation}.md`, `.env.example`, `pyproject.toml` (pytest, ruff config) |
| Web (B) | `web/` |

Nobody edits another owner's files.

## Python collector interfaces (A1 implements; A2 codes against them exactly)

```python
# collectors/core/models.py
@dataclass
class Item:
    external_id: str              # stable id from the source (guid, url, procedure no.)
    url: str                      # the notice on the regulator's own site
    title: str                    # original language, exactly as published — never translated
    published: date | None
    doc_type: str                 # one of the doc_type enum values in 0001_core.sql
    lang: str | None              # BCP-47 of this item (a source can publish in several)
    body_text: str | None = None  # text of the notice page, if known
    attachment_urls: list[str] = field(default_factory=list)
    structured: dict | None = None  # raw structured fields, stored in document.structured

@dataclass
class SourceConfig:  # one entry of sources.yaml (and of the source table)
    id: str; regulator_id: str; kind: str; channel: str; url: str; parser: str
    languages: list[str]; schedule: str; enabled: bool
    options: dict                 # parser-specific options from sources.yaml
    expected_max_gap_days: int | None

@dataclass
class Fetched:
    status: int; final_url: str; content: bytes; content_type: str
    @property
    def text(self) -> str: ...    # decoded using the HTTP charset, meta charset, then utf-8/cp1252/shift_jis/euc-kr sniffing

# collectors/core/context.py
class FetchContext:
    db: "Db"
    run_id: str
    backfill: bool
    def get(self, url: str, *, accept: str | None = None, headers: dict | None = None) -> Fetched: ...
        # polite: one request at a time per host, 1 s apart, real browser User-Agent, 40 s timeout,
        # ETag/Last-Modified conditional GET (returns status 304 with empty content when unchanged),
        # every 200 response is archived (see archive) automatically.
    def browser_get(self, url: str, *, wait_selector: str | None = None, timeout_ms: int = 45000) -> Fetched: ...
        # Playwright Chromium, one shared browser per run; never solves or bypasses a challenge page —
        # if a Cloudflare/bot challenge is detected it raises SourceBlocked.
    def archive(self, content: bytes, mime: str) -> tuple[str, str]: ...   # -> (sha256, r2_key)

class SourceBlocked(Exception): ...   # source health becomes 'blocked', never retried aggressively
class ParseError(Exception): ...      # the page changed shape; source health becomes 'degraded'

# collectors/core/db.py
class Db:
    def fetchall(self, sql: str, params: dict | tuple | None = None) -> list[dict]: ...
    def fetchone(self, sql: str, params=None) -> dict | None: ...
    def execute(self, sql: str, params=None) -> None: ...
    def transaction(self): ...    # context manager

# collectors/pdf.py
def extract_text(content: bytes, lang_hint: str | None) -> tuple[str, str, int]: ...
    # -> (text, method 'text'|'ocr'|'none', words). pdftotext -layout; if a page has < 25 words,
    # tesseract with the language pack mapped from lang_hint (jpn, kor, fin, swe, dan, nor, isl, deu,
    # fra, ita, spa, por, nld, ara, eng).
```

**Parser module contract.** `collectors/parsers/<name>.py` defines:

- `list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]` (required)
- `fetch_detail(ctx, source, item: Item) -> Item` (optional): fills `body_text` and `attachment_urls` from the
  notice page.
- `after_store(ctx, source, items, stored: set[str]) -> None` (optional): called after the run stored what it
  could; `stored` holds every external id now in the database. The mailbox marks only stored mail as read;
  `pubmed` records which searches finished their look-back.
- `is_history(item) -> bool` (optional): the item is stored as history (no alert, no digest line), like a
  backfill. `pubmed`: a paper found only by a search's first 12-month look-back.
- `aliases(item) -> list[str]` (optional): other external ids the same item may already be stored under; the
  runner skips the item when one is known. `pubmed`: a paper's PMC id (stored so before its PMID existed).
- `STRUCTURED_FIELDS` (optional): paths in `structured` matched like text, always with confidence high.
  `pubmed`: `query_term`, the search words that found the paper.

The runner gives every parser `ctx.store` (the `Store`, or `MemoryStore` in tests); a source's
`options.time_budget_min` replaces the 10-minute budget of a normal run (`pubmed`: 15).

The registry loads parsers by name with `importlib.import_module(f"collectors.parsers.{name}")`, so adding a
parser never edits a shared file. Parsers raise `ParseError` when the page shape is unrecognisable, and must
never return a silently empty list for a page that loaded fine but changed. Return `[]` only when the page
genuinely lists nothing in range.

**SPC contract.** A2's entry point is `collectors/spc/run.py`:

```python
def run_spc(ctx: FetchContext, db: Db, ingredient_ids: list[str] | None = None, *,
            store: Store | None = None, notifier: Notifier | None = None) -> list[str]:
    # discovers spc_product rows per active ingredient and country, snapshots, diffs per section,
    # writes spc_snapshot / spc_change, and returns the ids of the issues it created (doc_type 'label_change')
```

The runner (A1) calls it on the `weekly` schedule, and for one ingredient when an admin confirms a new one.
Each SPC source gets a `source_run` row per run and a health like any other source (`blocked` on a bot
check, `degraded` after 2 failed runs in a row, with the admin health alert on the change). A module's
`discover` / `snapshot` raises when it could not read (an HTTP error, a missing section, an unknown shape);
it never returns `[]` or a partial snapshot for a failed read.

Error texts and logs never carry a secret: `collectors.core.context.redact` strips `api_key=`, tokens,
passwords and the Telegram bot token from every `FetchError` / `SourceBlocked` / `ParseError` message and
every `source_run.error`; `install_log_redaction()` (called by every entry point after `basicConfig`)
keeps httpx/httpcore at WARNING and redacts each log record.

## `sources.yaml` ids and parser names (A1 writes the file; these names are fixed)

| id | parser | owner |
|---|---|---|
| ema-dhpc | ema_dhpc | A1 |
| ema-psusa | ema_psusa | A1 |
| ema-news | generic_html (options in `sources.yaml`) | A2 |
| fda-medwatch | feed | A1 |
| fda-enforcement | openfda_enforcement | A1 |
| mhra-dsu, mhra-alerts | govuk | A1 |
| bfarm-rhb, pei-rhb | feed | A1 |
| basg-whatsnew | feed | A1 |
| aemps-feed | feed | A1 |
| aemps-dhpc | aemps_dhpc | A2 |
| basg-dhpc | basg_dhpc | A2 |
| hsa-announcements | feed | A1 |
| hc-recalls | hc_recalls | A1 |
| pubmed | pubmed | A1 |
| ansm-securite | ansm | A2 |
| aifa-sicurezza | aifa | A2 |
| hpra-notices | hpra | A2 |
| dkma-dhpc | dkma | A2 |
| noma-dhpc | noma | A2 |
| ima-dhpc | ima_is | A2 |
| infarmed-circulares | infarmed | A2 |
| lu-dhpc | lu_sante | A2 |
| swissmedic-hpc, swissmedic-updates | swissmedic | A2 |
| medsafe-dhcp, medsafe-comms, medsafe-prescriber-update | medsafe | A2 |
| bfarm-risk | bfarm_risk | A2 |
| pmda-revisions, pmda-urgent, pmda-msi, pmda-company-letters, pmda-proper-use, pmda-mhlw | pmda | A2 |
| mfds-letters | mfds | A2 |
| famhp-news | famhp | A2 |
| cbg-news | cbg | A2 |
| cbg-dhpc | cbg_dhpc | A2 |
| mpa-news | lakemedelsverket | A2 |
| tga-alerts, tga-updates | tga | A2 |
| fimea-email, tga-email | email_inbox | A2 |
| ema-prac, who-alerts, eda-eg, sfda-sa, jfda-jo, uae-mohap, uae-ede | prac / who_alerts / generic_html / ede | A2 |
| (user-added sources) | feed or generic_html | A1 / A2 |

The SPC sources are `spc-cima`, `spc-bdpm`, `spc-ema-epar`, `spc-dailymed`, `spc-mhra` and `spc-pmda`, with
`kind: spc`. Their modules sit under `collectors/spc/` (A2); A1 lists them in `sources.yaml`.

Every catalogue source also has `page:` (`SourceConfig.page_url`, stored in `source.page_url`, 0032): the
https page a person opens for it, never a feed or an API address: `registry.py` refuses a page that is not a
web address, and `tests/test_regulator_pages.py` refuses a feed or API page in any entry. The Sources screen
links there, and `new_items()` uses it in place of a feed item's own link. A source added in the app has no
page and links to its own address when that is not a feed.

The `options` keys a parser reads (`include_categories`, `include_keywords`, `doc_type`, `lang`, `selector`
…) are documented at the top of that parser's module.

## Platform tables and functions (C creates them in 0002_ops.sql; A1, A2 and B use them)

```sql
create table inbound_email (id uuid pk, source_id text references source(id), received_at timestamptz,
  from_addr text, subject text, r2_key text, text_body text, html_body text, processed_at timestamptz);
create table probe_result (id uuid pk default gen_random_uuid(), url text not null, requested_by uuid
  references person(id), requested_at timestamptz default now(), status text default 'queued'
  check (status in ('queued','running','ok','failed')), channel_detected text, parser_detected text,
  items jsonb, error text, finished_at timestamptz);
-- 0035: the NCBI searches the literature collector has run (written by the collector only; a team member reads).
create table literature_search (db text check (db in ('pubmed','pmc')), query text /* lower case */,
  kind text check (kind in ('name','class')), look_back_from date, history_until date,
  look_back_done_at timestamptz /* null: the 12-month look-back is not finished */, last_searched_at timestamptz,
  created_at timestamptz, primary key (db, query));
-- RPCs callable by a signed-in person:
create_link_token() returns text                          -- one-time Telegram code for the caller
archive_hit_count(p_term text, p_lang text) returns int   -- how many archived texts contain the term
```

**Sources screen (0032).** Read by anyone signed in; written only as stated:

```sql
create table regulator_page (id uuid pk, regulator_id text references regulator(id), kind page_kind
  -- 'database' | 'dhpc' | 'safety'
  , sort int, label text, url text, read_by text[] -- source ids; empty = not read by the app
  , partial boolean, note text, unique (regulator_id, url));   -- admins write; audited
create table country_look (id bigserial pk, person_id uuid, regulator_id text, looked_at timestamptz);
v_my_country_look (regulator_id, looked_at)                 -- the caller's latest look per authority
mark_country_looked(p_regulator text, p_seen_to timestamptz default null) returns timestamptz
  -- stamps every authority of that country for the caller at p_seen_to (the time the page read its list,
  -- 0056), never later than now(); now() without it; 42501 without a person, 22023 for an unknown authority
new_items(p_from timestamptz, p_to timestamptz default now()) returns table (document_id, source_id,
  regulator_id, regulator_name, country_name, country_code, source_kind, title_orig, lang, link,
  published_date, first_seen_at, doc_type, matched, r2_key, mime, email_id, email_r2_key)
  -- security invoker; documents first seen in [p_from, p_to). link is a page a person opens: a feed
  -- or API address becomes the source's page (else the authority's home page), an openFDA recall
  -- links to FDA's Enforcement Report, and an e-mail item has no link (email_id / email_r2_key instead)
```

A migration that changes her pages matches each row on (regulator, her address), so a page an admin has moved
is left alone (0038 sets `read_by`, `note` and, for a dead address, `url`). A page of kind `dhpc` or
`safety` with an empty `read_by` has a note starting "Not read:" that says why; a page whose address changed
keeps her address in its note. `tests/test_regulator_pages.py` applies 0038 over the 0032 seed and checks both.

Since 0098 (her feedback, 8 Nov 2026) an admin also writes her pages from the Sources screen
(`web/src/features/sources/PageEdit.tsx`, rules in `pageRules.ts`): **Add a link** and **Change** write `regulator_id`,
`kind`, `label`, `url` and `note` only, never `read_by` or `partial`, so a link she adds is one she opens herself;
**Remove** deletes the row. **Add a local reference** inserts a `regulator` (id from its short name, `languages`
`{en}`) and its first page. `regulator` is audited from 0098 (`audit_regulator_write`, and `audit_regulator_change`
only when a row really changes, so the collector's catalogue upsert logs nothing); `supabase/tests/sources_she_edits.sql`.

The feed rule (`(\.(xml|json|rss|atom)([?#]|$)|/(rss|feed|atom)(/|[?#]|$)|^https?://api\.)`, case-blind) is
the same in `new_items()`, `web/src/features/sources/horizontal.ts` and `tests/test_regulator_pages.py`;
the web test reads it from the migration. Subscription kind `new_items_digest` is the daily count of
`new_items()` per country (`collectors/alerts.py`, `new_items_digest_if_due`).

**Edge Functions** (all require a signed-in person; the web app calls them with `supabase.functions.invoke`):

| Function | Input | Output | Who may call |
|---|---|---|---|
| `ingredient-lookup` | `{q}` | `{candidates:[{inn_en, atc_code, wikidata_qid, rxcui, labels:{lang:label}, sources:[..], score}]}` | anyone signed in |
| `ingredient-lookup` (terms) | `{action:'terms', wikidata_qid, atc_code, inn_en}` | `{terms:[{lang, country_code, term, kind, mode, source}]}` | anyone signed in |
| `probe-source` | `{url}` | `{probe_id}` | admin. Fires `repository_dispatch` to `probe.yml`; the web app polls `probe_result`. |
| `archive-url` | `{r2_key}` | `{url}` | anyone signed in. Pre-signed R2 GET, valid 10 minutes. |
| `invite-person` | `{email, full_name, role}` | `{person_id}` | admin |
| `literature-search` | `{ingredient_id, from, to}` (days `YYYY-MM-DD`, publication dates, both included) | `{ingredient:{id, inn_en}, from, to, checked_at, queries:[{label, kind:'name'\|'class', pubmed:{count, url, error?}, pmc:{count, url, error?}}], note?}` | anyone signed in. Live NCBI counts (esearch, `retmax=0`, `datetype=pdat`) for the ingredient's English INN and each English class word, as the daily literature watch searches them; `url` opens the same search on the PubMed / PMC website (`count` equals the website's). `count` is null with `error` when that database did not answer. At most 20 searches. Nothing is stored. Web: `features/literature/useLiteratureSearch.ts`. |
| `telegram-webhook` | Telegram updates | — | Telegram only. Checks the secret-token header; handles `/start <code>`. |

## Drug classes and the check of the past (0034)

```sql
-- drug_class: + origin text ('atc' = made by collectors/classes.py from the ATC level-4 code | 'hand'),
--   wikidata_qid, confirmed_by uuid -> person, confirmed_at, created_at; audited.
-- class_term: + source ('seed' | 'wikidata' | 'who' | 'manual'), added_by -> person, changed_at, rematched_at.
-- ingredient_term: + changed_at, rematched_at.
-- changed_at is set by the database (trigger) on insert and whenever term, lang, mode or exclusions change,
-- and on every word of an ingredient that is watched again after a pause; a class's words also when an
-- ingredient that searches it is watched again, or a watched ingredient gets a searched link to it (0055).
-- A word is DUE while rematched_at is null or rematched_at < changed_at.
create table rematch_job (id uuid pk, trigger text ('daily'|'manual'), started_at, since date,
  ingredient_term_ids uuid[], class_term_ids uuid[], cursor_document_id uuid, documents_checked int,
  documents_reread int, documents_matched int, issues_created int, finished_at);  -- at most one open
-- RPCs, administrators only (security definer; errcode 42501 for anyone else):
add_class_term(p_class uuid, p_lang text, p_term text, p_mode match_mode default null) returns uuid
  -- trimmed, 2 to 200 characters; ja/ko/zh default to 'substring', others 'stem';
  -- source 'manual', added_by = the caller
remove_class_term(p_term uuid) returns void           -- P0002 when it is no longer there
confirm_drug_class(p_class uuid) returns timestamptz  -- confirmed_by = the caller, confirmed_at = now()
```

- `collectors/classes.py` never changes an existing class (same `code`); it only links ingredients to it.
  It writes classes with `origin = 'atc'` and words with `source` 'wikidata' or 'who'.
- `collectors/rematch.py` takes the due words of watched ingredients (and of classes linked to a watched
  ingredient) and checks the stored notices (not of `spc` or `literature` sources) dated from `since` and
  first seen before the job started, in id order. On reaching the end it sets `rematched_at = started_at` on
  the job's words whose `changed_at <= started_at`. Everything it creates is `is_backfill`: it never alerts
  and never reaches the digest. A class-only issue that a due class word already matched gains the
  ingredients that search the class now (`class_gap`); `rematch_documents` gives each issue its `ingredients`.
- Store methods (`collectors/core/store.py` and `memstore.py`): `rematch_open_job`, `rematch_due_terms`,
  `rematch_create_job`, `rematch_terms`, `rematch_documents`, `rematch_advance`, `rematch_finish`,
  `set_issue_names_ingredient`; for classes `ingredients_for_classes`, `drug_class_id`, `create_drug_class`,
  `link_ingredient_class`.

## The Ingredients screen (0039)

```sql
document_link(d document, s source, r regulator) returns text   -- immutable; the page a person opens:
  -- 'email:%' -> null (email_id / email_r2_key open it); api.fda.gov -> FDA's Enforcement Report
  -- (?Event=<structured.event_id>); a feed or API address, or an empty address -> the source's page_url,
  -- else the authority's homepage; otherwise the document's url. new_items() links with it.
-- RPCs for a member of the team (security definer with my_role(); 42501 for anyone else; 22023 when p_to is
-- before p_from or the range is over 366 days; P0002 for an unknown ingredient). Days are Cairo days, both
-- included; a notice's day is published_date, else first_seen_at in Cairo.
ingredient_screen(p_ingredient uuid, p_from date, p_to date) returns jsonb
  -- {ingredient:{id, inn_en, atc_code, active, classes:[{id, code, name_en, origin, relation, enabled}], names,
  --   name_languages, class_words, class_languages (enabled classes only, 0049)}, from, to,
  --  regulators:[{id, name, country_name, country_code, homepage, hers, runs, ok, failed, unread_page,
  --   pages:[regulator_page], sources:[{id, regulator_id, kind, channel, url, page_url, enabled, health, notes}],
  --   mentions:[mention]}],          -- every authority with pages of hers or a source not spc/literature;
  --                                  -- hers first, then country and name; runs of safety and recall
  --                                  -- sources, failures by source_run_failed(), never by run.trigger
  --  label_changes:[mention],        -- notices of spc sources
  --  literature:{papers, by_name, by_class, pubmed, pmc, by_query:[{query, kind, pubmed, pmc}], first:[paper]}}
  -- mention: {document_id, source_id, regulator_id, regulator_name, country_name, country_code, title, lang,
  --   link (document_link), email_id, email_r2_key, date, published_date, first_seen_at, doc_type,
  --   terms:[{text, lang}], by_class, relation ('name' | 'group' | 'manual' | 'parent', 0049), class_name (the
  --   class that found it, null for 'name'), is_backfill (the document's or its notice's), sections (spc only),
  --   issue_id (a link not 'suggested', its anchor first), issue_status, decision:{to_status, person, at, comment}}
ingredient_papers(p_ingredient uuid, p_from date, p_to date) returns table (document_id, title, lang, journal,
  day, pubmed_url, pmc_url, by_class, is_backfill, first_seen_at)
  -- papers of literature sources naming the ingredient or one of its classes; the name's papers first,
  -- newest first. The screen pages it 50 at a time.
```

Web: `web/src/features/screen/` (route `/ingredients/:id?from=&to=`); decisions are `review_event` inserts, the
only place the web app records one since the notice page was removed (November 2026). SQL test:
`supabase/tests/ingredient_screen.sql`.

Web routes (`web/src/app/routes.tsx`, tabs in `web/src/app/nav.ts`): `/ingredients`, `/ingredients/:id`,
`/sources`, `/reports`, `/people` (administrators), `/me`; `/` opens `/ingredients`. The addresses of the removed
screens (`REMOVED_PATHS`: notifications, issues, issue, signals, oversight, psur, labels) open `/`.

## The weekly report (0040)

```sql
screen_reader() returns boolean   -- security definer, revoked from public, anon and authenticated:
  -- my_role() is not null, or a direct database connection (no request.jwt.claims and no
  -- request.jwt.claim.sub). ingredient_screen_check() asks it, so ingredient_screen() and ingredient_papers()
  -- answer the report (SUPABASE_DB_URL) as they answer the screen; the service key and anyone signed in but
  -- not on the team are still refused (42501).
screening_log(p_from date, p_to date) returns table (source_id, regulator_id, regulator, country, country_code,
  source_kind, enabled, runs, ok_runs, failed_runs, items_seen, items_new, items_matched, last_run, last_failure)
  -- every source and its reads in those Cairo days, both included, at most 366 (22023 otherwise; 42501 for a
  -- non-reader); failures by source_run_failed(), never filtered by run.trigger. For a whole month it equals
  -- monthly_screening_log(), which stays for the monthly reports already made.
weekly_report (id, week_start date unique -- a Sunday, week_end = week_start + 6, xlsx_r2_key, xlsx_sha256,
  pdf_r2_key, pdf_sha256, made_at, git_sha, made_by_run)
  -- written only by the collector (upsert on week_start); read by a member of the team; audited.
```

Collector: `python -m collectors.report [--week YYYY-MM-DD | --month YYYY-MM] [--dry-run]`
(`collectors/report_weekly.py`, template `report_templates/weekly.html`; the default is the last complete week).
Web: Reports (`web/src/features/reports/`, `weeks.ts`). `archive-url` serves a key a `weekly_report` row points
at. SQL test: `supabase/tests/weekly_report.sql`; Python: `tests/test_report_weekly.py`.

## The five-day clock (0041, 0050)

```sql
app_setting eda_days = '5', eda_day_zero = '"first_seen"'   -- jsonb; or '"decision"'
authority_report (id, issue_id, authority 'EDA', sent_on date, reference, note, person_id, decision_id -> review_event,
  created_at, withdrawn_at, withdrawn_by, withdraw_reason)
  -- append-only: the team reads (never service_role, 0050); a reviewer or administrator inserts their own row
  -- (sent_on never after today in Cairo and never before day zero, 22023); the trigger refuses 'PH409'
  -- 'NO_CONCERN …' when the notice's latest decision is not relevant and 'PH409' 'ALREADY_SENT …' when that
  -- decision was reported already, and names the decision (decision_id). Update and delete are refused
  -- ('… append-only'); only withdraw_authority_report() writes.
withdraw_authority_report(p_id uuid, p_reason text) returns void
  -- security definer; a reviewer or administrator; reason required (22023); P0002 when unknown or withdrawn.
eda_clock(p_issues uuid[]) returns table (issue_id, ingredient_id, ingredient, title, country, regulator,
  day_zero, due, days_left, clock, decided_at, decided_by, sent_id, sent_on, sent_reference, sent_note, sent_by)
  -- the collector's (null = every notice whose status and latest decision are relevant); not for authenticated
  -- nor service_role (0050).
finding_state(p_issues uuid[]) returns jsonb
  -- the screen's: {"<issue_id>": {day_zero, due, days_left, clock, sent}} with clock running | late | sent | off
  -- and sent {id, on, reference, person, note} or null; {} for nothing or unknown ids; screen_reader() or 42501.
  -- day_zero = Cairo day of issue.created_at, the day PHAROS first showed the notice (0050; or of the decision
  -- when eda_day_zero = decision); due = day_zero + eda_days; days_left counts from signal_cairo_today(),
  -- negative when late. off when the latest decision is not relevant. sent = the latest authority_report not
  -- withdrawn for the notice, whatever decision it was recorded under (never forgotten, 0050), even while off;
  -- clock = sent whenever one exists and the latest decision is relevant.
v_eda_clock  -- eda_clock(null) where clock in ('running', 'late'); the collector's reminder reads it on the
  -- direct connection; revoked from public, anon, authenticated and service_role (0050).
latest_decision(p_issue uuid) returns review_event   -- the guard's and eda_clock's own; nobody else (0050).
```

Collector: `collectors/reminders.py` (`remind_if_due`, kind `escalation`, from 07:00 Cairo, once a day, findings
late or due within 2 days; `run.py` calls it after the new-items digest). Store: `reminder_people()`,
`eda_reminders(today, within_days)`. Web: `web/src/features/screen/clock.ts`, `DecisionButtons.tsx`,
`styles/clock.css`. SQL test: `supabase/tests/eda_clock.sql`; Python: `tests/test_reminders.py`.

## Signal steps inside the finding (0042)

```sql
app_setting signal_auto_open = 'true'   -- jsonb boolean; false: Concerns us opens nothing
open_signal_as(p_issue uuid, p_title text, p_ingredient uuid, p_person uuid, p_comment text default null) returns uuid
  -- the one code path that opens a signal: open_signal()'s checks and rows (signal, signal_issue, signal_event
  -- 'opened' naming the notice) for a named person; granted to nobody (42501 for every API role).
  -- open_signal() = open_signal_as(…, signal_require_reviewer(), …), signature and grants unchanged.
signal_take_step_as(p_person uuid, p_signal, p_step, p_from_stage, p_comment, p_priority, p_outcome, p_owner, p_due)
  -- signal_take_step()'s body for a named person; granted to nobody. signal_take_step() keeps its signature,
  -- grants and guards: 42501 for a reader, 'PH409' 'STALE_SIGNAL …' when p_from_stage is not the stage now.
trigger review_event_zz_open_signal  -- after insert on review_event, sorts after review_event_apply
  -- to_status = relevant, signal_auto_open true, no signal_issue for the notice → open_signal_as(issue, the
  --   notice's title, its single ingredient or null, new.person_id, 'Opened when the notice was marked Concerns
  --   us[: comment]'). A notice with a signal (open or closed) opens no second one.
  -- to_status = not_relevant and the notice's signal is at validation with no step beyond opened / notice_linked
  --   / note → signal_take_step_as(new.person_id, …, 'not_validated', 'validation', 'Decision changed: <comment
  --   | no reason given>'); otherwise the signal is left as it is.
  -- A failure in either is a warning in the log; the decision is never refused.
finding_state(p_issues uuid[]) returns jsonb   -- as 0041/0050, plus per notice
  -- signal: null | {id, ref, title, stage, priority, outcome, next_step, next_due, overdue, owner, opened_at,
  --   opened_by, steps: [{step, from_stage, to_stage, priority, outcome, person, at, comment}]}
  -- next_step = validated | assessed | action_done by stage, null when closed; next_due and overdue are
  -- v_signal_table's (the current stage's due day; late when before signal_cairo_today()); steps in order.
```

Collector: the morning reminder (`collectors/reminders.py`) adds, after the findings, the signal steps late or due
within 2 days: store `signal_reminders(today, within_days)` reads `overdue_items(today + within + 1)` kind
`signal` joined to `v_signal_table` (`signal_id, ref, title, ingredient, ingredient_id, stage, next_due,
days_left`). Weekly report: `signal_cell()` on each decision row and each mention ("SIG-2026-001 · Validation ·
due 5 Dec 2026"), summary "Signals open: N (M steps late)" from `v_signal_table`. Web:
`web/src/features/screen/signalSteps.ts`, `SignalSteps.tsx` (rendered by `DecisionButtons` when
`finding.signal` exists; `rpc('signal_take_step', {…, p_from_stage: signal.stage})`, then `finding_state` for the
notice and `withSignal` on the screen's cache; PH409 reloads like a stale decision), `styles/signal-steps.css`.
SQL test: `supabase/tests/signal_in_finding.sql`; vitest `signalSteps.test.ts`; Python `tests/test_reminders.py`,
`tests/test_report_weekly.py`.

## Our label under Label changes (0043)

```sql
spc_product.is_reference boolean not null default false   -- one per ingredient (partial unique index)
set_reference_product(p_product uuid, p_on boolean) returns void
  -- security definer; a reviewer or administrator (42501); P0002 for an unknown product; on = true clears the
  -- other product of the same ingredient. Audited (audit_spc_product_reference, on the column only).
label_gap (id, spc_change_id -> spc_change cascade, our_label_id -> our_label cascade, gap jsonb, computed_at,
  unique (spc_change_id, our_label_id))
  -- the collector's (direct connection) to write; the team reads (RLS my_role() is not null); anon nothing.
  -- gap: {lang_match, our_lang, their_lang, covered, partly, missing,
  --       sections: [{section, our_section, our_text, covered, partly, missing,
  --                   added: [{sentence, status covered|partly|missing, score 0–1, closest|null}]}]}
  -- lang_match false -> sections []. Only sections 4.1–4.9 (US and Japanese headings mapped) are compared.
label_changes(p_ingredient uuid, p_from date, p_to date) returns jsonb
  -- ingredient_screen_check() as 0039/0040 (team or the report's direct connection; 22023 days; P0002).
  -- The changes DETECTED in the Cairo days (spc_change.created_at), the reference product first, then newest:
  -- [{change_id, detected_at, detected_day, label_date, previous_label_date,
  --   product: {id, name, mah, country_code, country_name, source_id, regulator_id, regulator_name, url,
  --             is_reference},
  --   lang (document.lang, else source.languages[1]), link (document_link, else product url, source page,
  --   homepage), document_id, title, sections, diff (as stored), gap (label_gap.gap for the newest current
  --   version of our label, else null), gap_at, our_label: {id, product_name, version, lang, uploaded_at,
  --   uploaded_by (name)} | null, issue_id, issue_status, is_backfill, decision: {to_status, person, at, comment}}]
```

Collector: `collectors/labels/gap.py` (the check, pure), `collectors/labels/recompute.py` (`gap_for_change` when
`collectors/spc/run.py` records a change; `recompute_gaps` after the SPC step of every normal run: the changes of
the last 365 days with no row for a current version of our label, 500 per run). Weekly report: `gather_week`
reads `label_changes()` per ingredient; `gap_summary()` words the gap. Web: `web/src/features/screen/LabelChanges.tsx`,
`OurLabel.tsx`, `labelText.ts` (the section splitter), `queries.ts` (`useLabelChanges`, key
`['label-changes', id, from, to]`; its `label_changes` Mentions carry `document_id = change_id` so
`DecisionButtons` works unchanged), `web/src/lib/pdfText.ts`, `styles/labels.css`. SQL test:
`supabase/tests/label_changes.sql`; Python: `tests/test_label_gap.py`, `tests/test_label_recompute.py`.

## Case reports in the literature (0044)

```sql
paper_state(p_documents uuid[]) returns jsonb   -- security definer, screen_reader() (42501 otherwise); at most
  -- 1,000 ids (22023); {} for none. Keyed by document id (an unknown id has no entry):
  -- {issue_id, issue_status, decision:{to_status, person, at, comment},   -- as a mention's in ingredient_screen()
  --  case_report: {reason: 'pubtype' | 'title'} | null,   -- structured.case_report, else judged on the fly
  --  day_zero, due_serious, due_nonserious}                -- Cairo day of first_seen_at, +15, +90
mlm_monitored(p_ingredient uuid) returns boolean   -- a row in mlm_entry; same reader check
-- 0044 also sets structured.case_report on every literature document stored before it. ingredient_screen()
-- 0097: a flag is kept only when the title or abstract names the ingredient (collectors/case_names.py): else
-- structured.case_report is JSON null, case_report_was the old flag, names_checked the Cairo day of the check;
-- v_case_report follows structured.case_report too. Store.case_reports_unchecked(limit), mark_case_names(kept,
-- cleared, day).
-- reads ingredient_papers() by column position: never widen that function; add a function instead.
```

Collector: `structured.case_report` is set by `collectors/parsers/pubmed.py` (`case_report(pubtype, title)`);
`Store.case_report_papers_since(since)` feeds the daily message's block (`collectors/alerts.py`,
`Notifier.digest_if_due`); `collectors/mlm.py` fills `mlm_entry` daily. Web: `web/src/features/screen/papers.ts`
(pure), `paperState.ts` (hooks), `styles/papers.css`. SQL test: `supabase/tests/case_reports_screen.sql`; Python:
`tests/test_pubmed_ncbi.py`, `tests/test_alerts.py`, `tests/test_store_pg.py`, `tests/test_report_weekly.py`,
`tests/test_mlm.py`, `tests/test_case_names.py`.

## Any ingredient she adds is covered (0045)

```sql
ingredient_readiness(p_ingredient uuid) returns jsonb
  -- security definer; screen_reader() or 42501; P0002 for an ingredient not on the watchlist; execute for
  -- authenticated only (revoked from public and anon). One answer for the Ingredients page and the weekly report:
  -- {names:       {languages_with_a_name, of, missing: [lang]},      -- kind 'code' is not a name; of = every
  --                                                                 -- language of every regulator
  --  class:       {atc, classes, words, confirmed},                 -- classes = every linked class; words, the
  --                                                                 -- past check and NCBI count only the classes
  --                                                                 -- searched (ingredient_class.enabled, 0049)
  --  past_check:  {done, words_due, job_running},                   -- due: rematched_at null or < changed_at
  --  ncbi:        {searches, expected, look_back_done, last_run},   -- expected = 2 × (name ∪ English class words)
  --  europepmc:   {watched, searches, expected, look_back_done, last_run},  -- 0082: db 'europepmc', expected =
  --                                                                 -- 1 × the same words; watched = source
  --                                                                 -- 'europepmc' enabled
  --  label_watch: {products, by_source: {<source_id>: {country, regulator, products, read}},
  --                waiting: [country], empty: [country], first_snapshot, japan_code},
  --                -- enabled spc sources only; read = a source_run since ingredient.created_at that
  --                -- source_run_failed() does not call a failure; waiting = countries with an unread source;
  --                -- empty = read, no active spc_product; japan_code = an ingredient_term kind 'code', JP
  --  eurd:        {found, list_read, frequency, dlp, next_submission},  -- the substance alone before a combination
  --  ema_mlm:     {monitored},
  --  telegram:    {people: [full_name]},   -- active, telegram linked, subscription 'ingredient' for all or this one
  --  ready}
  -- ready = a name in ≥1 language ∧ (no ATC ∨ classes > 0) ∧ past_check.done ∧ ncbi.look_back_done
  --         ∧ (¬europepmc.watched ∨ europepmc.look_back_done)
  --         ∧ (products > 0 ∨ waiting = []) ∧ telegram.people ≥ 1.  japan_code, eurd and ema_mlm never hold it back.
subscription (Dr Sama, kind 'ingredient', ingredient_id null)  -- inserted by 0045 by her address, once (as 0033)
```

Her words, shared by `web/src/features/ingredients/readiness.ts` and `collectors/report_weekly.py`
(`readiness_items`, `readiness_text`; `tests/test_report_weekly.py` holds both to the same phrases): `Ready`, or
`Still preparing: ` + items joined by ` · ` in this order: `no name to look for yet`, `class words waiting`
(an ATC code and no class yet),
`check of the past running` | `waiting`, `PubMed look-back running` | `waiting`, `Europe PMC look-back running` |
`waiting` (only while it is watched), `label watch on Monday (A, B)`
(up to three country names, else `n countries`), `nobody receives its Telegram messages yet`.

Collector: `collectors/eurd.py` (daily, `collect.yml` step "EURD list"; `eurd_entry` as 0028). Web:
`Readiness.tsx` (rpc `ingredient_readiness`, query key `['ingredient-readiness', id]`), `readiness.ts`,
`styles/readiness.css`; the Japan code is an `ingredient_term` kind `code`, lang `ja`, country `JP`, mode `exact`,
source `pmda` (`TermEditor.tsx`). SQL test: `supabase/tests/ingredient_readiness.sql`; Python: `tests/test_eurd.py`,
`tests/test_report_weekly.py`; web: `readiness.test.ts`.

## Inspection evidence (0046, 0047)

```sql
audit_log  -- append-only (0046): trigger audit_log_no_change (before update or delete, each row) and
  -- audit_log_no_truncate (before truncate) raise 42501 "The audit log is never changed or removed." for every
  -- role, the owner included; update, delete, truncate revoked from public, anon, authenticated, service_role.
  -- audit_row() inserts as before. Nothing may update, delete or truncate it (no retention job exists).
sign_kind  -- + 'weekly_report', 'pack' (0046; used from 0047 on).
record_fingerprint(p_kind sign_kind, p_id uuid) returns text   -- 0047, same signature and grants, now plpgsql:
  -- null for someone not on the team; monthly_report and weekly_report: sha256(pdf_sha256 || ':' || xlsx_sha256)
  -- as hex; signal as 0030; pack: as the reports, from report_request (0048; null until the pack is made).
sign_record(p_kind, p_id, p_meaning sign_meaning, p_comment) returns uuid   -- 0047, same signature and grants:
  -- weekly_report (and pack): reviewer or admin, either meaning (reviewed / approved); monthly_report: admin;
  -- signal: reviewer or admin, once closed. Password sign-in in the last 300 s (amr) or 28P01; the same person,
  -- meaning and fingerprint once (23505); sign_off append-only and audited (0030).
```

Web: Reports (`web/src/features/reports/ReportsPage.tsx`, `FileHash.tsx`), `web/src/features/signoff/`
(`SignOff.tsx`: query key `['sign-off', kind, id]`, reads `sign_off` and `record_fingerprint`; `signoff.ts`:
`shortHash`, `signatureState`, `STATE_LABEL` "Fingerprint matches" / "File changed since signing",
`defaultMeaning`), `styles/signoff.css`. Workflow: `db-backup.yml` verify-archive samples 50 originals plus 10
`weekly_report` / `monthly_report` / made `report_request` (pack) files. SQL test: `supabase/tests/sign_off_weekly.sql`; web: `signoff.test.ts`.

## Packs on request (0048)

```sql
report_request (id uuid, kind text 'psur'|'inspection', ingredient_id uuid (psur only, required there),
  from_day date, to_day date (Cairo days, both included, at most 5 years), requested_by uuid → person,
  requested_at, status text 'queued'|'building'|'done'|'failed', error text (the reason, or a note while it
  waits), attempts int, started_at, pdf_r2_key, pdf_sha256, xlsx_r2_key, xlsx_sha256, made_at (all five
  required when done), git_sha, made_by_run)
  -- unique (kind, ingredient, from_day, to_day) while queued or building (report_request_one_waiting).
  -- The team reads a PSUR pack, an admin an inspection pack too (my_role() is not null and (kind = 'psur' or
  -- my_role() = 'admin')); archive-url follows it (the caller's session); no write for anon or authenticated;
  -- service_role holds nothing;
  -- audited (audit_row). The collector writes on its direct connection (the owner).
request_report(p_kind text, p_ingredient uuid, p_from date, p_to date) returns uuid   -- security definer:
  -- reviewer or admin (42501), an inspection pack admin only (42501); kind, ingredient and days checked (22023;
  -- an unknown ingredient P0002; more than five years or a first day after signal_cairo_today() 22023). The same
  -- pack still waiting: its id. Otherwise 22023 when the caller already has 2 queued or building, or 5 are in all.
record_fingerprint('pack', id)   -- sha256(pdf_sha256 || ':' || xlsx_sha256) of the request; null until made,
  -- and null for an inspection pack unless the caller is an admin,
  -- so sign_record('pack', …) refuses a pack not made (22023) and signs a made one as a weekly report.
```

Collector: `collectors/report_pack.py` (`python -m collectors.report_pack [--dry-run]`; `--waiting` prints the
count), templates `report_templates/pack_base.html`, `pack_macros.html`, `psur.html`, `inspection.html`.
`Store`: `report_requests_waiting()`, `claim_report_request()` (the oldest queued, or building for over 2 hours;
`for update skip locked`; attempts + 1; returns `requested_by_name`, `ingredient_name`),
`finish_report_request()`, `fail_report_request()`, `requeue_report_request()`; `MemoryStore` the same plus
`add_report_request()`. Archive keys `reports/packs/<kind>/<id>/<stem>.pdf|.xlsx` (`put_named(revise=True)`);
`archive-url` serves them. Telegram kind `report`, to the requester (`reminder_people()`) and `admins()`; an
inspection pack to `admins()` only. `SIGNATURES_SQL` (the inspection pack's signatures) computes each record's
fingerprint now as `record_fingerprint()` does, signals included.
Workflow: `collect.yml` steps "Packs waiting?" and "Packs on request" (last; `!cancelled()`; never on a dry run;
20 minutes; never weekly or classes). Web: `web/src/lib/psur.ts` (`frequencyMonths`, `intervalFor`), `features/reports/packs.ts`,
`Packs.tsx` (query key `['report-requests']`), `styles/reports-packs.css`. Tests: `tests/test_report_pack.py`,
`tests/test_store_pg.py`, `supabase/tests/report_request.sql`, `packs.test.ts`, `psur.test.ts`.

## The search profile: groups, the class above, groups by hand (0049)

```sql
-- ingredient_class: + relation text not null default 'group' ('group' = its ATC level-4 group | 'parent' = the
--   level-3 class above it | 'manual' = a group given by hand), enabled boolean not null default true,
--   changed_at; audited. On 0049 every link of a class with origin 'hand' became 'manual'; everything else
--   'group', enabled. A link inserted by hand to a class with origin 'hand' is 'manual' (trigger).
-- Switching a link from off to on sets changed_at on every word of the class (trigger
-- class_search_enabled_again): the check of the past and the literature look-back run for it.
-- Everything that searches reads ENABLED links only: Store.load_terms, class_ingredients, class_words,
-- rematch_due_terms; literature-search; report_weekly SEARCHES_SQL; ingredient_screen's class_words,
-- class_languages and literature searches. A link that is off still shows on the Ingredients page and screen.
-- RPCs, administrators only (security definer; 42501 for anyone else):
set_class_search(p_ingredient uuid, p_class uuid, p_enabled boolean) returns void   -- P0002 when not linked
add_search_group(p_ingredient uuid, p_name_en text) returns uuid
  -- trimmed, 2 to 120 characters; 22023 when the name looks like an ATC code (groups by hand are named in
  -- words); reuses a class with the same name (case-insensitive) else inserts origin 'hand' with a code made
  -- from the name; links it 'manual' (an existing link of any relation is switched on, never downgraded)
unlink_search_group(p_ingredient uuid, p_class uuid) returns void
  -- 'manual' links only: 22023 for a link from the ATC code (switch it off instead), P0002 when not linked
-- Not callable by the app:
ingredient_match_relation(p_ingredient uuid, p_document uuid) returns text
  -- how a document was found for an ingredient: 'name' (its own names) > 'group' > 'manual' > 'parent';
  -- null when nothing matched. 'parent' is a class-level signal to assess, not a group match.
```

- The search mode on the Ingredients page is DERIVED, never stored: no class on (or none) = *Ingredient only*;
  every class on = *Ingredient + groups*; some = *Custom* (`web/src/features/ingredients/searchProfile.ts`:
  `profileMode`, `profileWords`, `switchesFor`; reusable by any screen).
- `collectors/classes.py` links the level-4 group ON and the level-3 class above it OFF (`relation 'parent'`);
  it never changes a class or a link that exists, so a switch set by hand stays. Manual run: *Actions ->
  PHAROS collect -> Run workflow -> classes* runs only this step.
- Store: `link_ingredient_class(ingredient_id, class_id, *, relation='group', enabled=True)` (on conflict
  nothing); `memstore.set_class_search(ingredient_id, class_id, enabled)`.

## Notices only: a class kept out of the literature search (0051)

```sql
-- ingredient_class: + literature boolean not null default true (default false and every link false since 0093:
--   the literature is searched for names); audited; dated in changed_at like enabled
--   (trigger ingredient_class_relation). Every link existing on 0051 stays in the literature.
-- It counts only while enabled. enabled and literature = the class's English words are also searched on PubMed
-- and PubMed Central; enabled and not literature = its words are matched in notices only (every language).
-- Readers of ENABLED AND LITERATURE: Store.class_words (the daily NCBI watch, collectors/parsers/pubmed.py),
-- literature-search, report_weekly SEARCHES_SQL, ingredient_screen's literature searches, ingredient_readiness
-- ncbi (expected and look_back_done). Everything else that 0049 lists still reads enabled alone: load_terms,
-- class_ingredients, rematch_due_terms, the screen's class_words and class_languages, readiness class words.
-- Switching literature never makes a word due for the check of the past. Papers already found are kept; a word
-- back in the literature after STALE_DAYS is looked back on again, after less its days are caught up.
set_class_literature(p_ingredient uuid, p_class uuid, p_on boolean) returns void
  -- administrators only (security definer; 42501 for anyone else); P0002 when not linked; null = true
```

- `ingredient_screen` classes gain `literature`; the screen's head says "NSAID (notices only)".
- Web: `ClassLink.literature`; the class line's second switch **In the literature search** / **Notices only**
  (administrators, shown while the class is searched); `profileWords` marks the English words of such a class
  `notInLiterature`. Store twin: `memstore.set_class_literature(ingredient_id, class_id, on)`.

## The Japan code of an ingredient that exists (0052)

```sql
set_japan_code(p_ingredient uuid, p_code text) returns text
  -- security definer; administrators only (as save_ingredient and the ingredient_term policy), 42501 for anyone
  -- else; P0002 for an ingredient not on the watchlist; 22023 unless upper(trim(p_code)) matches isJapanCode
  -- (readiness.ts): ^[0-9]{4}[0-9A-Z]{3}([0-9A-Z]{5})?$. Stores the first 7 characters as an ingredient_term
  -- lang 'ja', country 'JP', kind 'code', mode 'exact', source 'pmda', verified_by = the caller; deletes the
  -- ingredient's other JP code terms; touches no other term; returns the stored code. Audited by
  -- audit_ingredient_term (0001). A new code is due for the check of the past (term_changed_at, 0034); the same
  -- code again is not. Execute for authenticated only (revoked from public and anon).
```

The screen no longer calls it; it keeps its meaning for any other caller (0069).

## Several Japan codes for one ingredient (0069)

PMDA files one ingredient under one 一般名 code per form (paracetamol: 1141007 tablets, 1141700 suppositories,
1141400 injection). Japan's label watch reads every JP code term (`collectors/spc/pmda_pi.py`, `SQL_TERM_CODES`).

```sql
set_japan_codes(p_ingredient uuid, p_codes text[]) returns text[]
  -- security definer; administrators only, 42501 for anyone else; P0002 for an ingredient not on the watchlist.
  -- Each element trimmed and upper-cased, blanks skipped; 22023 naming every element that does not match
  -- isJapanCode, and 22023 for a list with no code (it would remove every code). Each code is stored as its first
  -- 7 characters, once: an ingredient_term lang 'ja', country 'JP', kind 'code', mode 'exact', source 'pmda',
  -- verified_by = the caller. The ingredient's JP code terms not in the list are deleted; a code it already had
  -- keeps its row (not due again for the check of the past, 0034); touches no other term; returns the stored
  -- codes in order. Audited by audit_ingredient_term (0001). Execute for authenticated only.
```

Web: `JapanCodeField.tsx` (the field: one or several codes, separated by commas, spaces, new lines, 、 or ;
shared by `TermEditor.tsx`, one draft term per good code, and `JapanCodeEdit.tsx`), `JapanCodeEdit.tsx` (the open
row of the Ingredients page, administrators; `set_japan_codes`; invalidates `['ingredients']` and
`['ingredient-readiness', id]`), `japanCode.ts` (`japanCodeOf`, `japanCodesOf`, `currentJapanCodes`,
`sameJapanCodes`, `pmdaGeneralListUrl`). SQL tests: `supabase/tests/japan_code.sql`, `supabase/tests/japan_codes.sql`;
web: `japanCode.test.ts`.

## The product list and cases by product (0099)

A product of ours combines one or more watched ingredients, each in its own amount per strength (Carvexa:
carvedilol + ivabradine, 6.25 mg / 5 mg and 12.5 mg / 7.5 mg). A case is reported against a product and its
strength; the literature, the label watch, the weekly report and the readiness stay per ingredient.

```sql
product (+ dosage_form text, active boolean not null default true, created_by uuid → person)
  -- unique on lower(trim(name)); 0001's policies (team read, admin write) and audit trigger
product_strength (id, product_id → product on delete cascade, label text, sort int, unique (product_id, label))
product_strength_part (strength_id, product_id, ingredient_id, amount numeric > 0,
                       unit text default 'mg' in ('mg','g','µg','mL','IU','%'))
  -- pk (strength_id, ingredient_id); fk (strength_id, product_id) → product_strength (id, product_id) and
  -- fk (product_id, ingredient_id) → product_ingredient: the ingredient is one of the product's.
  -- Both tables: RLS team read, admin write; audited.
product_strength_label(p_strength uuid) returns text
  -- "6.25 mg / 5 mg": trim_scale(amount) || ' ' || unit in the order of the ingredients' inn_en, joined ' / '.
save_product(p jsonb) returns jsonb   -- {id, outcome: 'saved' | 'archived' | 'deleted'}
  -- security definer; administrators only (42501). p = {id?, name, mah?, dosage_form?, active?,
  -- ingredients: [ingredient id], strengths: [{id?, label?, parts: [{ingredient_id, amount, unit?}]}]}, or
  -- {id, remove: true}. 22023: no name, no ingredient, an ingredient not on the watchlist, no strength, a
  -- strength without exactly one amount above zero per ingredient, an unknown unit, a strength left off the list
  -- that a case names. 23505: a name already on the list, two strengths with one label. A strength without a
  -- label is named by product_strength_label(). Remove: archived (active = false) when a case names the
  -- product, else deleted with its strengths.

safety_case (+ product_id uuid → product, product_strength_id uuid; fk (product_strength_id, product_id) →
             product_strength (id, product_id); check product_strength_id is null or product_id is not null)
create_upload_case(p_file_name, p_mime, p_sha256, p_bytes, p_day_zero, p_ingredient uuid default null,
                   p_product uuid default null, p_strength uuid default null) returns uuid
save_case(p_case, p_seen, p_data, p_serious, p_ingredient, p_comment,
          p_product uuid, p_strength uuid) returns timestamptz   -- no defaults: an old tab's call fails, never clears the product
confirm_case(… the same …) returns timestamptz
  -- 0059's rules, and: a strength needs its product; a product must be on the list (an archived one only when
  -- the case already names it); the strength must be the product's; an ingredient given with a product must be
  -- in it. The case keeps the ingredient given, else the product's own when it has a single ingredient.
  -- confirm_case needs a product OR an ingredient ('Choose the ingredient or the product the case is about.').
case_check_form(p_data, p_ingredient) also refuses a products[] element that is not an object, or whose
  ingredients is not an array.
v_case_table (+ product_id, product_strength_id, product text)   -- product = name || ' ' || strength label
ingredient_coded_terms(p_ingredient)
  -- a case counts for the ingredient when safety_case.ingredient_id is it OR the case's product contains it.
```

The case form: each `products[]` element gains `ingredients: [{name, amount, unit}]` beside the kept
`active_ingredient` (`caseForm.ts` `ProductIngredient`, `collectors/cases/schema.py` `INGREDIENT`, checked by
`case_check_form`). The minimum criterion "a suspect product" is unchanged: a suspect line with a name. The
E2B(R3) file writes one `ingredient` (G.k.2.3.r) per element under the product's `kindOfProduct`, with
`quantity/numerator` value and UCUM unit (G.k.2.3.r.3a/3b: mg, g, ug, mL, [iU], %) and `ingredientSubstance/name`
(G.k.2.3.r.1); a product without `ingredients` keeps its one `active_ingredient`. `e2b.py problems()` and
`caseForm.ts e2bProblems()` refuse an ingredient line with an amount but no name, an amount that is not a number
above zero, or a unit outside the map.

Edge function `case-intake` `upload`: `product_id?`, `strength_id?` (uuids; a strength without a product is 400).
Reader (`collectors/cases/read.py`): the active products (and the case's own) go in the prompt
(`products_line()`); `guess_product()` takes the one product the suspect lines name by brand, else by every one of
its ingredients (the product with the most ingredients wins; a tie is left to the reviewer); its only strength is
taken only when the brand is named. `fill_product_line()` puts each ingredient with its amount on the suspect line.

Web: `web/src/features/products/` — `productForm.ts` (`toProduct`, `strengthLabel`, the draft, `toPayload`, the pick
`p:<id>`/`i:<id>`, `suspectLine`, `withSuspect`), `useProducts.ts` (`['products']`), `ProductPick.tsx` (the
"Product or ingredient" and "Strength" choices, on New case and the case page), `ProductsPage.tsx` (the Products
tab, `/products`, beside Ingredients). SQL test: `supabase/tests/product_list.sql`; web: `productForm.test.ts`,
`caseForm.test.ts`; Python: `tests/test_cases.py`.

## Removing an ingredient or a source (0100)

```sql
remove_ingredient(p_id uuid) returns jsonb   -- {outcome: 'deleted' | 'paused', name, reasons: [text]}
  -- security definer; administrators only (42501); P0002 when it is not there. Deleted (its terms, classes and
  -- gathered figures cascade) only when no match, issue_ingredient, signal, safety_case, report_request,
  -- spc_product, spc_listing, our_label or product_ingredient row names it; else active = false and the reasons.
remove_source(p_id text) returns jsonb       -- {outcome: 'deleted' | 'switched_off'}
  -- security definer; administrators only (42501); P0002 when it is not there; 22023 for origin 'catalogue'.
  -- Deleted with its source_run rows (filtered_item and list_check cascade) when no document, inbound_email,
  -- spc_product or spc_listing row names it; else enabled = false.
```

Web: `RemoveIngredient.tsx` and `removeIngredient.ts` (the answer's words) under `features/ingredients/`;
`SourceEdit.tsx` (`ChangeSource`: kind, schedule, notes of an origin 'user' source; `RemoveSource`) under
`features/sources/`. SQL test: `supabase/tests/remove_ingredient_and_source.sql`.


## Environment / secrets

| Secret | Used by |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | web; functions |
| `SUPABASE_SERVICE_ROLE_KEY` | functions |
| `SUPABASE_DB_URL` | collectors |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | collectors; archive-url; case-intake |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_BOT_USERNAME` | collectors; webhook |
| `GITHUB_DISPATCH_TOKEN`, `GITHUB_REPO` | probe-source; case-intake |
| `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID` (repository **variables**, with `id-token: write`) | collectors/cases and collectors/coding: the Claude reader (case-read.yml and the "Cases" step of collect.yml) signs in by federation, no key stored (`collectors/core/claude.py`). Without them cases wait unread and the run warns. `ANTHROPIC_API_KEY` is only for running a collector by hand |
| `PHAROS_E2B_SENDER`, `PHAROS_E2B_RECEIVER` | collectors/cases/e2b.py (optional: the sender and receiver identifiers in the E2B(R3) file; default `SATOPHARMA` and `EDA`) |
| `NCBI_API_KEY` | pubmed; literature-search (optional: 10 NCBI requests a second instead of 3) |
| `ADMIN_TELEGRAM_CHAT_ID` | pg_cron watchdog (stored in Supabase Vault) |
| `PHAROS_IMAP_HOST`, `PHAROS_IMAP_PORT`, `PHAROS_IMAP_USER`, `PHAROS_IMAP_PASSWORD` | collectors (Fimea/TGA newsletters in pharos@satopharma.com). satopharma.com mail is Turbify (Yahoo MX `mx-biz.mail.am0.yahoodns.net`), so it uses Yahoo/Turbify IMAP with a per-mailbox app password. |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | deploy-web |
| `SUPABASE_PROJECT_REF`, `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD` | deploy-supabase |
| `SITE_URL`, `CONTACT_EMAIL` | auth redirects; HTTP contact (also the contact in `collectors/classes.py`'s User-Agent; default pharos@satopharma.com) |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_TELEGRAM_BOT_USERNAME` | web build (from the GitHub secrets SUPABASE_URL, SUPABASE_ANON_KEY, TELEGRAM_BOT_USERNAME) |
| `BACKUP_AGE_RECIPIENT` | db-backup (optional age public key(s); the nightly backup is encrypted to it) |
| `DISPATCH_TOKEN` | GitHub forbids secret names starting `GITHUB_`; deploy-supabase copies it into the function secret `GITHUB_DISPATCH_TOKEN` |

`SUPABASE_DB_URL` is the **session-pooler** URI, because GitHub runners have no IPv6.

When the R2 variables are absent, the collectors archive to `./.archive/` (tests and dry runs). When
`SUPABASE_DB_URL` is absent, the collectors cannot run except in fixture tests.

## Working rules for every builder

- **No local installs, builds, typechecks, test runs or dev servers.** The owner's PC is near its memory
  limit, and CI runs all of that.
- **Allowed locally:** `python -m py_compile <file>`, and small `curl` downloads of fixtures (≤ 1 MB each).
- **Fixtures are real.** Saved from the live site, never invented. A source that cannot be reached gets a
  `README.md` in its fixture folder saying so, with the date.
- **Never bypass a bot check or CAPTCHA.**
- **No git commands.** The lead commits.
