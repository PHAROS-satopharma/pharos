# PHAROS operations

How PHAROS runs from day to day, what each alert means, and how to recover. All times below are UTC unless
marked Cairo. Cairo is UTC+2 in winter and UTC+3 in summer.

## Schedules

| Workflow | When (UTC) | What it does |
|---|---|---|
| `collect.yml`, schedule **4h** | every 4 h at :17 | Feeds, JSON, APIs, HTML lists, the PV mailbox over IMAP (Fimea, TGA newsletters) |
| `collect.yml`, schedule **12h** | 05:47 and 17:47 | Browser-engine sources (famhp, CBG-MEB, Läkemedelsverket, TGA) and the slower lists (EMA news, Swissmedic updates, PMDA company letters and ministry announcements) |
| `collect.yml`, schedule **daily** | 02:31 | Drug classes from the ATC code, large JSON files (EMA medicines, Health Canada recalls), Medsafe's Prescriber Update and NCBI literature (PubMed and PubMed Central), then EMA's EURD list (`collectors/eurd.py`) and literature monitoring list (`collectors/mlm.py`), and up to 15 minutes of the check of the past |
| `collect.yml`, schedule **literature** | 10:41 and 18:41 | The daily run's drug classes, NCBI literature (the enabled sources of kind literature) and up to 15 minutes of the check of the past again, so a new ingredient is ready within hours rather than after the night (owner, 6 Nov 2026); a few minutes when nothing is waiting |
| `collect.yml`, schedule **weekly** | Monday 03:23 | SPC / label watch |
| `collect.yml`, schedule **monthly** | the 1st, 01:41 | Monthly sources |
| `report.yml` | Sunday, 05:00 Cairo | Weekly report (XLSX + PDF) for the week that has just ended, Sunday to Saturday |
| `db-backup.yml`, backup | nightly 00:13 | `pg_dump` → gzip → age → R2 `backups/<date>.sql.gz.age` (plain `.sql.gz` with a warning while `BACKUP_AGE_RECIPIENT` is unset) |
| `db-backup.yml`, verify-archive | Sunday 00:43 | Re-hashes 50 random originals and 10 report files (`reports/`, `reports/packs/`); checks the bucket lock |
| pg_cron `pharos-watchdog` | every 30 min | Admin alert if no run has checked a source successfully in 6 h, or the database is over 350 MB |
| `probe.yml` | on demand | "Test link" from the Sources screen |
| `backfill.yml` | by hand | N months back from every source, flagged as backfill, no alerts |
| `rematch.yml` | by hand | The check of the past for up to 45 minutes at once (after adding an ingredient) |

`collect.yml`, `backfill.yml` and `rematch.yml` share one concurrency group, so two of them never run at once.
A run that starts while another is running waits. If a third run arrives while one is already waiting,
GitHub drops the waiting one; the next schedule picks up its sources. `report.yml` has its own group, so a
collection can never drop the weekly report. GitHub can start scheduled runs late at busy times (hours, on
a new repository). The minutes are chosen off the hour to reduce this.

