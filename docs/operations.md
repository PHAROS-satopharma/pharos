# PHAROS operations

How PHAROS runs from day to day, what each alert means, and how to recover. All times below are UTC unless
marked Cairo. Cairo is UTC+2 in winter and UTC+3 in summer.

## Schedules

| Workflow | When (UTC) | What it does |
|---|---|---|
| `collect.yml`, schedule **4h** | every 4 h at :17 | Feeds, JSON, APIs, HTML lists, the PV mailbox over IMAP (Fimea, TGA newsletters) |
| `collect.yml`, schedule **12h** | 05:47 and 17:47 | Browser-engine sources (famhp, CBG-MEB, Läkemedelsverket, TGA) and the slower lists (EMA news, Swissmedic updates, PMDA company letters and ministry announcements) |
| `collect.yml`, schedule **daily** | 02:31 | Drug classes from the ATC code, large JSON files (EMA medicines, Health Canada recalls), Medsafe's Prescriber Update and NCBI literature (PubMed and PubMed Central), then up to 15 minutes of the check of the past |
| `collect.yml`, schedule **weekly** | Monday 03:23 | SPC / label watch |
| `collect.yml`, schedule **monthly** | the 1st, 01:41 | Monthly sources |
| `report.yml` | the 1st, 05:00 Cairo | Monthly report (XLSX + PDF) for the previous month |
| `db-backup.yml`, backup | nightly 00:13 | `pg_dump` → gzip → age → R2 `backups/<date>.sql.gz.age` (plain `.sql.gz` with a warning while `BACKUP_AGE_RECIPIENT` is unset) |
| `db-backup.yml`, verify-archive | Sunday 00:43 | Re-hashes 50 random originals; checks the bucket lock |
| pg_cron `pharos-watchdog` | every 30 min | Admin alert if no run has checked a source successfully in 6 h, or the database is over 350 MB |
| `probe.yml` | on demand | "Test link" from the Sources screen |
| `backfill.yml` | by hand | N months back from every source, flagged as backfill, no alerts |
| `rematch.yml` | by hand | The check of the past for up to 45 minutes at once (after adding an ingredient) |

`collect.yml`, `backfill.yml` and `rematch.yml` share one concurrency group, so two of them never run at once.
A run that starts while another is running waits. If a third run arrives while one is already waiting,
GitHub drops the waiting one; the next schedule picks up its sources. `report.yml` has its own group, so a
collection can never drop the monthly report. GitHub can start scheduled runs late at busy times (hours, on
a new repository). The minutes are chosen off the hour to reduce this.

