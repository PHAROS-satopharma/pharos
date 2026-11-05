# PHAROS operations

How PHAROS runs from day to day, what each alert means, and how to recover. All times below are UTC unless
marked Cairo. Cairo is UTC+2 in winter and UTC+3 in summer.

## Schedules

| Workflow | When (UTC) | What it does |
|---|---|---|
| `collect.yml`, schedule **4h** | every 4 h at :17 | Feeds, JSON, APIs, HTML lists, the PV mailbox over IMAP (Fimea, TGA newsletters) |
| `collect.yml`, schedule **12h** | 05:47 and 17:47 | Browser-engine sources (famhp, CBG-MEB, Läkemedelsverket, TGA) |
| `collect.yml`, schedule **daily** | 02:31 | Large JSON files (EMA medicines, Health Canada recalls) |
| `collect.yml`, schedule **weekly** | Monday 03:23 | SPC / label watch |
| `collect.yml`, schedule **monthly** | the 1st, 01:41 | Monthly sources |
| `report.yml` | the 1st, 05:00 Cairo | Monthly report (XLSX + PDF) for the previous month |
| `db-backup.yml`, backup | nightly 00:13 | `pg_dump` → gzip → age → R2 `backups/<date>.sql.gz.age` (plain `.sql.gz` with a warning while `BACKUP_AGE_RECIPIENT` is unset) |
| `db-backup.yml`, verify-archive | Sunday 00:43 | Re-hashes 50 random originals; checks the bucket lock |
| pg_cron `pharos-watchdog` | every 30 min | Admin alert if no run has checked a source successfully in 6 h, or the database is over 350 MB |
| `probe.yml` | on demand | "Test link" from the Sources screen |
| `backfill.yml` | by hand | N months back from every source, flagged as backfill, no alerts |

`collect.yml` and `backfill.yml` share one concurrency group, so two of them never run at once.
A run that starts while another is running waits. If a third run arrives while one is already waiting,
GitHub drops the waiting one; the next schedule picks up its sources. `report.yml` has its own group, so a
collection can never drop the monthly report. GitHub can start scheduled runs late at busy times (hours, on
a new repository). The minutes are chosen off the hour to reduce this.