Every run has a time budget (`PHAROS_TIME_BUDGET_MIN`, about 10 minutes under the job's timeout), and in a
normal run one source gets at most 10 minutes (NCBI literature 15). When the budget runs out the run stops starting new notices
and sources and ends cleanly; what is left waits for the next run, and the source checked longest ago goes
first next time. The screening log shows "time budget reached" on a source that was cut short. A source that
found more new items than its `max_new_items` shows "item cap reached"; the rest are read on the next run, and
the run does not count as complete, so NCBI literature reads the same days again. A run that
crashes is recorded as not ok. Every run except the weekly one ends with a pack asked for on Reports, when one
waits (at most 20 minutes, see *Packs on request*): the 4h, 12h and monthly runs have 60 minutes, the daily 80.

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
| report (weekly: one real run, one run that skips) | 4.35 × 2 | 6 + 1 | 30 |
| backup | 30 | 2 | 60 |
| verify-archive | 4.35 | 2 | 9 |
| probe | about 10 | 3 | 30 |
| CI (only the changed parts are checked) | about 40 | 3 | 120 |
| deploy Supabase | about 10 | 3 | 30 |
| deploy web | about 10 | 2 | 20 |
| packs on request (inside a collection run, only when one is asked for) | as asked | about 25; at worst 3 tries, about 75 | not in the total |
| **Total** | | | **about 1,157** |

That is about 266 minutes a week, inside acceptance test 13's limit of 300, but a little above the aim of 1,100 a
month (the cut is below). While a new ingredient's or class word's literature look-back is filling (see NCBI
literature), the daily run takes up to about 18 minutes: up to about 360 more minutes in that month. The check
of the past adds up to 15 minutes to a daily run only while one is open (a few days after an ingredient or
words are added); with nothing due it ends in seconds. A backfill is a one-off, at most 300 minutes. Run it in
a month with headroom.
Each pack asked for on Reports adds about 25 minutes to the collection run that makes it, and a pack that runs
out of time three times costs about 75 before it is marked failed. At most two of one person's packs and five
in all wait at once (`request_report()` refuses another), so a busy month of packs stays within a few hundred
minutes; a dry run never makes one.

To check the real figure: *GitHub organisation → Settings → Billing → Usage*. If a month goes over 1,100,
the first thing to cut is the 4h schedule, to every 6 h.

## Source health

| State | Meaning | What to do |
|---|---|---|
| `unknown` | Not checked yet | Nothing |
| `ok` | The last run read the source | Nothing |
| `degraded` | The page loaded but changed shape (the parser could not read it), or the source has been quiet for longer than `expected_max_gap_days` | Check the page. If the layout changed, the parser needs a fix (a PR) |
| `down` | The source failed 3 runs in a row (timeouts, HTTP errors) | Usually the regulator's site is down. It recovers by itself |
| `blocked` | The site showed a bot check (for example Cloudflare, or a short page whose words say it is a security check). PHAROS never bypasses one. A page that lost its list but only carries a captcha in its code (a contact form) is "the page changed shape", not blocked | Use the newsletter by email (Fimea already does). This is not "down" |

## The weekly report

Dr Sama's review (6 Nov 2026): some findings must reach the Egyptian Drug Authority within 5 days, so the
report covers one week, Sunday to Saturday in Cairo, and replaces the monthly one. It goes into her SOP and the
pharmacovigilance system master file.

- **When.** `report.yml`, every Sunday at 05:00 Cairo, for the week that ended at midnight. By hand: *Actions →
  PHAROS weekly report → Run workflow*, with the week's Sunday (`2026-11-01`), or nothing for the last week. A
  day that is not a Sunday is refused before anything is read. `month` makes a month again in the old monthly
  format (never both at once).
- **What it reads.** The Ingredients screen's own functions, so the report and the screen never give two
  answers: `ingredient_screen()` and `ingredient_papers()` for each watched ingredient, `screening_log()` for the
  reads of every source, `new_items()` and the country looks for what was new. It connects directly to the
  database (`SUPABASE_DB_URL`); `screen_reader()` (0040) lets that connection read the screen. A read is never
  filtered by what started it.
- **Six sections**, in the PDF and as sheets of the Excel file: 1 Summary and the decisions taken (her words:
  Concerns us, Doesn't concern us, No decision yet, Reviewed, no decision yet); 2 Authorities read, hers first;
  3 Our ingredients by country, with every notice, its link, the words matched and the decision; 4 NCBI
  literature, each search with its counts and every paper with its PubMed and PubMed Central links; 5 Everything
  new per authority, and who looked at the country; 6 To check by hand: her pages the app does not read, the
  sources whose reads failed (with the last failure) and the sources not read that week.
- **Where it goes.** `reports/weekly/<Sunday>/PHAROS-weekly-<Sunday>.xlsx` and `.pdf` in R2, locked; a week made
  again is stored beside it as `-r2`, `-r3` … and the `weekly_report` row points at the latest (the audit log
  keeps the earlier ones), with the SHA-256 of each file, the code that made it and the Actions run. The PDF goes
  to every administrator with Telegram linked (dry-run aware). The Reports page lists the weeks, newest first,
  with the monthly reports made before November 2026 folded below.

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

### An administrator without the People screen

Dr Sama is an administrator with every administrator right except the People screen (owner, 6 Nov 2026): she
does not see the *People* tab, and the database refuses her changes to any person (name, role, access) and to
anyone else's alerts; she still reads every name and sets her own alerts on *Me* (never *Source health
alerts*, which are not offered to her). It is the column
`person.manages_people` (false for her, true for everyone else), read by `i_manage_people()` in the person and
subscription write policies and by `invite-person` (migration 0053). Only an administrator who manages the
people can change the column; to give another administrator the same limits:

```sql
update person set manages_people = false where email = '<their email>';
```

## The app: three tabs, and the phone

"We only do screening here" (Dr Sama, November 2026). PHAROS has three tabs, in the order of her two passes and
the report:

- **Ingredients**: the vertical pass. One ingredient across every source for the days she chooses (below).
- **Sources**: the horizontal pass. Each country's pages and everything its authorities newly published (below).
- **Reports**: the weekly reports, the PSUR and inspection packs made on request (*Packs on request*), and the
  screening log, with each file's SHA-256 and its signatures (*Inspection evidence*).
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
  authority's own page for it. Decisions on a notice are recorded on the Ingredients screen. Their work came
  back inside the remaining screens: the signal steps under the decision (*The signal steps*), our label under
  *Label changes* (*Our label and the label watch*), and the PSUR builder as the PSUR pack on Reports (*Packs on
  request*).
- **Collection steps.** The morning escalation of late items (`collectors/escalate.py`) no longer runs. The
  morning message about the five-day clock (`collectors/reminders.py`, below) took its place. The daily EURD
  list (`collectors/eurd.py`) and the daily reading of EMA's literature monitoring list (`collectors/mlm.py`)
  were removed with it and put back in November 2026: the readiness line, the PSUR pack and the weekly report
  read the EURD list, and the Ingredients screen and the weekly report say whether EMA reads the literature for
  each ingredient (see *Case reports in the literature*).
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
so Germany's two authorities clear together. The look is the time the page read its list, not the time of the
click (0056): a notice that arrived while the card stayed open stays new. Each person has their own looks. The *Sources* tab shows
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
7. The next daily run adds its group from the ATC code (searched) and the class above it (shown, switched off
   until you have read its words; see below) and starts the check of the past for its names. To have the past
   checked sooner, run *Actions -> PHAROS check of the past -> Run workflow*; to have the classes made sooner,
   *Actions -> PHAROS collect -> Run workflow -> classes*.
8. The NCBI literature watch searches PubMed and PubMed Central for its English name and its English class
   words at its next daily run, looking back 12 months first (stored as history; papers never go to
   Telegram). See NCBI literature below.

### Adding an ingredient: what follows by itself

Nothing more is asked of her after Save. Each ingredient's row on the Ingredients page says how far the
preparation has got, and the weekly report repeats it in section 1 (migration 0045, `ingredient_readiness()`):

- **Ready** when the ingredient has a name in at least one language, its drug class is made (or it has no ATC
  code, so no class), its check of the past is done, NCBI's 12-month look-back has finished for every expected
  search, every watched country's label watch has read since it was added (a watch that read and found no label
  is an answer), and at least one person with Telegram linked is subscribed to it. Dr Sama is subscribed to every
  ingredient by the migration, so a new one is covered the moment it is saved.