Every run has a time budget (`PHAROS_TIME_BUDGET_MIN`, about 10 minutes under the job's timeout), and in a
normal run one source gets at most 10 minutes (NCBI literature 15). When the budget runs out the run stops starting new notices
and sources and ends cleanly; what is left waits for the next run, and the source checked longest ago goes
first next time. The screening log shows "time budget reached" on a source that was cut short. A run that
crashes is recorded as not ok.

## Actions minutes budget

The free plan for a private repository gives 2,000 minutes a month. PHAROS aims for about 1,100 or fewer.
GitHub rounds each job up to a whole minute.

| Job | Runs a month | Minutes each | Minutes a month |
|---|---|---|---|
| collect 4h | 6 a day × 30 = 180 | 2 | 360 |
| collect 12h (Playwright) | 2 a day × 30 = 60 | 4 | 240 |
| collect daily (with NCBI literature) | 30 | 7 | 210 |
| collect weekly (SPC) | 4.35 | 10 | 44 |
| collect monthly | 1 | 4 | 4 |
| report (one real run, one run that skips) | 2 | 6 + 1 | 7 |
| backup | 30 | 2 | 60 |
| verify-archive | 4.35 | 2 | 9 |
| probe | about 10 | 3 | 30 |
| CI (only the changed parts are checked) | about 40 | 3 | 120 |
| deploy Supabase | about 10 | 3 | 30 |
| deploy web | about 10 | 2 | 20 |
| **Total** | | | **about 1,134** |

That is about 261 minutes a week, inside acceptance test 13's limit of 300, but a little above the aim of 1,100 a
month (the cut is below). While a new ingredient's or class word's literature look-back is filling (see NCBI
literature), the daily run takes up to about 18 minutes: up to about 360 more minutes in that month. The check
of the past adds up to 15 minutes to a daily run only while one is open (a few days after an ingredient or
words are added); with nothing due it ends in seconds. A backfill is a one-off, at most 300 minutes. Run it in
a month with headroom.

To check the real figure: *GitHub organisation → Settings → Billing → Usage*. If a month goes over 1,100,
the first thing to cut is the 4h schedule, to every 6 h.

## Source health

| State | Meaning | What to do |
|---|---|---|
| `unknown` | Not checked yet | Nothing |
| `ok` | The last run read the source | Nothing |
| `degraded` | The page loaded but changed shape (the parser could not read it), or the source has been quiet for longer than `expected_max_gap_days` | Check the page. If the layout changed, the parser needs a fix (a PR) |
| `down` | The source failed 3 runs in a row (timeouts, HTTP errors) | Usually the regulator's site is down. It recovers by itself |
| `blocked` | The site showed a bot check (for example Cloudflare). PHAROS never bypasses one | Use the newsletter by email (Fimea already does). This is not "down" |

## Telegram admin alerts

Admin alerts go only to the admin, never to reviewers or readers. While `telegram_dry_run` is on (the
default), they are only logged in `ops_alert_log` and `notification`.

| Alert | Sent by | Meaning | What to do |
|---|---|---|---|
| "No collector run has checked a source successfully for N hours" | Watchdog | No run has read even one source without an error for 6 hours or more: an Actions outage, a disabled workflow, a secret that expired, minutes used up, or every source failing | Open *Actions → PHAROS collect* and read the last run |
| "No collector run has checked a source successfully yet" | Watchdog | Collection has never run (normal only before the first deploy) | Run *PHAROS collect* once by hand |
| "The database is N MB" | Watchdog | Over 350 MB of the free plan's 500 MB | Ask the lead to prune text or move to a paid plan before 500 MB |
| Source down | Collectors | A source failed 3 runs in a row | See Source health above |
| Backfill summary | Backfill | How many documents and issues the backfill found | Review the backfill issues in the app |

The watchdog sends at most one alert every 6 hours. A failed archive check or a failed backup fails its
GitHub job, and GitHub emails the repository admins.

## Backups and restore

- Each nightly file in R2 `backups/<date>.sql.gz.age` holds two parts: the sign-in accounts (`auth.users`,
  `auth.identities`, data only, including the password hashes), then the whole `public` schema, with
  structure and data.
- The file is gzip, then encrypted with [age](https://age-encryption.org) to the public key in the GitHub
  secret `BACKUP_AGE_RECIPIENT` (docs/setup.md, "Backup encryption"). Only the private key, kept offline,
  can read it. If that secret is not set, the backup still runs but is stored unencrypted as
  `backups/<date>.sql.gz`, and every run shows the warning "Backup not encrypted".
- Bucket lock rules keep each backup for 90 days, and a lifecycle rule then deletes it. That leaves 90 days
  of copies.
- The originals (`sha256/`), the inbound mail (`inbound/`) and the reports (`reports/`) are locked for good.
  They are the archive, and they do not depend on the backup.

**Restore** (the lead does this):

1. Download the backup from *Cloudflare → R2 → pharos-archive → backups/*.
2. If it ends in `.age`, decrypt it on the machine that holds the private key (never upload the key):
   `age -d -i key.txt -o <date>.sql.gz <date>.sql.gz.age`, then check it with `gzip -t <date>.sql.gz`.
   A file ending in `.sql.gz` (from before encryption was set up) needs no decryption.
3. Use the same Supabase project, or a new one in Frankfurt. In the SQL editor, run
   `drop schema public cascade; create schema public; grant usage on schema public to anon, authenticated, service_role;`.
4. Run `gunzip -c <date>.sql.gz | psql "<session pooler URI>"`. Ignore "already exists" notices.
   In one step without writing the plain file: `age -d -i key.txt <date>.sql.gz.age | gunzip -c | psql "<session pooler URI>"`.
5. Mark the migrations as applied: `supabase migration repair --status applied 0001 0002 0003`, plus any later
   migration numbers.
6. Re-run **PHAROS deploy Supabase** by hand (from `main`). It re-creates the watchdog schedule (pg_cron jobs
   are not in the dump), the Vault secrets and the Telegram webhook.
7. Check that the app shows the issues and that the next collection run writes a `run` row.

## First administrator

PHAROS is invite-only, so the very first admin is made once, by hand. Invite the owner's email in *Supabase →
Authentication → Users → Invite user*, then run this in the SQL editor:

```sql
insert into person (auth_user_id, full_name, email, role)
select id, 'Omar Gawish', email, 'admin' from auth.users where email = '<the invited email>';
```

After that, admins invite everyone else from the People screen (the `invite-person` function).

## The app: three tabs, and the phone

"We only do screening here" (Dr Sama, November 2026). PHAROS has three tabs, in the order of her two passes and
the report:

- **Ingredients**: the vertical pass. One ingredient across every source for the days she chooses (below).
- **Sources**: the horizontal pass. Each country's pages and everything its authorities newly published (below).
- **Reports**: the screening reports.
- **People** is a fourth tab for administrators only: who may sign in, their roles and messages.
- **Me** (her initials, top right): Telegram, the messages she receives, password, theme and sign-out.

`/` opens Ingredients.

- **On a phone** (a screen under 760 px wide) the tabs sit in a bar at the foot of the screen, each labelled,
  the current one in amber with a rule above it. The bar keeps clear of the phone's gesture bar and notch.
- **The phone app.** On Android, open `https://pharos-satopharma.pages.dev` in Chrome, sign in, then
  Chrome's menu (⋮) → **Add to Home screen** (on some phones **Install app**) → **Install**. On an iPhone, Safari → Share → **Add to Home
  Screen**. PHAROS then opens from its own icon, full screen, at Ingredients. It is the same website
  (`web/public/manifest.webmanifest`). There is no offline copy (no service worker), so every screen is
  always the latest one and needs a connection.

### What was removed in November 2026, and what is kept

- **Screens.** These are gone: Notifications (the notice list and its Excel export), the notice page (`/issue/…`),
  Signals, Oversight, the PSUR builder and Our labels. An old link or bookmark to any of them
  (`/notifications`, `/issues`, `/issue/<id>`, `/signals`, `/signals/<id>`, `/oversight`, `/psur`, `/labels`)
  opens Ingredients, never an empty page. A notice's title on the Ingredients and Sources screens opens the
  authority's own page for it. Decisions on a notice are recorded on the Ingredients screen.
- **Collection steps.** The daily EURD list (`collectors/eurd.py`), the morning escalation of late items
  (`collectors/escalate.py`) and the weekly EMA literature monitoring list (`collectors/mlm.py`) no longer
  run. Their data stays as it was last written: `eurd_entry` and `mlm_entry` keep the last list read.
- **Kept running.** Every source, the label (SPC) watch (its changes show on the Ingredients screen), NCBI
  literature, the check of the past, the PRAC agendas and minutes (`ema-prac`), the Telegram messages (new
  notices, the daily digests, source health) and the watchdog.
- **Data.** No table, view or function was dropped and no migration was changed. The notices (`issue`) and
  their decisions (`review_event`), signals (`signal`, `signal_event`), our labels, the EURD and literature
  monitoring lists, the case-report flag (`v_case_report`), `overdue_items()` and every signature
  (`sign_off`) stay in the database, and their database tests still run in CI.

## The Sources screen and the daily new-items message

The Sources screen is a horizontal pass over the authorities: one card per country, Dr Sama's 25 countries
first (A to Z, the European Union among them), then *Other authorities*. Each card shows:

- **The pages you check**: her list (`regulator_page`, 0032), each marked *Read by the app*, *Partly read by
  the app*, *Read by the app, by e-mail subscription* or *Not read by the app — open it yourself*. A page
  counts as read only while one of its sources is switched on. A page not read says why in its note.
- **New since you last looked (N)**: every item the country's authorities published since the person last
  pressed **Mark as looked at** on that card, or since Sunday 00:00 Cairo when they never did, and never more
  than 31 days back. Matched items carry *Matches a watched ingredient*. An item that came by e-mail with no
  web page opens with **Read the e-mail** and **Save the original e-mail**.
- **This week's reading** (folded): per source, checks, failed checks, new and matched items, and the last
  check, from Sunday 00:00 Cairo. *New* and *Matched* open the items behind them.

**Mark as looked at** stamps every authority of the country for the person pressing it (`mark_country_looked`),
so Germany's two authorities clear together. Each person has their own looks. The *Sources* tab shows
"N new" across every country. Feed and API addresses are never shown as links; an administrator sees them,
with the parser, schedule, health and last error, under **Technical details**.

Once a day, on the first collector run after the digest hour (`digest_hour_cairo`, 09:00 Cairo by default,
within 4 h 30 min), every `new_items_digest` subscriber gets one Telegram message:

```
PHAROS · new items
New on the authorities' pages since <Cairo time>:

Germany: 3
United Kingdom: 1

https://pharos-satopharma.pages.dev/sources
```

The counts run from the last message delivered on an earlier day (a day back for the first one) and use the
same list as the screen (`new_items()`). Nothing is sent on a day with nothing new. A refused message is
tried again on the next run inside the window, to the people who did not get it. Anyone switches it on or
off on the People screen: *New items on the authorities' pages, once a day*. Migration 0033 switches it on for
Dr Sama only. While `telegram_dry_run` is on, the message is only written down.

### Her pages: what reads each one (0038, 6 Nov 2026)

Every safety and DHPC page of her list is read, except two whose sites refuse the servers PHAROS runs on.
Each new source below was read from GitHub's runners before it was added.

| Her page | Read by |
|---|---|
| EMA home page news | `ema-news`, EMA's news list (every news item, ten a page). Not `news.xml`: it carries only seven items and missed the oral GLP-1 opinion of 16 Oct 2026 |
| Swissmedic updates | `swissmedic-updates`, "New on this website", everything Swissmedic posts (40 a page, about two months) |
| Medsafe Prescriber Update | `medsafe-prescriber-update`: each article of the latest issue and the issue PDF (four issues a year) |
| PMDA, safety information announced by MHLW | `pmda-mhlw`, from the Japanese page (the English one has not changed since June 2013). Rare: no expected gap |
| Infarmed circulars | `infarmed-circulares`, which now keeps every circular of the medicines circulars page (`circulares_all`), not only the alert series |
| HPRA newsletters | `hpra-notices`: her address no longer opens; each Drug Safety Newsletter is posted as a safety notice |
| MFDS safety letters (health.kr) | `mfds-letters`: health.kr republishes MFDS's letters, all of which are on MFDS's own board |
| Health Canada InfoWatch | Not read. canada.ca timed out every request from the runners (6 Nov 2026), with a browser's and with PHAROS's own user agent. Health Canada sends each issue by e-mail (MedEffect e-Notice) |
| FDA press announcements | Not read. fda.gov answers the runners with its abuse-detection page. To have them read: subscribe the PHAROS mailbox to *FDA Press Releases* (the sign-up box at the bottom of fda.gov's press announcements page). `fda-email` already reads every message from `public.govdelivery.com`; then set the page's `read_by` to `{fda-email}` with a note starting "By e-mail subscription" |

## Turning real Telegram messages on

`app_setting.telegram_dry_run` starts at `true`. Only the owner turns it off, on *My account → Real Telegram
messages* (admins only):

1. **Send me a test message** sends one real message to his own linked chat, and to nobody else
   (`send_telegram_test()`, bot token from Vault). The screen shows Telegram's answer.
2. **What would have gone** shows the latest messages written down during dry run.
3. Once a test has gone, he ticks the approval and clicks **Turn real messages on**. **Back to dry run**
   undoes it. Every change is written to `audit_log`.

## Adding a source

1. **Catalogue source** (lead, by pull request): add an entry to `collectors/sources.yaml` with its `id`,
   regulator, `kind`, `channel`, `url`, `page`, `parser`, `languages`, `schedule` and
   `expected_max_gap_days`. `page` is the page a person opens (https, never a feed or an API); the
   Sources screen links there. When the source reads one of Dr Sama's pages, add its id to that page's
   `read_by` in `regulator_page` (by migration) so the page shows *Read by the app*. Add a real saved
   fixture under `tests/fixtures/<id>/` and a parser test. CI must pass before merge.
2. **User source** (admin, in the app): *Sources → Add → Test link*. The probe shows what PHAROS would read.
   Save only if the items look right. User sources use the `feed` or `generic_html` parser.
3. **Newsletter-only source**: subscribe pharos@satopharma.com to the regulator's newsletter, then add an
   `email` channel source with parser `email_inbox` (lead, by pull request).

## Adding an ingredient

1. *Ingredients → Add*, then type the name. Misspellings are fine.
2. PHAROS lists candidates from Wikidata, the EMA lists, RxNav and PubChem, each with its ATC code. It never
   picks one for you.
3. Click **Confirm <name> (<ATC>)**. Nothing is saved before this click.
4. The term editor is pre-filled for each language. Add the names it marks as gaps, and the national brand
   names.
5. Use **Test against archive** to see how many stored texts each term hits before saving.
6. The SPC watch picks the ingredient up at its next weekly run.
7. The next daily run adds its drug class from the ATC code (see below) and starts the check of the past for
   its names. To have the past checked sooner, run *Actions -> PHAROS check of the past -> Run workflow*.
8. The NCBI literature watch searches PubMed and PubMed Central for its English name and its English class
   words at its next daily run, looking back 12 months first (stored as history; papers never go to
   Telegram). See NCBI literature below.

## The Ingredients screen: one ingredient across every source

Click an ingredient's name on *Ingredients* (the triangle beside it still shows every name looked for). The
screen answers one question for the days chosen: did any source mention this ingredient, and where. It is the
vertical pass; the Sources screen is the horizontal one.

- **The days.** *This week* (Sunday to today, Cairo), *Last week*, *Last 30 days*, or any *From*/*To*, both days
  included, at most 366. The days are in the address (`/ingredients/<id>?from=2026-11-01&to=2026-11-07`), so a
  link opens the same screen.
- **The answer per country**, her countries first, then *Other authorities*:
  *Mentioned in N notices*; *Not read in these days*; *N of M reads failed*; *A page of hers is not read by the
  app*; or *Nothing found*. The middle three say "check it by hand", and their pages open folded out. A read
  counts the safety and recall sources of the country in those Cairo days; a note such as "time budget reached"
  is not a failure. The line at the top sums it up: *Mentioned in X of N countries · Y nothing found · Z to check
  by hand*.
- **Each mention** shows its date (published, else the day it was first seen), its type, the original title
  linked to the page a person opens (the same link as on the Sources screen), the words that matched with their
  language, *By class* when only a class word matched, and *History* when it came from a backfill or the check of
  the past. An e-mail with no web page opens with **Read the e-mail**. Its notice shows its status and latest
  decision (who, when, why); a reviewer or administrator records **Reviewed**, **Relevant** or **Not relevant**
  (a reason is required) right there, or **Change** after a decision. The decision shows at once on every
  mention filed under the same notice.
- **Label changes** of products with the ingredient are listed apart, with the sections that changed.
- **Literature**: the papers the daily NCBI watch stored for those days, by database and by search, the
  ingredient's own papers first, 50 at a time (**Show more**), each with its PubMed and PubMed Central links.
  Papers have no decision buttons. **Count on PubMed and PubMed Central now** asks NCBI live
  (`literature-search`); those counts are by publication date.

The screen reads everything with one call, `ingredient_screen()` (migration 0039), and more papers with
`ingredient_papers()`. Both refuse anyone who is not on the team.

## Drug classes and the check of the past

- **Drug classes from the ATC code.** The daily run starts with `python -m collectors.classes`. For each
  watched ingredient with an ATC code, its level-4 group (levofloxacin J01MA12 -> J01MA Fluoroquinolones) is
  made a drug class once: the name from WHO's ATC index (atcddd.fhi.no), the words from Wikidata (the item
  with that ATC code, or else the drug class Wikidata names exactly as WHO does), in the 15 regulator
  languages. Junk is dropped, plurals are cut to a stem that finds singular and plural, and a word another
  word already finds is dropped. A class that exists is never changed; the ingredient is only linked to it.
  If WHO or Wikidata does not answer, nothing is made and the ingredient is tried again the next day (a
  warning in the run). `python -m collectors.classes --dry-run` prints what it would make.
- **On the Ingredients page** (open an ingredient): "Fluoroquinolones (J01MA) · 17 words in 12 languages ·
  from the ATC code", then **Confirm**, which records the administrator's name and the date. Opening the
  class lists its words by language; each can be tested against the archive, and an administrator adds or
  removes words. Check the words before confirming: Wikidata has gaps (no Japanese or Portuguese word for
  fluoroquinolones, and German only as "Fluorchinolonantibiotikum", from which "Fluorchinolon" is made).
- **How class words match.** A class word is looked for only in notices in its own language. A notice that
  names the class but none of the watched ingredients is a class-only issue: the daily digest, never an
  immediate message.
- **The check of the past** (`python -m collectors.rematch`). Notices are matched as they arrive, so a word
  saved later (a new ingredient, a new or changed name, an ingredient watched again after a pause, a new
  class word) is "due" until the stored notices of the last 12 months have been checked with it. The daily
  run gives it 15 minutes after the collection; `rematch.yml` runs it by hand for up to 45 minutes. It reads
  each notice's kept text, or its original again from R2 (page, PDF with OCR, attachments), skips words that
  already matched that notice, and files what it finds as history: no Telegram message, no digest. Its
  progress is the `rematch_job` row (one open at a time): the next run continues from
  `cursor_document_id`; when it reaches the end its words are marked checked, and a word changed meanwhile
  waits for the next check. A list page shared by several notices is not read as any one notice's text.
  Literature has its own search and is not checked here.
- **After the 0034 deployment** the words the 12-month backfill already covered are marked checked;
  everything added after it (levofloxacin, added 5 November 2026) is due, so the first daily run starts on it.

## Removed: Signals, Our labels, the PSUR builder, Oversight and the escalation

Removed in November 2026 (see *What was removed* above). For the record of what they did:

- **Signals** took a notice marked Relevant through validation, assessment, action and closed. Every step is a
  row in `signal_event`, which nobody can change or delete; the rows stay. The due days are still in
  `app_setting` `signal_due_days`.
- **Our labels** kept the text of our own approved product information, section by section, and compared it
  with an originator's label change. The versions stay in the database.
- **The PSUR builder** (`/psur`) gathered a PSUR interval's notices, label changes, literature, signals and
  screening annex, with the interval from EMA's EURD list (`eurd_entry`, last list kept).
- **Oversight** (`/oversight`) listed what was late (`overdue_items(day)`, still in the database; the review time
  is `app_setting` `review_due_days`). **The morning escalation** sent the late items to administrators on
  Telegram once a Cairo day (notification kind "Late items"). Neither runs now.

## Electronic sign-off

- **Who signs what.** An administrator approves each monthly report (Reports, the "Sign-off" column). Signals
  were signed on their own page until the Signals screen was removed; those signatures stay in `sign_off`.
- **How.** The signer chooses what the signature means, types their password and may add a comment. The page
  signs in again with that password; `sign_record()` accepts the signature only when the token shows a password
  sign-in in the last five minutes, and stores the name and role at that moment, the meaning, the database
  time and `record_fingerprint()` — the SHA-256 of the report's two files, or of the signal with its steps and
  notices.
- **Never changed.** `sign_off` is append-only (a trigger refuses any update or delete, even by the database
  owner). When a record changes after it was signed — a report made again, a signal reopened — the page marks
  the signature "The record changed after this signature" and the record can be signed again.
- The inspection pack lists every signature of the period (sheet "Sign-offs").

## NCBI literature (PubMed and PubMed Central)

- **What is searched.** Every day (the daily run), for each active ingredient: its English name (INN) and each
  English word of its drug classes, on PubMed and on PubMed Central (full texts). Each is typed exactly as a
  person types it on the NCBI websites (no quotes, no field tag), so NCBI expands it the same way. The run reads
  by entry date, every page of results, and stores each paper once: under its PMID with both links when it is in
  both databases, under its PMC id when it is not in PubMed yet. A paper found only by a class word is
  class-only.
- **Never on Telegram.** A paper is never an immediate alert and never a line in the daily class digest, found
  by the name or by a class word: papers are read on the Ingredients screen and in the weekly report, so the
  authority notices are not buried (levofloxacin alone: 89 PubMed and 357 PubMed Central papers published in
  October 2026). The runner skips a document of the literature source or type, the alert step skips an issue of
  type literature, and the digest query leaves them out.
- **Look-back.** A search word never searched before (a new ingredient, a new class word, or one not searched
  for 90 days) first reads the last 12 months. What it finds is stored as history.
  After that each run reads from the last complete run minus 3 days. `literature_search` (migration 0035) holds
  one row per database and word: the look-back's days and, once every paper it found is stored, when it
  finished. To read a word's 12 months again, delete its two rows.
- **How fast.** A run reads and stores at most 800 papers in at most 15 minutes, new papers first, then the
  look-backs' name papers, then their class papers; the rest wait for the next day (the screening log says "time
  budget reached"). Storing takes about a second a paper, so a large look-back takes days: levofloxacin's 12
  months are about 8,000 papers (PubMed 1,105 and PMC 7,838 on 6 November 2026), the NSAID class words about
  20,000. To fill a look-back in one go, run `backfill.yml` with `source: pubmed` (up to 285 minutes, about
  17,000 papers, name papers first, everything as history); the next daily run then finds them stored.
- **Capacity.** About 3 KB of database per paper: 50,000 papers is about 150 MB. The watchdog warns at 350 MB.
  Watch the database size while the first look-backs fill, and keep class words specific (each class word adds
  thousands of papers a year).
- **Etiquette.** `tool=pharos`; at most 3 requests a second, or 10 with `NCBI_API_KEY` (a free key from an NCBI
  account; set it as a repository secret: the collectors and the `literature-search` function use it).
- **Live counts.** The `literature-search` function returns, for an ingredient and a range of publication
  dates, the live PubMed and PMC count of each search with a link that opens the same search on the website.
  On 6 November 2026 its counts for levofloxacin, 1-31 October 2026, were the websites' own: PubMed 89 and PMC
  357 for "levofloxacin", 233 and 475 for "fluoroquinolones", 187 and 491 for "nonsteroidal
  anti-inflammatory". The stored papers can differ from these counts: the watch reads by entry date, the
  counts are by publication date.

## Literature case reports and PRAC agendas

- **Case reports.** The database still flags a literature notice "Possible case report" when PubMed lists it as
  Case Reports or its title says "case report", "case series" or "a case of" (`v_case_report`), with day zero
  (the Cairo day PHAROS found the paper). The notice page and Oversight that showed the flag were removed in
  November 2026.
- **EMA's literature monitoring.** The weekly reading of EMA's medical literature monitoring list
  (`collectors/mlm.py`) was removed in November 2026; `mlm_entry` keeps the last list read.
- **PRAC agendas.** The `ema-prac` source also reads the agendas and minutes of PRAC meetings
  (`/en/committees/prac/prac-agendas-minutes-highlights`). An agenda names each substance PRAC will discuss,
  weeks before a recommendation, so a watched ingredient on it becomes a notice (Safety update, "Agenda of the
  PRAC meeting …") with the page where it is named. If that page stops listing documents, the run warns and the
  signal recommendations are still read.
