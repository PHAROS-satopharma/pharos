# Internal contracts (binding for every part of the build)

The schema is in `supabase/migrations/0001_core.sql`. Nothing below may contradict it. If a part needs
another table, it goes in that part's own migration file, listed under "Who owns what".

## Who owns what

| Owner | Paths |
|---|---|
| Collectors core (A1) | `collectors/core/`, `collectors/parsers/{__init__,base,feed,ema_dhpc,ema_psusa,govuk,openfda_enforcement,hc_recalls,pubmed}.py`, `collectors/{run,matching,pdf,merge,alerts,report,backfill,probe}.py`, `collectors/report_templates/`, `collectors/sources.yaml`, `collectors/requirements.txt`, `supabase/migrations/0003_seed_watchlist.sql`, `tests/test_{matching,merge,alerts,feed,ema,run}*.py`, `tests/fixtures/{ema-*,fda-*,mhra-*,bfarm-rhb,basg-*,aemps-*,hsa-*,hc-*,pubmed}/` |
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
| fda-medwatch | feed | A1 |
| fda-enforcement | openfda_enforcement | A1 |
| mhra-dsu, mhra-alerts | govuk | A1 |
| bfarm-rhb | feed | A1 |
| basg-whatsnew | feed | A1 |
| aemps-feed | feed | A1 |
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
| swissmedic-hpc | swissmedic | A2 |
| medsafe-dhcp, medsafe-comms | medsafe | A2 |
| bfarm-risk | bfarm_risk | A2 |
| pmda-revisions, pmda-urgent, pmda-msi | pmda | A2 |
| mfds-letters | mfds | A2 |
| famhp-news | famhp | A2 |
| cbg-news | cbg | A2 |
| mpa-news | lakemedelsverket | A2 |
| tga-alerts, tga-updates | tga | A2 |
| fimea-email, tga-email | email_inbox | A2 |
| ema-prac, who-alerts, eda-eg, sfda-sa, jfda-jo, uae-mohap, uae-ede | prac / who_alerts / generic_html / ede | A2 |
| (user-added sources) | feed or generic_html | A1 / A2 |

The SPC sources are `spc-cima`, `spc-bdpm`, `spc-ema-epar`, `spc-dailymed`, `spc-mhra` and `spc-pmda`, with
`kind: spc`. Their modules sit under `collectors/spc/` (A2); A1 lists them in `sources.yaml`.

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
-- RPCs callable by a signed-in person:
create_link_token() returns text                          -- one-time Telegram code for the caller
archive_hit_count(p_term text, p_lang text) returns int   -- how many archived texts contain the term
```

**Edge Functions** (all require a signed-in person; the web app calls them with `supabase.functions.invoke`):

| Function | Input | Output | Who may call |
|---|---|---|---|
| `ingredient-lookup` | `{q}` | `{candidates:[{inn_en, atc_code, wikidata_qid, rxcui, labels:{lang:label}, sources:[..], score}]}` | anyone signed in |
| `ingredient-lookup` (terms) | `{action:'terms', wikidata_qid, atc_code, inn_en}` | `{terms:[{lang, country_code, term, kind, mode, source}]}` | anyone signed in |
| `probe-source` | `{url}` | `{probe_id}` | admin. Fires `repository_dispatch` to `probe.yml`; the web app polls `probe_result`. |
| `archive-url` | `{r2_key}` | `{url}` | anyone signed in. Pre-signed R2 GET, valid 10 minutes. |
| `invite-person` | `{email, full_name, role}` | `{person_id}` | admin |
| `telegram-webhook` | Telegram updates | — | Telegram only. Checks the secret-token header; handles `/start <code>`. |

## Environment / secrets

| Secret | Used by |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | web; functions |
| `SUPABASE_SERVICE_ROLE_KEY` | functions |
| `SUPABASE_DB_URL` | collectors |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | collectors; archive-url |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_BOT_USERNAME` | collectors; webhook |
| `GITHUB_DISPATCH_TOKEN`, `GITHUB_REPO` | probe-source |
| `NCBI_API_KEY` | pubmed |
| `ADMIN_TELEGRAM_CHAT_ID` | pg_cron watchdog (stored in Supabase Vault) |
| `PHAROS_IMAP_HOST`, `PHAROS_IMAP_PORT`, `PHAROS_IMAP_USER`, `PHAROS_IMAP_PASSWORD` | collectors (Fimea/TGA newsletters in pharos@satopharma.com). satopharma.com mail is Turbify (Yahoo MX `mx-biz.mail.am0.yahoodns.net`), so it uses Yahoo/Turbify IMAP with a per-mailbox app password. |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | deploy-web |
| `SUPABASE_PROJECT_REF`, `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD` | deploy-supabase |
| `SITE_URL`, `CONTACT_EMAIL` | auth redirects; HTTP contact |
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