- Otherwise **Still preparing:** followed by what is still running or still to come, in order: *class words
  waiting* (the next daily or literature run: 02:31, 10:41 or 18:41), *check of the past running* or *waiting*,
  *NCBI look-back running* or *waiting*, *label watch on Monday (Japan, Spain)* naming the countries not yet read (the weekly run, Monday
  03:23), *nobody receives its
  Telegram messages yet*.
- Under the line: how many label products were found and where (or *No label found in any watched country*),
  the EURD list's PSUR frequency, data lock point and submission date (the EURD list is read daily again,
  `collectors/eurd.py`), whether EMA's literature monitoring covers it, and who receives its Telegram messages.
- **Japan:** PMDA's search is a form that answers a POST only, so PHAROS cannot look a package insert up by
  name. The term editor has a *Japan code* field when an ingredient is added, and an administrator finds the
  same field on any ingredient already on the watchlist: open its row (the triangle beside the name), then
  *Japan code*. Open the PMDA search (link beside the field), search the name, open the product and copy the
  7-character code from its address (`…/GeneralList/<code>`; the 12-character YJ code is accepted and kept as the
  7 characters it starts with), then **Save**. The row shows the code it has now with a link to its products on
  PMDA; a new code replaces the old one and leaves every name alone (`set_japan_code()`, migration 0052; audited).
  Japan's label watch uses it at its next weekly run. Like any new word it is due for the check of the past that
  night (0034); the readiness line does not wait for that, since a code is not a name. Without a code the row says *No Japan code
  yet, so Japan's label watch cannot find its package inserts*; it never holds Ready back.

### Editing an ingredient on the watchlist

Open its row (the triangle beside the name), then **Edit names** beside *Names looked for* (administrators). Change
the English name or any name: its wording, kind, matching, exclusions or country; add a name or a language; or
press **Remove** (an emptied name is removed too). Nothing is written until **Save**; **Cancel** leaves it as it
was. The rows are written directly (the ingredient_term admin policy, 0001; every change is in the audit log), so
the edit is not one step: if a write fails part-way, the screen says so and the list shows what the database holds.
A new or changed name is due for the check of the past that night (0034). The Japan code is not in this editor; it
keeps its own field on the row. The ATC code is not edited here (classes are made from it).

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
  language, how it was found when no name of the ingredient matched (*Group: Fluoroquinolones*, *Group (by
  hand): NSAID*, or *Related class: Quinolone antibacterials · assess* for a word of the class above the group,
  a class-level signal to be assessed), and *History* when it came from a backfill or the check of the past. A
  class that is switched off is marked *(off)* in the head of the screen. An e-mail with no web page opens with **Read the e-mail**. Its notice shows its status and latest
  decision (who, when, why); a reviewer or administrator records **Concerns us** or **Doesn't concern us**
  (a reason is required) right there, or **Change** after a decision. The decision shows at once on every
  mention filed under the same notice.
- **Label changes** of products with the ingredient are listed apart, under our own label (next section): the
  changes *detected* in the days, the reference product first, each with the sections that changed, what the
  originator added set against our label, the word changes, and the notice's decision.
