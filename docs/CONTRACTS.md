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
mark_country_looked(p_regulator text) returns timestamptz   -- stamps every authority of that country
  -- for the caller; 42501 without a person, 22023 for an unknown authority
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
-- and on every word of an ingredient that is watched again after a pause.
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
  and never reaches the digest.
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
  -- {ingredient:{id, inn_en, atc_code, active, classes:[{id, code, name_en, origin}], names, name_languages,
  --   class_words, class_languages}, from, to,
  --  regulators:[{id, name, country_name, country_code, homepage, hers, runs, ok, failed, unread_page,
  --   pages:[regulator_page], sources:[{id, regulator_id, kind, channel, url, page_url, enabled, health, notes}],
  --   mentions:[mention]}],          -- every authority with pages of hers or a source not spc/literature;
  --                                  -- hers first, then country and name; runs of safety and recall
  --                                  -- sources, failures by source_run_failed(), never by run.trigger
  --  label_changes:[mention],        -- notices of spc sources
  --  literature:{papers, by_name, by_class, pubmed, pmc, by_query:[{query, kind, pubmed, pmc}], first:[paper]}}
  -- mention: {document_id, source_id, regulator_id, regulator_name, country_name, country_code, title, lang,
  --   link (document_link), email_id, email_r2_key, date, published_date, first_seen_at, doc_type,
  --   terms:[{text, lang}], by_class, is_backfill (the document's or its notice's), sections (spc only),
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

## The five-day clock (0041)

```sql
app_setting eda_days = '5', eda_day_zero = '"first_seen"'   -- jsonb; or '"decision"'
authority_report (id, issue_id, authority 'EDA', sent_on date, reference, note, person_id, decision_id -> review_event,
  created_at, withdrawn_at, withdrawn_by, withdraw_reason)
  -- append-only: the team reads; a reviewer or administrator inserts their own row (sent_on never after
  -- today in Cairo, 22023); the trigger refuses 'PH409' 'NO_CONCERN …' when the notice's latest decision is
  -- not relevant and 'PH409' 'ALREADY_SENT …' when that decision was reported already, and names the decision
  -- (decision_id). Update and delete are refused ('… append-only'); only withdraw_authority_report() writes.
withdraw_authority_report(p_id uuid, p_reason text) returns void
  -- security definer; a reviewer or administrator; reason required (22023); P0002 when unknown or withdrawn.
eda_clock(p_issues uuid[]) returns table (issue_id, ingredient_id, ingredient, title, country, regulator,
  day_zero, due, days_left, clock, decided_at, decided_by, sent_id, sent_on, sent_reference, sent_note, sent_by)
  -- the collector's (null = every notice whose status and latest decision are relevant); not for authenticated.
finding_state(p_issues uuid[]) returns jsonb
  -- the screen's: {"<issue_id>": {day_zero, due, days_left, clock, sent}} with clock running | late | sent | off
  -- and sent {id, on, reference, person, note} or null; {} for nothing or unknown ids; screen_reader() or 42501.
  -- day_zero = Cairo day of the notice's earliest first_seen_at; due = day_zero + eda_days; days_left counts
  -- from signal_cairo_today(), negative when late. off when the latest decision is not relevant.
v_eda_clock  -- eda_clock(null) where clock in ('running', 'late'); the collector's reminder reads it on the
  -- direct connection; revoked from public, anon and authenticated.
```

Collector: `collectors/reminders.py` (`remind_if_due`, kind `escalation`, from 07:00 Cairo, once a day, findings
late or due within 2 days; `run.py` calls it after the new-items digest). Store: `reminder_people()`,
`eda_reminders(today, within_days)`. Web: `web/src/features/screen/clock.ts`, `DecisionButtons.tsx`,
`styles/clock.css`. SQL test: `supabase/tests/eda_clock.sql`; Python: `tests/test_reminders.py`.

## Any ingredient she adds is covered (0045)

```sql
ingredient_readiness(p_ingredient uuid) returns jsonb
  -- security definer; screen_reader() or 42501; P0002 for an ingredient not on the watchlist; execute for
  -- authenticated only (revoked from public and anon). One answer for the Ingredients page and the weekly report:
  -- {names:       {languages_with_a_name, of, missing: [lang]},      -- kind 'code' is not a name; of = every
  --                                                                 -- language of every regulator
  --  class:       {atc, classes, words, confirmed},                 -- words = class_term rows of its classes
  --  past_check:  {done, words_due, job_running},                   -- due: rematched_at null or < changed_at
  --  ncbi:        {searches, expected, look_back_done, last_run},   -- expected = 2 × (name ∪ English class words)
  --  label_watch: {products, by_source: {<source_id>: {country, regulator, products, read}},
  --                waiting: [country], empty: [country], first_snapshot, japan_code},
  --                -- enabled spc sources only; read = a source_run since ingredient.created_at that
  --                -- source_run_failed() does not call a failure; waiting = countries with an unread source;
  --                -- empty = read, no active spc_product; japan_code = an ingredient_term kind 'code', JP
  --  eurd:        {found, list_read, frequency, dlp, next_submission},  -- the substance alone before a combination
  --  ema_mlm:     {monitored},
  --  telegram:    {people: [full_name]},   -- active, telegram linked, subscription 'ingredient' for all or this one
  --  ready}
  -- ready = a name in ≥1 language ∧ (no ATC ∨ words > 0) ∧ past_check.done ∧ ncbi.look_back_done
  --         ∧ (products > 0 ∨ waiting = []) ∧ telegram.people ≥ 1.  japan_code, eurd and ema_mlm never hold it back.
subscription (Dr Sama, kind 'ingredient', ingredient_id null)  -- inserted by 0045 by her address, once (as 0033)
```

Her words, shared by `web/src/features/ingredients/readiness.ts` and `collectors/report_weekly.py`
(`readiness_items`, `readiness_text`; `tests/test_report_weekly.py` holds both to the same phrases): `Ready`, or
`Still preparing: ` + items joined by ` · ` in this order: `no name to look for yet`, `class words tonight`,
`check of the past running` | `tonight`, `NCBI look-back running` | `tonight`, `label watch on Monday (A, B)`
(up to three country names, else `n countries`), `nobody receives its Telegram messages yet`.

Collector: `collectors/eurd.py` (daily, `collect.yml` step "EURD list"; `eurd_entry` as 0028). Web:
`Readiness.tsx` (rpc `ingredient_readiness`, query key `['ingredient-readiness', id]`), `readiness.ts`,
`styles/readiness.css`; the Japan code is an `ingredient_term` kind `code`, lang `ja`, country `JP`, mode `exact`,
source `pmda` (`TermEditor.tsx`). SQL test: `supabase/tests/ingredient_readiness.sql`; Python: `tests/test_eurd.py`,
`tests/test_report_weekly.py`; web: `readiness.test.ts`.

## Environment / secrets

| Secret | Used by |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | web; functions |
| `SUPABASE_SERVICE_ROLE_KEY` | functions |
| `SUPABASE_DB_URL` | collectors |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | collectors; archive-url |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_BOT_USERNAME` | collectors; webhook |
| `GITHUB_DISPATCH_TOKEN`, `GITHUB_REPO` | probe-source |
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