Every run has a time budget (`PHAROS_TIME_BUDGET_MIN`, about 10 minutes under the job's timeout), and in a
normal run one source gets at most 10 minutes. When the budget runs out the run stops starting new notices
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
| collect daily | 30 | 3 | 90 |
| collect weekly (SPC) | 4.35 | 10 | 44 |
| collect monthly | 1 | 4 | 4 |
| report (one real run, one run that skips) | 2 | 6 + 1 | 7 |
| backup | 30 | 2 | 60 |
| verify-archive | 4.35 | 2 | 9 |
| probe | about 10 | 3 | 30 |
| CI (only the changed parts are checked) | about 40 | 3 | 120 |
| deploy Supabase | about 10 | 3 | 30 |
| deploy web | about 10 | 2 | 20 |
| **Total** | | | **about 1,014** |

That is about 233 minutes a week, inside acceptance test 13's limit of 300. A backfill is a one-off, at most
300 minutes. Run it in a month with headroom.

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

## The Sources screen and the daily new-items message

The Sources screen is a horizontal pass over the authorities: one card per country, Dr Sama's 25 countries
first (A to Z, the European Union among them), then *Other authorities*. Each card shows:

- **The pages you check**: her list (`regulator_page`, 0032), each marked *Read by the app*, *Partly read by
  the app*, *Read by the app, by e-mail subscription* or *Not read by the app — open it yourself*. A page
  counts as read only while one of its sources is switched on.
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

## Signals

A notice marked **Relevant** can open a signal (Signals screen, or the Signal panel on the notice). A signal
goes through validation, assessment, action and closed. Every step is a row in `signal_event`, which nobody can
change or delete, and each step needs a comment except assigning an owner. The step functions stamp the person and
the time themselves. A step taken on a stage that someone else already changed is refused, and the page reloads.

Due dates are Cairo calendar days, set from `app_setting` `signal_due_days`. The defaults are 30 days to
validate, and 30, 60 or 90 days to assess a high, medium or low priority signal. An action's due date is chosen
when the assessment is recorded. To match the SOP, an administrator changes the setting in the SQL editor, for
example:

```sql
update app_setting set value = '{"validation": 14, "assessment": {"high": 30, "medium": 60, "low": 90}}'
 where key = 'signal_due_days';
```

The new days apply to the next step taken. Due dates already set are not moved.

## Our labels

*Ingredients → Our labels* keeps the text of our own approved product information (leaflet or SmPC),
section by section, one row per version. A reviewer or administrator adds a version as a PDF with a text layer, a
text file or pasted text. It is read on their computer, and only the numbered sections found are saved. A new
version of the same product keeps the older ones and marks them superseded.

When the label watch records an originator's change, the notice shows, under each changed section, every sentence
the originator added and whether the same section of our current label says it: *Our label says this* (three
quarters or more of its content words are in one sentence of ours), *Partly in our label*, or *Not in our label*.
US and Japanese sections are matched to the SmPC section they correspond to (adverse reactions → 4.8). The check
compares words in one language only. When our label and the originator's text are in different languages, the
notice shows our section to read side by side.

## PSUR builder and the EURD list

- **The EURD list.** The daily collection (02:31 UTC) ends with `python -m collectors.eurd`: it downloads EMA's
  List of Union reference dates, keeps the original in the archive, and stores in `eurd_entry` every row that
  names a watched ingredient, alone or in a combination (whole words only; a row's "except for …" is not a
  match). A list already stored (same SHA-256) is not read again. A failure only warns; the page keeps the last
  list. To read a saved copy by hand: `python -m collectors.eurd --file eurd.xlsx`.
- **The page** (`/psur`, linked from Reports): choose an ingredient; the interval is set from its EURD row (the
  day after the previous data lock point to the DLP) and can be changed. It shows §3 regulator actions, §4
  label-change notices and originator label changes, §11 literature, §15–16 signals open in the interval, and
  the screening annex (`screening_summary(from, to)`: each source, the Cairo days it was read, failed reads).
  Notices judged not relevant are counted and listed in the Excel file only.
- **Print or save as PDF** prints the page without the form; **Download Excel** saves the same sections as one
  workbook. PHAROS began screening on 5 November 2026; the annex says so when the interval starts earlier.

## Oversight and the morning escalation

- **The page** (`/oversight`, in the top bar): notices waiting for review, reviews late, open signals, signal
  steps late, sources needing a look, the PSUR data lock points and submissions in the next 90 days (from the
  EURD list), and the latest monthly report. Everything late links to the notice or signal.
- **What is late** comes from `overdue_items(day)`: a signal past the due date of its stage, and a notice still
  "New" more than `review_due_days` days (app setting, 7 by default) after PHAROS found it. Backfilled notices
  are never late. To change the review time: `update app_setting set value = '5' where key = 'review_due_days';`
- **The escalation** (`python -m collectors.escalate`, after the 12-hour collection): once a Cairo day, from
  07:00, the late signals and notices go to every active administrator with Telegram linked, as notification
  kind "Late items". Nothing goes when nothing is late. While `telegram_dry_run` is on, the message is only
  written to the notification log.

## Electronic sign-off

- **Who signs what.** An administrator approves each monthly report (Reports, the "Sign-off" column). A
  reviewer or administrator reviews or approves a signal once it is closed (the signal's page, "Sign-off").
- **How.** The signer chooses what the signature means, types their password and may add a comment. The page
  signs in again with that password; `sign_record()` accepts the signature only when the token shows a password
  sign-in in the last five minutes, and stores the name and role at that moment, the meaning, the database
  time and `record_fingerprint()` — the SHA-256 of the report's two files, or of the signal with its steps and
  notices.
- **Never changed.** `sign_off` is append-only (a trigger refuses any update or delete, even by the database
  owner). When a record changes after it was signed — a report made again, a signal reopened — the page marks
  the signature "The record changed after this signature" and the record can be signed again.
- The inspection pack lists every signature of the period (sheet "Sign-offs").

## Literature case reports and PRAC agendas

- **Case reports.** A literature notice is flagged "Possible case report" when PubMed lists it as Case Reports or
  its title says "case report", "case series" or "a case of" (`v_case_report`). The notice page shows day zero
  (the Cairo day PHAROS found the paper) and the dates to report a valid case: 15 days if serious, 90 if not.
  Oversight lists every flagged paper until its 90 days pass, unless it was judged not relevant.
- **EMA's literature monitoring.** `python -m collectors.mlm` (weekly, after the label watch) reads EMA's medical
  literature monitoring list and keeps in `mlm_entry` the group of each watched ingredient EMA monitors (a group
  named after it, or one where it stands alone; a combination does not count). The notice page and Oversight
  say "Not monitored by EMA" for an ingredient with no row: its literature cases are ours to report. On the
  list valid from 1 June 2020, ibuprofen, diclofenac and meloxicam are monitored; lornoxicam is not.
- **PRAC agendas.** The `ema-prac` source also reads the agendas and minutes of PRAC meetings
  (`/en/committees/prac/prac-agendas-minutes-highlights`). An agenda names each substance PRAC will discuss,
  weeks before a recommendation, so a watched ingredient on it becomes a notice (Safety update, "Agenda of the
  PRAC meeting …") with the page where it is named. If that page stops listing documents, the run warns and the
  signal recommendations are still read.