- **Literature**: the papers the daily NCBI watch stored for those days, by database and by search, the
  ingredient's own papers first, 50 at a time (**Show more**), each with its PubMed and PubMed Central links.
  A paper that looks like a case report is listed first, tagged **Possible case report**, with *day zero · 15
  days · 90 days* and the decision buttons of its notice (see *Case reports in the literature*). Every paper filed
  under a notice shows that notice's five-day clock and signal steps as a mention does (`finding_state()`, asked
  with each page of 50 papers). **Count on
  PubMed and PubMed Central now** asks NCBI live
  (`literature-search`); those counts are by publication date.

The screen reads everything with one call, `ingredient_screen()` (migration 0039), and more papers with
`ingredient_papers()`. Both refuse anyone who is not on the team. Section 03, *Label changes*, reads
`label_changes()` (migration 0043, next section).

## Our label and the label watch

The label watch (`collectors/spc`, weekly) reads the SmPC or PI of every product with one of our ingredients in
the countries it covers and records each change of a safety section (`spc_change`). Section 03 of the
Ingredients screen puts those changes next to **our own label** (6 Nov 2026, the QPPV's third need):

- **Our label.** The panel at the top of section 03 shows the current version of our label for the ingredient:
  product, version, language, how many sections, who uploaded it and when. A reviewer or administrator presses
  **Upload our label** (or **Replace**) and gives the approved leaflet or SmPC as a PDF (read on this computer;
  nothing is uploaded but the sections found), a text file, or pasted text. The screen shows the numbered
  sections it found; at least one safety section (4.1 to 4.9) is needed. Saving makes a new version
  (`save_our_label`, 0027); the version before stays in the database, marked superseded, so what an old change
  was compared with can be traced.
- **The comparison** is the collector's, not the browser's. When a change is recorded, and on every collection
  run for the changes of the last year that have no comparison yet against a current version of our label, the
  collector splits what the originator added into sentences and looks for each one in the same section of our
  label (`collectors/labels/gap.py`; US and Japanese section headings are mapped to the SmPC section). Each
  sentence is **Our label says this** (three quarters or more of its content words are in one sentence of ours),
  **Partly in our label** (two fifths or more) or **Not in our label**; "Ours: …" shows our closest sentence. The
  result is stored once per change and version of our label (`label_gap`). Labels in different languages are
  never compared: the screen says so and asks for a look by eye. A new version of our label is compared with the
  changes of the last year **on the next collection run, within 4 hours**; until then the screen says "Not
  compared with our label yet".
- **The reference product.** One product per ingredient — the originator's, as a rule — can be marked
  **Mark as the reference product** by a reviewer or administrator; it is listed first among the label changes,
  on the screen and in the weekly report, and marking another product clears it. The mark is in the audit log.
- **The weekly report** lists the same changes under each ingredient (*Detected 3 Nov 2026*, the label's own
  date, product, holder, authority, sections) with one line on the gap: *Our label: 2 covered, 1 partly, 1
  missing*, *Not compared: different language*, *Not compared yet*, or *No label of ours uploaded*.
- **Days.** Section 03 and the report filter by the Cairo day the change was **detected**, not by the date printed
  on the label (a label dated 1 October found on 3 November appears in the week of 3 November).

The Our labels screen of before November 2026 (`/labels`) stays removed; the panel on the Ingredients screen
took its place.

## Drug classes and the check of the past

- **Drug classes from the ATC code.** The daily run starts with `python -m collectors.classes`. For each
  watched ingredient with an ATC code, its level-4 group (levofloxacin J01MA12 -> J01MA Fluoroquinolones) and
  the level-3 class above it (J01M Quinolone antibacterials) are each made a drug class once: the name from WHO's ATC index (atcddd.fhi.no), the words from Wikidata (the item
  with that ATC code, or else the drug class Wikidata names exactly as WHO does), in the 15 regulator
  languages. Junk is dropped, plurals are cut to a stem that finds singular and plural, and a word another
  word already finds is dropped. A class that exists is never changed; the ingredient is only linked to it.
  If WHO or Wikidata does not answer, nothing is made and the ingredient is tried again the next day (a
  warning in the run). `python -m collectors.classes --dry-run` prints what it would make; *Actions -> PHAROS
  collect -> Run workflow -> classes* runs only this step.
- **The search profile** (open an ingredient on the Ingredients page). *Ingredient only* looks for its own
  names; *Ingredient + groups* adds the words of every one of its classes; *Custom* is what the page shows when
  some classes are switched on and some off. The mode is read from the switches, not stored. Each class line
  says what the class is to the ingredient (*its group*, *the class above its group*, *a group added by hand*)
  and has its switch, **Searched** / **Not searched**. **Words PHAROS looks for** lists every word searched for
  the ingredient, by language, with where it comes from and how it matches.
- **Notices only.** A searched class has a second switch, **In the literature search** / **Notices only**
  (administrators). A wide class such as NSAID finds thousands of PubMed and PubMed Central papers a year
  that are not about the ingredient; *Notices only* keeps its words in regulator notices, in every language, and
  takes its English words out of the daily NCBI watch, the live count, the weekly report and the readiness
  check. Papers it already found stay. Switching it back on after a long pause looks back again.
- **The class above the group starts switched off.** Its words come from Wikidata with noise ("girase
  inhibitor"), a wide class brings notices that are not about the ingredient, and each English word is a
  12-month look-back on PubMed and PubMed Central. Read its words, remove the wrong ones, then switch it on:
  the check of the past and the literature look-back start for it. It is the way to Japanese words for
  fluoroquinolones (ニューキノロン, フルオロキノロン), which Wikidata has only at that level.
- **A group by hand.** **Add group** on the ingredient's line (administrators) names a pharmacotherapeutic
  group in words, never an ATC code ("Respiratory fluoroquinolones"). An existing class with that name is
  reused; a new one starts with no words, which you add on its line. It can be removed from the ingredient
  (**Remove this group from …**); a class from the ATC code is switched off instead, never removed. The ATC
  classes and codes are never changed by any of this.
- **On the Ingredients page** (open an ingredient): "Fluoroquinolones (J01MA) · 17 words in 12 languages ·
  from the ATC code · its group", its switch, then **Confirm**, which records the administrator's name and the date. Opening the
  class lists its words by language; each can be tested against the archive, and an administrator adds or
  removes words. Check the words before confirming: Wikidata has gaps (no Japanese or Portuguese word for
  fluoroquinolones, and German only as "Fluorchinolonantibiotikum", from which "Fluorchinolon" is made).
- **How class words match.** A class word is looked for only in notices in its own language. A notice that
  names the class but none of the watched ingredients is a class-only issue: the daily digest, never an
  immediate message.
- **The check of the past** (`python -m collectors.rematch`). Notices are matched as they arrive, so a word
  saved later (a new ingredient, a new or changed name, an ingredient watched again after a pause, a new
  class word, and a class's words when a watched ingredient is linked to the class or watched again, 0055)
  is "due" until the stored notices of the last 12 months have been checked with it. The daily
  run gives it 15 minutes after the collection; `rematch.yml` runs it by hand for up to 45 minutes. It reads
  each notice's kept text, or its original again from R2 (page, PDF with OCR, attachments), skips words that
  already matched that notice, and files what it finds as history: no Telegram message, no digest. A
  class-only issue its class's words had already found gains the ingredients that search the class now. On the
  0055 deployment the words of every class a watched ingredient joined after they were last checked became due. Its
  progress is the `rematch_job` row (one open at a time): the next run continues from
  `cursor_document_id`; when it reaches the end its words are marked checked, and a word changed meanwhile
  waits for the next check. A list page shared by several notices is not read as any one notice's text.
  Literature has its own search and is not checked here.
- **After the 0034 deployment** the words the 12-month backfill already covered are marked checked;
  everything added after it (levofloxacin, added 5 November 2026) is due, so the first daily run starts on it.

## Removed: Signals, Our labels, the PSUR builder, Oversight and the escalation

Removed as screens in November 2026 (see *What was removed* above). For the record of what they did:

- **Signals** took a notice marked Relevant through validation, assessment, action and closed. Every step is a
  row in `signal_event`, which nobody can change or delete; the rows stay. The same steps are now taken under
  the decision on the Ingredients screen (see *The signal steps*).
- **Our labels** kept the text of our own approved product information, section by section, and compared it
  with an originator's label change. The versions stay in the database, and since 6 Nov 2026 the same text is
  uploaded and read on the Ingredients screen, under *Label changes* (see *Our label and the label watch*).
- **The PSUR builder** (`/psur`) gathered a PSUR interval's notices, label changes, literature, signals and
  screening annex, with the interval from EMA's EURD list (`eurd_entry`). The PSUR pack on Reports does this
  now (see *Packs on request*).
- **Oversight** (`/oversight`) listed what was late (`overdue_items(day)`, still in the database; the review time
  is `app_setting` `review_due_days`). **The morning escalation** sent the late items to administrators on
  Telegram once a Cairo day (notification kind "Late items"). Neither runs now; the five-day clock's morning
  reminder (next section) is what reaches the team.

## The five-day clock

When Dr Sama marks a notice *Concerns us*, the Egyptian Drug Authority must have it within five days. PHAROS
keeps that clock (migrations 0041 and 0050) per notice:

- **Day zero** is the Cairo day PHAROS first showed the notice — the day the notice was created in PHAROS
  (`issue.created_at`), not the day of the decision and not the date of any document: the authority counts from
  when we knew. An EMA document that arrives later and becomes the notice's anchor does not move it, and a notice
  created today for an old document is due in five days, not late. `app_setting` `eda_days` (5) and
  `eda_day_zero` (`first_seen`, or `decision` to count from the decision) change that.
- **The clock on the screen.** Under the status of a notice on the Ingredients screen the clock reads
  "Authority: due Tue 11 Nov, 1 day left", "Authority: late by 3 days (was due Tue 3 Nov)" or "Sent to the
  authority 6 Nov 2026 · ref EDA/2026/0042". It shows nothing while the latest decision is not *Concerns us*.
  Today is the database's Cairo day, never the phone's.
- **Sent to the authority.** A reviewer or administrator presses *Sent to the authority*, gives the day it was
  sent (between day zero and today), the reference and a note, and the clock stops. The row is in
  `authority_report` and nobody can change or delete it; the service key cannot read it. The database refuses a
  report when the latest decision is not *Concerns us* or the decision was reported already; the screen then
  reloads and shows the notice as it is. A wrong report is **withdrawn** with a reason (*Withdraw the report*):
  it stays on record as withdrawn and the clock runs again. A later *Doesn't concern us* switches the clock off,
  but a report already sent is never forgotten: *Concerns us* again finds the notice sent, and nobody is asked to
  report it twice.
- **The morning reminder.** Once a Cairo day, from 07:00, every active administrator and reviewer with a
  Telegram chat gets one message listing the findings that are late or due within two days: the title, the
  ingredient, the country, "due Tue 11 Nov, 1 day left" or "3 days late (was due Tue 3 Nov)", and the link to
  the ingredient's screen. Nothing is sent when nothing is due (notification kind `escalation`; the collector
  sends it right after the new-items digest, never on a backfill, and a failure never fails the run).
- **The weekly report** adds "Reported to the authority this week" and "Due to the authority: N (M late)" to the
  summary and the columns *Due* and *Sent* (date · reference) to the decisions table.

## The signal steps

A finding that concerns us is a signal to follow through the steps of GVP Module IX. PHAROS opens it from the
decision and keeps it inside the finding (migration 0042), so nothing is filled in twice:

- **Concerns us opens the signal.** The moment a reviewer or administrator records *Concerns us*, the notice gets
  a signal (SIG-2026-001 …) named after it, for its ingredient, opened by the person who decided, due for
  validation in 30 Cairo days (`app_setting` `signal_due_days`). A notice has one signal at most: *Concerns us*
  again later opens no second one. `app_setting` `signal_auto_open` (true) switches this off.
- **Doesn't concern us closes it — if nothing was done yet.** While the signal is still in validation with no real
  step taken, *Doesn't concern us* closes it as *not validated* with the words "Decision changed: <her reason>".
  A signal already validated is left as it is and stays open on the screen. *Concerns us* again reopens a signal
  the decision closed this way, into validation, with "Decision changed back: <her reason>" (0058); the
  decision's own closing and reopening are not work, so it can change either way again. A signal a person
  closed (*Not a signal*, an assessment) stays closed.
- **The steps, on the Ingredients screen.** Under the decision and the clock, the signal shows its reference, the
  chain *Validate → Assess → Action → Closed* with the current stage lit, and the day the stage is due ("Validate
  by Sun 6 Dec", marked **late** when past). A reviewer or administrator takes the next step there: *It is a
  signal* (priority and why) or *Not a signal* (why); *Record the assessment* (outcome, and the day the action is
  due when the outcome is a label update, an RMP update, a DHPC or a PSUR input); *Action done*; *Reopen* (a
  signal closed as not a signal goes back to validation, with no priority until it is validated; one closed
  after its assessment goes back to assessment with its own priority, 0057). Every
  step needs words for the record; the history under the chain lists who took each step, when, and what they
  wrote. Two people on one signal: the second step is refused and the screen reloads. Readers see the chain and
  the history, no buttons.
- **The morning reminder** lists, after the findings due to the authority, the signal steps late or due within two
  days — "SIG-2026-001 · <notice> · levofloxacin · Validate · due Sat 7 Nov, 1 day left" — with the link to the
  ingredient's screen; it goes even when no finding is due.
- **The weekly report** shows the signal on each decision row and on each notice that concerns us (reference,
  stage, due day, late), and "Signals open: N (M steps late)" in the summary; the Excel decisions sheet has the
  column *Signal*.

## Inspection evidence

What an inspector can be shown for any week (0046, 0047; the Reports page).

- **The files and their SHA-256.** Reports → Weekly reports lists every week with its PDF and Excel file and the
  SHA-256 of each, as stored on the `weekly_report` row when the file was archived (`reports/weekly/…`, locked in
  R2). The page shows the first and last eight characters; **Copy** copies the full value (where the browser
  refuses the clipboard, the full value is shown to select by hand). The copy kept in the SOP or the
  pharmacovigilance system master file is checked with `sha256sum <file>` (Linux, macOS) or
  `certutil -hashfile <file> SHA256` (Windows): the same 64 characters mean the same file.
- **Who signs.** A reviewer or an administrator signs a weekly report: "I have reviewed this report" (Reviewed)
  or "I approve this report" (Approved); an administrator is offered Approved first, a reviewer Reviewed. A reader
  sees the signatures and cannot sign. The monthly reports (administrators only) and the signals signed before
  November 2026 keep their signatures in `sign_off`. Packs (PSUR, inspection) are signed the same way once they
  are made (0048, below): a pack still waiting has no files, so no fingerprint, and cannot be signed.
- **How.** The signer chooses what the signature means, types their password and may add a comment. The page
  signs in again with that password; `sign_record()` accepts the signature only when the token shows a password
  sign-in in the last five minutes, and stores the name and role at that moment, the meaning, the database
  time and `record_fingerprint()` — for a weekly report the SHA-256 of `pdf_sha256 || ':' || xlsx_sha256` (as
  the monthly report), for a signal the SHA-256 of the signal with its steps and notices. Someone who signs in
  by e-mail link sets a password first under *My account*.
- **What a signature proves.** That this person, with this role, chose this meaning at this database time for
  these exact two files: the stored fingerprint is computed from the two file hashes, which are the hashes of
  the locked files in R2. Under each signature the page says **Fingerprint matches** while the row still points
  at those files, or **File changed since signing** when the week was made again (a new `-r2` file and new
  hashes); the week can then be signed again, and the old signature stays.
- **Never changed.** `sign_off` is append-only (a trigger refuses any update or delete, even by the database
  owner). `audit_log` too (0046): a row trigger refuses every update and delete, a statement trigger every
  truncate, for every role including the owner, and no API role holds those rights. Nothing in PHAROS ever
  changed or removed an audit row; only a migration that drops the trigger could, and it would be in the
  repository history.
- **The archive check.** `db-backup.yml` verify-archive (Sundays 00:43 UTC) re-hashes 50 random originals and
  10 random report files (the weekly and monthly PDF and Excel under `reports/`, and the packs made under
  `reports/packs/`) against the database, checks
  that an overwrite is refused, and records the result in `archive_check`.

## Packs on request

A PSUR pack (one ingredient) or an inspection pack (the whole system), asked for on Reports → Packs (0048, the
QPPV plan's phase 15). A reviewer or an administrator chooses the pack, the ingredient for a PSUR pack, and the
days: at most five years, the first day not in the future. An inspection pack is for administrators only: only
an administrator asks for one, sees it on Reports, reads its files and signs it, and only administrators are
told when it is made. A PSUR pack starts at the ingredient's EURD interval
(the day after the previous data lock point to the next one, as EMA's list sets it), cut at today; an ingredient
with no interval that has started, and an inspection pack, start at the last 12 months. A reader sees the PSUR
packs and their files and cannot ask for one.

- **When it is made.** `request_report()` queues the request; the step "Packs on request", the last step of
  every `collect.yml` run except the weekly and the classes runs, makes the oldest one waiting, one per run,
  so within four hours. Chromium and the fonts are installed only when a request waits. The same pack asked for
  again while it waits is the same request; once made it can be asked for again (a new request, new files).
  At most two of one person's packs wait at once ("Two packs of yours are already waiting; ask again when one
  is ready.") and five in all ("Five packs are already waiting; …"). A dry run of `collect.yml` (`dry_run`)
  never makes a pack: the step is skipped, so the request waits for the next real run.
- **Time budget.** 15 minutes per request, checked between the pieces it is read in. A pack not finished waits
  for the next run, with the note "Took longer than 15 minutes; the next collection run goes on with it."; after
  three tries it is marked failed, with the reason. A run that died while making one leaves it "Being made now";
  after two hours the next run takes it again. A pack that fails is never retried by itself: the reason is on
  the request, and it is asked for again on Reports. A pack never fails the collection run. Printing the PDF has
  no budget of its own, so a very large pack can reach the step's 20-minute limit; the run then dies with it
  "Being made now", it is taken again after two hours, and it is marked failed after three tries.
- **What it is read from.** The weekly report's own functions (`ingredient_screen()`, `ingredient_papers()`,
  `paper_state()`, `label_changes()`, `finding_state()`, `screening_log()`), in pieces of at most 366 days (the
  most each answers), summed: the pack, the weekly reports and the screens never disagree.
- **The PSUR pack.** The EURD interval; §3 regulatory actions (every notice naming the ingredient or its class,
  by country, with its decision, its report to the authority and its signal) and the answer of every country;
  §4 label changes, each against our label; §11 literature, possible case reports first, with day zero and
  the 15- and 90-day dates, and the searches; §15–16 signals (every signal a finding of these days belongs to,
  with its stage, outcome and every step); the screening annex. Findings that do not concern us are left out of
  §3, §4 and §11, counted in the PDF and listed with their reason on the Excel sheet "Not relevant".
- **The inspection pack.** Coverage (every page of hers and whether the app reads it), the screening log,
  every decision, every signature with whether the file still matches it, every report to the authority
  (withdrawn ones too, with the reason), every weekly report with the SHA-256 of both files and its signatures,
  the archive checks, the changes in the audit log counted per table, and the people and their roles.
- **The files.** A4 PDF and an Excel file with a sheet per section, archived in R2 under
  `reports/packs/<psur|inspection>/<request id>/` (never overwritten: a pack made again is stored as `-r2`),
  with the SHA-256 of each on the request, the code (`git_sha`) and the run that made it. Reports shows both
  files with their SHA-256 and the signatures, exactly as a weekly report.
- **Who is told.** The person who asked (when their Telegram is linked) and every administrator; for an inspection
  pack, administrators only: "pack ready",
  with the PDF attached up to 20 MB, or "pack not made" with the reason. Dry run as every message: with
  `telegram_dry_run` on, the notification is recorded and nothing is sent.

## NCBI literature (PubMed and PubMed Central)

- **What is searched.** Every day (the daily run), for each active ingredient: its English name (INN) and each
  English word of its drug classes, on PubMed and on PubMed Central (full texts). Each is typed exactly as a
  person types it on the NCBI websites (no quotes, no field tag), so NCBI expands it the same way. The run reads
  by entry date, every page of results, and stores each paper once: under its PMID with both links when it is in
  both databases, under its PMC id when it is not in PubMed yet. A paper found only by a class word is
  class-only.
- **Never an alert.** A paper is never an immediate alert and never a class-wide line in the daily digest, found
  by the name or by a class word: papers are read on the Ingredients screen and in the weekly report, so the
  authority notices are not buried (levofloxacin alone: 89 PubMed and 357 PubMed Central papers published in
  October 2026). The runner skips a document of the literature source or type, the alert step skips an issue of
  type literature, and the digest query leaves them out. The one exception is a paper that looks like a case
  report naming the ingredient: it is a block of the daily message (below).
- **Publication types.** PubMed's publication types ("Case Reports", "Review" …) are in a paper's PubMed record
  only. For the papers PubMed Central alone found, the run reads their PubMed records too, by the PMID the PMC
  record carries, in the same batches of 200; a paper not in PubMed yet has no type.
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

## Case reports in the literature

A paper reporting a case with one of our products starts a clock the day PHAROS finds it (her decision, 6
November 2026): a valid serious case reaches the Egyptian Drug Authority within 15 days, a non-serious one within
90. Day zero is the Cairo day the paper was first seen, never its publication date.

- **The flag.** The collector marks each paper as it is stored (`document.structured.case_report`,
  `collectors/parsers/pubmed.py`): PubMed lists it as *Case Reports*, or its title says "case report", "case
  series" or "a case of" (the words of `v_case_report`, 0031). Migration 0044 flagged the papers stored before
  it with the same words. A paper found only by a class word is flagged too but, like a class-wide notice, is
  not in the daily message.
- **The daily message.** The papers naming an ingredient that look like case reports and were found since the
  last message are a block, *Possible case reports (N)*, at the end of the daily class digest (`class_digest`
  subscribers, `collectors/alerts.py`): title, journal, day zero with the 15-day date, and a link to the
  ingredient's screen. When there is no class-wide notice the message is headed *possible case reports*. Each
  paper is sent once; a class-only paper, history and a paper that is no case report never.
- **The Ingredients screen.** Section 04 lists the possible case reports first, each tagged *Possible case
  report* with why (PubMed, or its title), *day zero · 15 days · 90 days*, and the decision buttons of its
  notice: **Concerns us**, **Doesn't concern us** (a reason is required), **Change**. The decision shows at once
  on every paper of the same notice. At the top of the section: *Monitored by EMA (MLM)* or *Not monitored by
  EMA: cases in the literature are ours to report*. The screen reads this with `paper_state()` (50 papers a
  call) and `mlm_monitored()` (migration 0044); `ingredient_papers()` is unchanged.
- **The weekly report.** Section 04 lists the possible case reports first with day zero, the two dates and the
  decision, says whether EMA monitors the ingredient, and the summary counts *Possible case reports in the
  literature* and *Case reports with no decision yet*. The Excel sheet *NCBI papers* carries the same columns.
- **EMA's literature monitoring.** `python -m collectors.mlm` (daily, after the EURD list) reads EMA's
  medical literature monitoring list and keeps in `mlm_entry` the group of each watched ingredient EMA monitors
  (a group named after it, or one where it stands alone; a combination does not count). An ingredient with no
  row is *Not monitored by EMA*: its literature cases are ours to report. On the list valid from 1 June 2020,
  ibuprofen, diclofenac and meloxicam are monitored; lornoxicam and levofloxacin are not. The list is matched
  against the watched ingredients on every run, so an ingredient added or retired between EMA's lists is
  covered from the next day; nothing is stored when neither the list nor the match has changed. A failure
  warns and keeps the last list.

## PRAC agendas

- **PRAC agendas.** The `ema-prac` source also reads the agendas and minutes of PRAC meetings
  (`/en/committees/prac/prac-agendas-minutes-highlights`). An agenda names each substance PRAC will discuss,
  weeks before a recommendation, so a watched ingredient on it becomes a notice (Safety update, "Agenda of the
  PRAC meeting …") with the page where it is named. If that page stops listing documents, the run warns and the
  signal recommendations are still read.
