# PHAROS operations

How PHAROS runs from day to day, what each alert means, and how to recover. All times below are UTC unless
marked Cairo. Cairo is UTC+2 in winter and UTC+3 in summer.

## Schedules

| Workflow | When (UTC) | What it does |
|---|---|---|
| `collect.yml`, schedule **4h** | every 4 h at :17 | Feeds, JSON, APIs, HTML lists, the PV mailbox over IMAP (Fimea, TGA, FDA, famhp and Health Canada mails) |
| `collect.yml`, schedule **12h** | 05:47 and 17:47 | Browser-engine sources (famhp, CBG-MEB, Läkemedelsverket, TGA) and the slower lists (EMA news, Swissmedic updates, PMDA company letters and ministry announcements) |
| `collect.yml`, schedule **daily** | 02:31 | Drug classes from the ATC code, large JSON files (EMA medicines, Health Canada recalls), Medsafe's Prescriber Update and NCBI literature (PubMed and PubMed Central), then EMA's EURD list (`collectors/eurd.py`), herbal substances (`collectors/herbal.py`, read by Add an ingredient) and literature monitoring list (`collectors/mlm.py`), up to 15 minutes of the check of the past, and the papers' free full texts from Unpaywall (`collectors/fulltext.py`) |
| `collect.yml`, schedule **literature** | 10:41, 18:41 and 22:41 | The daily run's drug classes, NCBI literature (the enabled sources of kind literature) and up to 15 minutes of the check of the past again, so a new ingredient is ready within hours rather than after the night (owner, 6 Nov 2026); a few minutes when nothing is waiting |
| `collect.yml`, schedule **weekly** | Monday 03:23 | SPC / label watch |
| `collect.yml`, schedule **monthly** | the 1st, 01:41 | Monthly sources |
| `trials.yml` | Wednesday 04:11 | Clinical trials of the watched ingredients from ClinicalTrials.gov (`collectors/trials.py`); only new or updated studies are fetched |
| `report.yml` | Sunday, 05:00 Cairo | Weekly report (XLSX + PDF) for the week that has just ended, Sunday to Saturday |
| `report.yml` | Every day, 07:00 Cairo | Daily report (XLSX + PDF) of the day before, Cairo midnight to midnight |
| `db-backup.yml`, backup | nightly 00:13 | `pg_dump` → gzip → age → R2 `backups/<date>.sql.gz.age` (plain `.sql.gz` with a warning while `BACKUP_AGE_RECIPIENT` is unset) |
| `db-backup.yml`, verify-archive | Sunday 00:43 | Re-hashes 50 random originals and 10 report files (`reports/`, `reports/packs/`); checks the bucket lock |
| pg_cron `pharos-watchdog` | every 30 min | Admin alert if no run has checked a source successfully in 6 h, or the database is over 420 MB |
| `probe.yml` | on demand | "Test link" from the Sources screen |
| `backfill.yml` | by hand | N months back from every source but the PV mailbox, flagged as backfill, no alerts |
| pg_cron `pharos-kick-4h`, `-12h`, `-weekly`, `-monthly` | about 50 min after each slot | Asks GitHub for that slot's collection when no run of it started (0007) |
| pg_cron `pharos-kick-readiness` | every hour at :29 | Asks GitHub again for the latest daily or literature slot (02:31, 10:41, 18:41, 22:41 UTC) until one of its runs starts (0084, 0090) |
| `rematch.yml` | by hand | The check of the past for up to 45 minutes at once (after adding an ingredient) |

`collect.yml`, `rematch.yml` and `audit.yml` share one concurrency group (`collectors`), so two of them never
run at once. A run that starts while another is running waits. If a third run arrives while one is already
waiting, GitHub cancels the waiting one; the next schedule picks up its sources. The readiness slots (daily and
literature: the drug classes, the NCBI and Europe PMC look-backs, the check of the past) are not left to the next
schedule: the database asks GitHub for the latest one every hour until one of its runs starts
(`pharos-kick-readiness`, 0084; on 6 Nov 2026 both literature slots were lost this way and the ingredients stayed
"Still preparing" for hours). Each new request takes the place of whatever waits, so a run started by hand may
need asking for again. `backfill.yml` has its own group and runs beside a collection: it can no longer hold the
queue for its 285 minutes. A notice is stored once whichever run finds it, a backfill leaves the literature
searches and the mailbox alone and sends no alert, and two runs together ask one site at most once a second.
`report.yml` has its own group, so a collection can never drop the weekly report. GitHub can start scheduled runs late at busy times (hours, on
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

**The repository is public since 6 November 2026, and GitHub's standard runners cost nothing for a public
repository.** The 2,000 free minutes of the private plan were spent in the first three days (1,190 minutes on
5 November alone, with the extra checks), and there was no card for a paid budget. The table below is the
private-plan budget, kept because it shows what each job costs; it is a limit again only if the repository
goes private.

**What being public asks of every workflow:** the code, the docs and every run log can be read by anyone.
Secrets stay hidden and are masked in logs, but a step's `env:` is printed at the head of its log, so a hand-run
input put there is public. The two message workflows (*PHAROS Telegram message*, *PHAROS Telegram steps email*)
read what was typed from the event file (`--from-event "$GITHUB_EVENT_PATH"`, `collectors/dispatch_inputs.py`)
and their logs never say who it went to or what it said; their tests fail if an input reaches a step again.
Never print a person's name, email address, Telegram chat or message text in a run log, and never upload a
run artifact with data from the database: a public repository's artifacts can be downloaded by anyone.
GitHub turns a public repository's schedules off after 60 days without a commit; a push turns them back on.

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
words are added); with nothing due it ends in seconds. The open full-text step (Unpaywall) adds up to 11 minutes
a day while the last year's papers are first looked up, then about a minute. A backfill is a one-off, at most 300 minutes. Run it in
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

One failed source never turns the GitHub collect run red. A run fails only when **more than half** of the sources it read failed (or its only source did): that is a systemic fault (the network, the database, a broken release). A single unreachable site (Jordan's timed out on 10 Nov 2026) shows here as `down` after 3 runs and sends its own Telegram alert; the run log names it in a line "1 of N source(s) failed and wait for the next run".

Jordan has a second route for that reason: `jfda-news-en` and `jfda-news-ar` read JFDA's medicine news (withdrawals, recalls, leaflet changes, warnings) from Google News, which gathers Petra, Jordan News, Jordan Times, Roya and Al Mamlaka and answers GitHub. They are headlines, not the circulars: the circulars stay on `jfda-jo` and come back on their own when www.jfda.jo answers again.

## The daily report

The owner's word (6 Nov 2026): the outcome of every day, as well as the week. `report.yml` makes it every
morning at 07:00 Cairo for the day before (midnight to midnight, Cairo): the weekly report's six sections, read
from the same functions for one day, so a day and its week never give two answers. `reports/daily/<day>/
PHAROS-daily-<day>.xlsx` and `.pdf` in R2, locked (made again: `-r2`, `-r3` …), recorded in `daily_report`
(0083), shown first on the Reports tab and sent to the administrators on Telegram. By hand: *Actions → PHAROS
daily and weekly report → Run workflow*, with the `day`. **The weekly report stays the one that is signed.**

## The weekly report

Dr Sama's review (6 Nov 2026): some findings must reach the Egyptian Drug Authority within 5 days, so the
report covers one week, Sunday to Saturday in Cairo, and replaces the monthly one. It goes into her SOP and the
pharmacovigilance system master file.

- **When.** `report.yml`, every Sunday at 05:00 Cairo, for the week that ended at midnight. By hand: *Actions →
  PHAROS daily and weekly report → Run workflow*, with the week's Sunday (`2026-11-01`), or nothing for the last week. A
  day that is not a Sunday is refused before anything is read. `month` makes a month again in the old monthly
  format (never both at once).
- **What it reads.** The Ingredients screen's own functions, so the report and the screen never give two
  answers: `ingredient_screen()` and `ingredient_papers()` for each watched ingredient, `screening_log()` for the
  reads of every source, `new_items()` and the country looks for what was new. It connects directly to the
  database (`SUPABASE_DB_URL`); `screen_reader()` (0040) lets that connection read the screen. A read is never
  filtered by what started it.
- **Six sections**, in the PDF and as sheets of the Excel file: 1 Summary and the decisions taken (her words:
  Concerns us, Doesn't concern us, No decision yet, Reviewed, no decision yet); 2 Authorities read, hers first;
  3 Our ingredients by country, with every notice, its link, the words matched and the decision; 4
  Literature, each search with its PubMed, PubMed Central and Europe PMC counts and every paper with its PubMed,
  PubMed Central and Europe PMC links (a preprint tagged); 5 Everything
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
| "The database is N MB" | Watchdog | Over 420 MB of the free plan's 500 MB | Ask the lead to prune text or move to a paid plan before 500 MB |
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

What she adds, changes and removes (owner, 8 Nov 2026: "anything in the system except people"); every write
asks for the administrator role only, so this holds for any administrator:

- **Ingredients**: add one, confirm it, change and remove its names, classes and search settings, pause it
  (*Watched*), and **Remove this ingredient** on its opened row (migration 0100). Only a fresh mistake, added and
  never screened, is deleted, with its names, classes, people's alerts on it and the figures gathered for it. One
  screened since it was added, or with notices, messages, a signal, a case, a report, its label watch, our own
  leaflet, a product, its matching checks or clinical trials, is paused instead and kept, and the app says why.
- **Products**: add, change and take off the list (*Products and cases by product*, migration 0099).
- **Sources**: add a source, switch any source on or off, add, change and remove her links, add an authority
  (0098), and add, change and remove literature references, Global and Local (0101). A source she added has **Change** (how often it is read, notes) and **Remove** (0100): if it has never
  been read it is deleted; once read, it is switched off and kept with its reads, so past weeks and PSUR intervals
  still show them. To read a different link, or one that publishes something else, add a new source. The app's own
  sources are switched off, not removed: the collector writes them back on every run.

## The app: three tabs, and the phone

"We only do screening here" (Dr Sama, November 2026). PHAROS has three screening tabs, in the order of her two passes and
the report, with the product list beside Ingredients:

- **Ingredients**: the vertical pass. One ingredient across every source for the days she chooses (below).
- **Products**: our products, each with its active ingredients and strengths (*Products and cases by product*,
  below). Everyone sees the list; an administrator adds and changes it.
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
  An admin changes this list on the card itself (0098): **Add a link**, and on each link **Change** and
  **Remove** (asked twice; the audit log keeps the old row). A link added here is not read by the app. Changing
  the address of a page the app reads moves only the link in her list, and the form says so.
- **Literature references** (first section, 0101): where the literature is screened, in two lists. *Global*:
  PubMed (NCBI), PubMed Central, Europe PMC and Cochrane are searched by the app every day (Cochrane's reviews are
  in PubMed and Europe PMC, so they are counted from those searches); Medscape is checked by hand. *Local*: the
  Egyptian medical journals the Egyptian Drug Authority asks for (Al-Azhar, Ain Shams …), checked by hand. Each line
  says *Searched by the app — N searches this week*, or *Checked by hand — who, when: nothing found*, or *not
  checked this week*. Reviewers and admins press **Checked: nothing found** (asked twice) or **Checked: found
  something** (with what was found) once a week on each hand-checked line; the check is kept and cannot be changed,
  and a check that found something speaks for the week even if a later one found nothing. A reference the app
  searches says *Nothing found* only when the ingredient's name was searched and no read failed; otherwise *Not
  searched* or *Not fully searched — check by hand*. Admins have
  **Add a global reference**, **Add a local reference**, and **Change** / **Remove** on each line (Remove switches
  it off; its checks stay). The Ingredients screen, the weekly and daily reports and the PSUR pack show the same
  references for each ingredient, with *Nothing found* written out.
- **Add an authority** (page head, admins; called "Add a local reference" before 0101): an authority she checks by hand — one PHAROS lists without
  pages of hers (Saudi Arabia, the UAE, Egypt …) or a new one — with its first link. Its country then joins her
  list, the ingredient screen and the weekly report. To stop the app reading a source, switch it off under
  *This week's reading*; a source is never deleted, as its history stays with it.
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
Dr Sama only. While `telegram_dry_run` is on, the message is only written down. A dry run (the setting, or
a manual collect run with `dry_run`) is once a day among dry runs but never counts as the real message: the
next real run still sends that day's message and counts from the last one that really went out. The class
digest follows the same rule.

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
| Health Canada InfoWatch | `hc-email`, by e-mail subscription (0077): the MedEffect e-Notice mails ("Outside of Canada", Drugs), subscribed for the PV mailbox on 6 Nov 2026, from `hc-sc.gc.ca` or `canada.ca`. canada.ca itself timed out every request from the runners (6 Nov 2026), with a browser's and with PHAROS's own user agent |
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
   names. Names that belong to another substance are left out and listed in a warning
   (`ingredient-lookup/guard.ts`, 0073): a Wikidata or PubChem name that Wikidata gives to another substance
   with a different RxNorm ingredient, to a medicine of another substance, or to a disambiguation page, or
   that RxNorm resolves only to other ingredients; also chemical formulas, and aliases of several words that
   contain none of the substance's names. On 6 November 2026 levofloxacin had "Ofloxacin", "Floxin" and
   "Floxacin", which linked the EMA ofloxacin PSUSA to it. 0073 removed those names and what they found.
   Wikidata cannot catch every wrong alias (guaifenesin's "Buchenteer" is on no other item), so still read
   each name.
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
preparation has got, and the weekly report repeats it in section 1 (migrations 0045 and 0082,
`ingredient_readiness()`):

- **Ready** when the ingredient has a name in at least one language, its drug class is made (or it has no ATC
  code, so no class), its check of the past is done, the 12-month PubMed look-back of its own name (titles and
  abstracts) has finished (0092: PubMed Central, Europe PMC and the class words search whole papers, about 150,000 a
  year for seven ingredients, so they fill in the background and hold nothing), every watched country's label watch has read since it was added (a watch that read and found no label
  is an answer), and at least one person with Telegram linked is subscribed to it. Dr Sama is subscribed to every
  ingredient by the migration, so a new one is covered the moment it is saved.
- Otherwise **Still preparing:** followed by what is still running or still to come, in order: *class words
  waiting* (the next daily or literature run: 02:31, 10:41, 18:41 or 22:41), *check of the past running* or *waiting*,
  *PubMed look-back running* or *waiting*, *Europe PMC look-back running* or *waiting*, *label watch on Monday (Japan, Spain)* naming the countries not yet read (the weekly run, Monday
  03:23), *nobody receives its
  Telegram messages yet*.
- Under the line: how many label products were found and where (or *No label found in any watched country*),
  her database pages for it (0095: *Label databases: 19 of 27 pages read · 2 waiting for the weekly run · 6 not
  read (reasons on the Sources page)*, a page counted read once a switched-on labels source reading it has run
  since the ingredient was added; it never holds Ready back), the EURD list's PSUR frequency, data lock point and submission date (the EURD list is read daily again,
  `collectors/eurd.py`), whether EMA's literature monitoring covers it, and who receives its Telegram messages.
- **Japan:** PMDA's search is a form that answers a POST only, so PHAROS cannot look a package insert up by
  name. The term editor has a *Japan codes* field when an ingredient is added, and an administrator finds the
  same field on any ingredient already on the watchlist: open its row (the triangle beside the name), then
  *Japan codes*. Open the PMDA search (link beside the field), search the name, open the product and copy the
  7-character code from its address (`…/GeneralList/<code>`; the 12-character YJ code is accepted and kept as the
  7 characters it starts with), then **Save**. PMDA files each form under its own code (paracetamol: 1141007
  tablets, 1141700 suppositories, 1141400 injection): type every one, separated by commas. The row shows the codes
  it has now, each with a link to its products on PMDA; **Save** keeps exactly the codes typed, removes one left
  out, and leaves every name alone (`set_japan_codes()`, migration 0069; audited). A wrong code is named and nothing
  is saved. Japan's label watch reads every code at its next weekly run. Like any new word it is due for the check of the past that
  night (0034); the readiness line does not wait for that, since a code is not a name. Without a code the row says *No Japan code
  yet, so Japan's label watch cannot find its package inserts*; it never holds Ready back. A code typed here is
  trusted. A code PHAROS only took from a PMDA revision notice matched to the ingredient is read only when the
  PMDA page's 一般名 names the ingredient in Japanese (a notice lists several ingredients, so its links reach all
  of them); without a Japanese name it is skipped, and the run log says so.
- **One label, every ingredient in it:** a label that holds several watched ingredients (a cold remedy with
  paracetamol, guaifenesin and phenylephrine) is watched once for each of them (migration 0079). A change to it
  opens one issue, linked to all of them, and is alerted once. Before 0079 the first ingredient to list a label
  kept it: Japan's acetaminophen inserts were filed under ivabradine, and paracetamol had none in Japan.
- **United States:** DailyMed is searched by the ingredient's RxNorm code as well as its names, since a name
  may not be the US one (paracetamol found none by name; acetaminophen's code 161 finds 791 prescription
  labels). Its prescription labels are read to the last page (acetaminophen: 765 by name), and the
  over-the-counter labels FDA approves one by one (NDA, ANDA, NDA authorized generic: acetaminophen 292,
  guaifenesin 396, phenylephrine 8 on 6 Nov 2026). The OTC monograph labels (about 3,700 store brands of
  acetaminophen) are not read: their wording is FDA's monograph, changed by an FDA order, not by the label.

### Editing an ingredient on the watchlist

Open its row (the triangle beside the name), then **Edit names** beside *Names looked for* (administrators). Change
the English name or any name: its wording, kind, matching, exclusions or country; add a name or a language; or
press **Remove** (an emptied name is removed too). Nothing is written until **Save**; **Cancel** leaves it as it
was. The rows are written directly (the ingredient_term admin policy, 0001; every change is in the audit log), so
the edit is not one step: if a write fails part-way, the screen says so and the list shows what the database holds.
A new or changed name is due for the check of the past that night (0034). The Japan codes are not in this editor;
they keep their own field on the row. The ATC code is not edited here (classes are made from it).

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
- **Databases read.** The weekly summary also says how many of her label database pages were read that week, for
  example *19 of 27 pages · 8 not read by the app (reasons on the Sources page)* (`label_databases`,
  `collectors/report_weekly.py`). A page is read when a switched-on labels source that reads it completed a run in
  the week. *Not read this week* means its source did not complete a run that week. *Not read by the app* means no
  source reads the page at all. The daily report leaves this line out, because the label watch runs weekly.
- **Days.** Section 03 and the report filter by the Cairo day the change was **detected**, not by the date printed
  on the label (a label dated 1 October found on 3 November appears in the week of 3 November).
- **Time, and labels read in turn** (0063, 6 Nov 2026). The watch keeps to the run's time budget
  (`PHAROS_TIME_BUDGET_MIN`: 78 minutes on the weekly run, 108 on a run started by hand). Each country gets an even
  share of the time left, and a country that finishes early leaves its time to the next. Within a country the
  labels are read in turn: **the reference product first**, then labels never read, then the one read longest
  ago (`spc_product.checked_at`). What the time does not reach is read first the next week; the source's run
  says *out of time: N label(s) left for the next run*, which is not a failure. An ingredient with hundreds of
  products in one country (paracetamol: Spain, France, the US) is covered over two or three weeks; its
  reference product every week. Before this, on 6 Nov 2026, paracetamol's products ran a hand-started watch to
  GitHub's two-hour timeout and the run was killed before it reached Japan; Monday's 90-minute run would have
  been killed the same way, for every ingredient.
- **A list that breaks off never switches products off** (0089, 0085, 7 Nov 2026). A product is marked no
  longer authorised only when the country's list for the ingredient was read to its end. When a page, a
  Japanese code page or a UK search page did not answer, the run notes *partial list: …* and keeps every product
  listed before, and their labels are read as usual. An empty answer where products were listed before is a
  failed discovery (*listed no product; N listed before kept*), not every product withdrawn at once. A list that
  failed outright still reads the labels already known. A label that does not answer (an HTTP error, a file that
  is not a PDF) is an error on that product and is read first the next week; only a label that answered with no
  section counts as *without label text*. A label two ingredients share is read in full for each of them. Spain
  is searched by ATC code and by the Spanish name, so combinations are found; the UK search reads every page
  (up to 40) of up to four English names, and a UK product without a PL number keeps its name as its id, so a
  new SPC file is the same product. A run that only ran out of time shows as a note, not as Failed (0089). On
  7 Nov 2026, 99 Japanese package inserts filed under ivabradine by codes it does not have (paracetamol's among
  them) were switched off once (0085).
- **The regulator's version decides what is read first** (0086, 7 Nov 2026). Each snapshot keeps the label's
  version as the regulator's list gives it: DailyMed's SPL version, PMDA's package id, CIMA's document date,
  EMA's last update, MHRA's document id (France's list names none). A label whose listed version moved is read
  first, ahead of the labels read in turn; a label still listed at the version last read is not read again for
  28 days (our reference product always is). The time saved goes to the labels that changed.
- **Sections read** (7 Nov 2026). US labels: the old-format PRECAUTIONS (with pregnancy, nursing, paediatric and
  geriatric use inside it) and Recent Major Changes are read and watched too; an OTC label's Warnings already
  held "Do not use", "Ask a doctor" and "Stop use". An EPAR's product information is read one SmPC per strength
  or form (the second one's sections are *smpc2:4.4* …); before, every SmPC after the first ran on inside the
  first one's section 10. The first read of a US label or an EPAR this new way is a new baseline, never a change.
- **Proven on a real revision** (7 Nov 2026). *PHAROS label change replay* (`replay.yml`, by hand: a DailyMed
  set id and two versions) reads two published versions of one label the way the watch reads them and names the
  sections that changed and those that would alert; nothing is stored and no message is sent. Corlanor
  (ivabradine) versions 16 and 20, the April 2019 approval for children, alert in warnings and precautions,
  contraindications, adverse reactions, interactions, specific populations and Recent Major Changes; versions 31
  and 33 have the same safety sections and give no change. The pair is a CI test (`tests/test_spc_replay.py`).
- **What was read, on screen** (0091, 7 Nov 2026). Under *Label changes* on the Ingredients screen, *Databases
  read* lists every database page of her list for the ingredient: the products listed, the labels read and
  those waiting their turn, each label that could not be read with its error (`spc_product.last_error`, cleared
  when a read succeeds), the newest label date, the newest change found, and whether the list was read to its
  end (`spc_listing`; a list that broke off says where). The pages needing a look come first; a page the app does
  not read comes last with its reason. On the Sources page each database page read by the label watch has one
  line with the same counts over every ingredient (`label_watch_sources()`).

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
  is "due" until every stored notice, whatever its date, has been checked with it (0072; until 6 November 2026
  only the last 12 months, which left 48 older notices naming a watched ingredient unlinked). The daily
  run gives it 15 minutes after the collection; `rematch.yml` runs it by hand for up to 45 minutes. It reads
  each notice's kept text, or its original again from R2 (page, PDF with OCR, attachments), skips words that
  already matched that notice, and files what it finds as history: no Telegram message, no digest. A
  class-only issue its class's words had already found gains the ingredients that search the class now. On the
  0055 deployment the words of every class a watched ingredient joined after they were last checked became due. Its
  progress is the `rematch_job` row (one open at a time): the next run continues from
  `cursor_document_id`; when it reaches the end its words are marked checked, and a word changed meanwhile
  waits for the next check. A check narrowed by hand (`--months`, the workflow's "months") marks nothing
  checked: its words wait for the next full check. On the 0072 deployment every word became due again (except
  the names found to belong to another substance), so the first checks after it read every stored notice. A list page shared by several notices is not read as any one notice's text.
  Literature has its own search and is not checked here.
- **After the 0034 deployment** the words the 12-month backfill already covered are marked checked;
  everything added after it (levofloxacin, added 5 November 2026) is due, so the first daily run starts on it.

## Completeness and the matching audit

**What keeps a notice from being lost**
- **UK.** MHRA is read from GOV.UK's search API, newest first. Paging stops at the first item already stored,
  and a backfill reads the whole list (`collectors/parsers/govuk.py`, `mhra-alerts` and `mhra-dsu`). The Atom
  feeds held only the newest 15–20 items.
- **Filters.** What a source's keyword or category filter leaves out is kept in `filtered_item`, with its title
  and the reason (0074). The Sources screen shows the count. A keyword filter never drops a notice that names a
  watched ingredient.
- **Gaps.** A run that lists only items never seen before, from a source that already has stored items, has moved
  past the last read. The run logs "Possible gap" with the oldest date listed, and the admins get a health alert
  (`possible_gap`, `collectors/run.py`; not for mailboxes, literature or labels).
- **Matching.** The check of the past reads every stored notice for a new or changed word, whatever its date
  (0072). The weekly matching audit (`audit.yml`, Sunday 00:53 UTC) then looks for stored notices that contain an
  ingredient's own name but carry no link to it. It links each one it finds and lists the names RxNorm gives to
  another substance (`match_audit`, 0075; shown on the Ingredients screen).

**Proof, 7 Nov 2026, 07:41–08:10 Cairo** (live database, after the UK backfills, the check of the past and the
first audit)
- **UK:** 1,465 of GOV.UK's 1,465 drug and device alerts are stored, plus the 90 letters taken from the safety
  roundups, and 871 of 871 Drug Safety Updates. Before: 130 and 100.
- **Missed links:** 1 notice of 631 that contain paracetamol's name has no link to it (a PubMed paper on
  electrochemical detection of paracetamol). Every other ingredient has 0. Before: 48, all older than 12 months,
  for example MHRA's "Paracetamol and pregnancy" and Denmark's 2014 ivabradine letters.
- **Names of other substances:** none of the nine is left (Ofloxacin, Floxin, Floxacin, ペントキシベリン, Buchenteer,
  C10H14O4, C9H13NO2, "Canada og Japan", "acetaminophen i USA"). The four EMA ofloxacin PSUSAs are not linked to
  levofloxacin, and Austria's "21900" table cell no longer matches ivabradine's code 2190039.
- **Words:** all 312 watched words have been checked against every stored notice.
- **Known false flag:** levofloxacin's stored RxNorm code is 1546009, "levofloxacin anhydrous" (a precise
  ingredient), not 82122, the ingredient. So the audit flags six of its own names (L-ofloxacin, Levaquin,
  Levofloxacin anhydrous, Levofloxacine, Levofloxacino, Levofloxacinum) as "RxNorm: levofloxacin". They are
  right: never remove them. Lornoxicam has no stored code, while RxNorm's is 20890.
- **Before the list check:** the proof above was made by hand for MHRA. EMA's DHPCs (172 human letters, the 4
  veterinary ones filtered on purpose), BfArM and MFDS were checked by hand on 6 Nov.

**The weekly list check** (`collectors/completeness.py`, `audit.yml` after the matching audit, `list_check` 0096)
- Every switched-on notice source's own list is read again whole, the way a backfill reads it, with the same parser
  and filters. Nothing is stored or archived and no message is sent. Mailboxes, literature and the label databases
  are not lists of notices and are not checked.
- Each listed notice is **stored**, **older** than the kept history (`backfill_months`; EMA's `backfill_all`
  sources keep all of it), or **missing**: listed, inside the kept history and not stored. What the filters left
  out is counted apart (`filtered_item`).
- The Sources screen shows one line per source: "Whole list checked …: all N notices listed are stored", or how
  many are not stored with the newest one named. A list read only in part, or not at all, is never shown as
  complete. With the technical details on, the line is shown for every source; otherwise only when it needs a look.
- To store what is missing: run `backfill.yml` for that source.

**Proof, 7 Nov 2026, 22:56–23:05 Cairo** (`audit.yml` started by hand, the first live list check, and the matching
audit after the RxNorm codes were fixed)
- **List check:** 48 notice sources read whole. 10,050 notices listed: 9,694 stored and 356 older than the kept
  history (WHO, HPRA, PMDA revisions, MFDS, NoMA, ANSM, EDA, MPA, Infarmed). **0 missing.** 191 left out by
  filters, the same count as `filtered_item`. UK: 1,555 alerts (with the roundup letters) and 871 Drug Safety
  Updates, all stored.
- **Not checked here:** the five mailboxes (FDA, Health Canada, FAMHP, TGA and Fimea e-mail), PubMed and Europe PMC,
  and the label databases.
- **Matching audit:** 229 notices name one of the seven ingredients; 0 are unlinked and 0 names are flagged.
  Levofloxacin now carries RxNorm 82122 and lornoxicam 20890 (0094), so the false flag above is gone.

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
  Today is the database's Cairo day, never the phone's. After a decision the screen reads the clock again from
  the database, so with `eda_day_zero` = `decision` a new *Concerns us* shows its new due day at once.
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
  sends it right after the new-items digest, never on a backfill, and a failure never fails the run). A long
  list goes in parts: a part Telegram refuses is tried again at the next run with the parts after it (they wait
  for it, so the parts arrive in order), and the parts the person already has are not sent again.
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
- **Never changed.** `sign_off` is append-only (a row trigger refuses any update or delete and a statement
  trigger any truncate, even by the database owner, 0060; the service key holds no right to write a signature,
  so only `sign_record()` adds one). `audit_log` too (0046): a row trigger refuses every update and delete, a statement trigger every
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
(the day after the previous data lock point to the next one, as EMA's list sets it; when a short month cut the
data lock point, 28 February for a cycle on the 31st, the list's next data lock point gives the day), cut at
today; an ingredient
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
  the archive checks, the changes in the audit log counted per table, the people and their roles, and the
  quality records of the days (deviations, audits, the CAPA plan; see *Quality: deviations, audits and CAPA*).
- **The files.** A4 PDF and an Excel file with a sheet per section, archived in R2 under
  `reports/packs/<psur|inspection>/<request id>/` (never overwritten: a pack made again is stored as `-r2`),
  with the SHA-256 of each on the request, the code (`git_sha`) and the run that made it. Reports shows both
  files with their SHA-256 and the signatures, exactly as a weekly report.
- **Who is told.** The person who asked (when their Telegram is linked) and every administrator; for an inspection
  pack, administrators only: "pack ready",
  with the PDF attached up to 20 MB, or "pack not made" with the reason. Dry run as every message: with
  `telegram_dry_run` on, the notification is recorded and nothing is sent.

## NCBI literature (PubMed and PubMed Central)

- **What is searched.** Every day (the daily run), for each active ingredient: its English name (INN) together
  with its other English names matched as words (synonyms and salts of mode stem, such as "acetaminophen" for
  paracetamol; never a brand, a code or an exact-only acronym such as "APAP"), on PubMed and on PubMed Central.
  Each name is a quoted phrase searched in titles and abstracts only (`"paracetamol"[tiab] OR
  "acetaminophen"[tiab]`; owner, 7 Nov 2026). Before that, the unquoted words were searched in PMC's full texts
  with every class word, about 140,000 papers in a 12-month look-back, most naming the ingredient in passing.
  Class words are searched only for a class an administrator switches into the literature; every class is out of
  it by default since migration 0093 (the words are still searched in the authorities' notices). The run reads
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
- **Capacity.** About 3 KB of database per paper: 50,000 papers is about 150 MB. The watchdog warns at 420 MB.
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
- **Free full text (Unpaywall, migration 0070).** Once a day, after Coding, `python -m collectors.fulltext` looks
  up each literature paper of the last year at Unpaywall (`api.unpaywall.org/v2/{doi}`, no key, identified by
  pharos@satopharma.com; Unpaywall allows 100,000 calls a day, PHAROS makes at most 2,000 a run, about four a
  second, in at most 11 minutes). Before that it asks PubMed again, at most every 30 days, for the DOI of the
  papers stored without one (a paper ahead of print often gets it later). What Unpaywall says is kept in
  `document.structured.oa`: whether a legal open copy exists, the best one's address, PDF address, licence
  (`cc-by`, `cc-by-nc-nd`, `cc0`, `publisher-specific-oa` …, or none stated), version (*published*, *accepted*
  manuscript or *submitted* preprint) and host (*publisher* or *repository*), the PDFs to try for a case, and
  when it was asked. A paper with no open copy is asked again after 30 days; an open one is not asked again. A
  failed lookup waits for the next day and never stops the others. On the Ingredients screen a paper with an
  open copy shows **Free full text** (the best open location) beside its PubMed links, tagged with the licence
  and the version; `paper_state()` returns it as `open_access` (only an http(s) address). The licence says what
  may be done with the copy: reading it for safety is always allowed, reusing it may not be. Live on 6 November
  2026: 10.1038/nature12373 was open (the publisher's PDF, which answers a script with a cookie page, plus an
  arXiv preprint), 10.1002/pds.5000 closed, and a DOI Unpaywall does not know answers 404.

## Europe PMC literature (second source, migration 0066)

- **What is searched.** The source `europepmc` (`collectors/parsers/europepmc.py`, regulator EBI) runs after
  NCBI in the daily and literature runs and searches Europe PMC's REST API for the same words NCBI is searched
  for: each active ingredient's English names and the English words of any class switched into the literature.
  Each name is a quoted phrase in the title or abstract, `(TITLE_ABS:"paracetamol" OR TITLE_ABS:"acetaminophen")
  AND (SRC:MED OR SRC:PMC OR SRC:PPR) AND FIRST_IDATE:[from TO to]`, with `synonym=false`, as NCBI's `[tiab]`
  (owner, 7 Nov 2026), so it finds the abstracts Europe PMC holds plus preprints (Research Square, medRxiv,
  bioRxiv …), which NCBI does not list.
- **One paper, one document.** Before storing, the run looks every hit up among the papers the other literature
  sources stored, by PMID, PMC id and DOI (case ignored). A paper NCBI already stored is not stored again: its
  `structured.found_in` and the search's `db` list gain `europepmc`. The NCBI run does the same the other way,
  so whichever source finds a paper first stores it. A new paper is a literature document with the same fields
  as NCBI's, under its PMID, else its PMC id, else its Europe PMC id (a preprint's `PPR…`), linked to its
  Europe PMC page and, when it has them, its PubMed and PMC pages.
- **Preprints.** A paper from SRC:PPR has `preprint: true`. The Ingredients screen shows it with a *Preprint*
  tag and "not peer reviewed", and the literature line counts Europe PMC beside PubMed and PMC and the preprints
  apart. Europe PMC gives no language: its papers are stored as English. A preprint is typed "preprint", so it is
  usually a possible case report by its title alone.
- **Look-back and catch-up.** The same rules as NCBI (`literature_search` rows with `db = 'europepmc'`): a
  new word reads 12 months as history, then each run reads from the last complete run minus 3 days. While the
  source is switched on, an ingredient is not Ready until every word's look-back here has finished too
  (`ingredient_readiness()`, migration 0082).
- **How fast.** Europe PMC first lists ids only (1,000 a page, under a second), then reads the new papers' records
  100 at a time, half a second between requests. A run spends at most 6 minutes searching (words searched
  before go first, then the look-backs; a word not reached keeps its row and goes first next time), stores at most
  800 new papers and stops at 10 minutes. Volumes for 12 months on 6 November 2026: carvedilol 1,424 hits (14
  preprints), paracetamol 6,925, metformin 15,618 (253 preprints); most are already stored from NCBI.
- **Etiquette.** No key. The request says who we are in its User-Agent ("PHAROS pharmacovigilance literature
  watch" and the company mailbox), never in the address, so no log line carries it.
- **Case intake.** *Open a case* on a paper with no PMID or PMC id reads its Europe PMC record (the abstract)
  and marks a preprint "not peer reviewed".

## Case reports in the literature

A paper reporting a case with one of our products starts a clock the day PHAROS finds it (her decision, 6
November 2026): a valid serious case reaches the Egyptian Drug Authority within 15 days, a non-serious one within
90. Day zero is the Cairo day the paper was first seen, never its publication date.

- **The flag.** The collector marks each paper as it is stored (`document.structured.case_report`,
  `collectors/parsers/pubmed.py`): PubMed lists it as *Case Reports*, or its title says "case report", "case
  series" or "a case of" (the words of `v_case_report`, 0031). Migration 0044 flagged the papers stored before
  it with the same words. A paper found only by a class word is flagged too but, like a class-wide notice, is
  not in the daily message.
- **It must name the ingredient** (owner, 8 Nov 2026). After its searches each literature run checks every
  flagged paper once (`collectors/case_names.py`): it keeps its flag only when its title or abstract names an
  ingredient whose name search found it (the English INN or another English name matched as words), asked of
  PubMed (`"name"[tiab]`) or, with no PMID, of Europe PMC (`TITLE_ABS`). Otherwise the flag is cleared
  (`structured.case_report` null, the old one kept as `case_report_was`; `names_checked` is the day). A paper
  only class words found is cleared without asking (migration 0097 cleared those at once). A paper not answered
  (NCBI or Europe PMC down) waits for the next run. On 7 Nov 2026 this left 420 of 2,516 flagged papers.
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

## Individual case reports (Cases)

The **Cases** tab (migration 0059) holds each individual case safety report from the source document to the
file the authority takes. A case opens three ways:

- **Upload.** A reviewer or an administrator drops the report on *Cases → New case*: a PDF, a photo of a form, a
  Word file (.docx), a saved email (.eml) or a text file, at most 10 MB, with day zero (the day the company first
  received it; today or within the last year). The `case-intake` function checks what the file really is from
  its bytes, stores it in the archive under its SHA-256 (never overwritten) and opens the case.
- **A literature paper.** On an ingredient's page, a paper flagged *Possible case report* has **Open a case**.
  Day zero is the day PHAROS found the paper. PHAROS fetches the paper's PubMed record and, when PubMed Central
  holds it openly, its full text, and archives them as one text file. When PubMed Central has no full text but
  Unpaywall lists a legal open copy as a PDF, PHAROS fetches it (public addresses only, every redirect checked,
  at most 20 MB, and only an answer that is a PDF by its type and its first bytes; the best copy first,
  then the repositories'), archives it under its SHA-256 with its licence, version, host, address and DOI in the
  archive's metadata, and names it in the text file (`Open-access PDF: sha256/…`); the reader then receives the
  PDF beside the record, checked against its SHA-256. A copy that cannot be fetched (a cookie page, a bot check,
  a private address) is said in the text file, and the record alone is read. A paper opens one case at most;
  once open, the paper shows a link to its case.
- **Forwarded email.** A reviewer or an administrator forwards the report to pharos@satopharma.com with the word
  CASE in the subject. Every 4-hourly run opens a case for it with the forwarding person as its creator and the
  day the message is dated (Cairo) as day zero. The sender must be the person's own address in People, and the
  receiving mail server's check (or PHAROS's own DKIM check) must pass for it; anything else is left unread.

**Reading.** As soon as a case opens, the app starts `.github/workflows/case-read.yml` with only the case's id.
It reads the archived original back, checks its SHA-256, and sends the document to the case reader (Anthropic's
Claude, model `claude-opus-5-5`) with the names of the watched ingredients. The reader fills the case form
(patient, reporter, products, reactions with their seriousness criteria and outcome, a narrative) and quotes the
words of the document behind each field; a field the document does not state stays empty. The answer is kept
unchanged in `safety_case.extracted`; the form the team works on is `data`. The reader never decides
seriousness, never codes MedDRA and never confirms. When the app could not reach GitHub, the "Cases" step of the
next 4-hourly run reads the case. A passing failure (the service busy, the network) is tried again on the next
run; after three tries, or for a document the reader cannot take, the case shows *Could not be read* with the
reason and **Read again**.

**What leaves PHAROS.** Only the document goes to the reader, over the Anthropic API, under the company's own API
account and its data terms. Nothing else from the database is sent.

**Checking and confirming.** The case page shows the document (**Open the document**), the four minimum criteria
of a valid case (an identifiable patient, an identifiable reporter, a suspect product, a reaction) as *Present* or
*Missing*, the clock, and the form with the quotes under each part. A reviewer corrects the form against the
document, decides seriousness, chooses the product and its strength or the ingredient, and presses **Save** or **Confirm the case**. The database
refuses a confirmation without the four criteria, a product or an ingredient, and the seriousness decision. **Not a valid
case** needs a comment. Two people changing one case at once: the second is told to reload.

**The clock.** Day zero plus 15 days, or plus 90 once a reviewer says the case is not serious; until then it
counts as serious. The list shows the days left, and the clock in red once the day has passed.

**Sent, follow-up.** After sending, **Record as sent** keeps the day and the authority's reference. A follow-up
**Reopen**s the case with a comment and, when new information arrived, a new day zero.

**The E2B(R3) file.** For a confirmed or sent case, **Make the E2B file** builds the ICH E2B(R3) message
(`collectors/cases/e2b.py`) from the confirmed form and archives it under `reports/cases/<case number>/`, with its
SHA-256 shown on the case. Each reaction needs its MedDRA LLT code and version, typed by the reviewer from the
MedDRA browser (PHAROS holds no MedDRA licence and never invents a code). Until the first file has passed the
Egyptian Drug Authority's gateway test, the file is a prepared draft to check before sending.

**The CIOMS I form.** For a confirmed or sent case, **Open the CIOMS I form** makes the one-page CIOMS I suspect
adverse reaction report in the browser (`web/src/features/cases/cioms.ts`) and opens it in a new tab, where it is
saved as PDF and attached to the e-mail to the authority. It needs the four minimum criteria and the seriousness
decision but no MedDRA code: the reactions go in English with the reporter's own words beside them, and a typed
MedDRA code and version are printed beside a reaction only when there. It is the route while PHAROS has no MedDRA
subscription (asked of MSSO on 8 Nov 2026). The form is not archived by PHAROS; the sent PDF is the record, with the
day and reference written on the case when it is marked sent. Dechallenge and rechallenge (boxes 20–21) are printed
as not stated, since the case does not hold them.

**History.** Every step (received, read, saved, confirmed, not valid, sent, reopened, the E2B file, notes) is one
row in `case_event`, append-only, with the person (or PHAROS) and a copy of the form at each save and
confirmation.

**Actions minutes.** One reading is one short run of `case-read.yml` (about two minutes with the package cache).

## Products and cases by product

Dr Sama's feedback of 8 November 2026: a case is reported against a **product**, and one of ours may combine
several active ingredients (carvedilol + ivabradine), each in its own amount per strength (6.25 mg / 5 mg). The
**Products** tab (migration 0099) holds that list; the literature, the label watch, the weekly report and the
readiness stay per ingredient, and a product is watched through each of its ingredients.

- **Adding a product** (administrators): *Products → Add a product*: the name, the marketing authorisation holder,
  the dosage form, the ingredients (ticked from the watched ingredients; an ingredient must be on the watchlist
  first), and one or more strengths, each with an amount and unit (mg, g, µg, mL, IU or %) for every ingredient.
  A strength left unnamed is named from its amounts ("6.25 mg / 5 mg"). **Change** reopens a product.
- **Taking a product off the list**: a product a case names is **archived** (kept on that case, no longer offered
  on new cases; tick *On the list* to bring it back); one no case names is deleted. A strength a case names cannot
  be removed.
- **New case** and the case page: the first choice is *Product or ingredient* (our products first, then the single
  ingredients). Picking a product shows *Strength* (a product with one strength takes it at once) and fills the
  suspect drug line: the product's name and strength, and each ingredient with its amount. What the reviewer wrote
  on that line (dose, dates, batch) stays. A case is confirmed with a product or an ingredient.
- **The reader** receives the product list with the document. A case opened for a product keeps it; otherwise
  PHAROS picks the product the suspect drug names, by its brand or by all of its ingredients (its strength only
  when the brand is named), for the reviewer to check.
- **Signals**: a case of a product counts on the page of each of its ingredients.
- **The E2B file** writes each ingredient of the product with its amount (G.k.2.3.r).

Deploying: apply migration 0099 before the new app, the `case-intake` function and the collectors (the reader
reads the product list, and the case functions take the product).

## Medical coding (MeSH and RxNorm)

The company holds no MedDRA or WHODrug licence, so PHAROS codes cases against two free dictionaries of the U.S.
National Library of Medicine (migration 0061). Both ask only that NLM is named as the source and never as
endorsing PHAROS; the case page says so under the reactions.

- **Reactions, indications, medical history: MeSH** (Medical Subject Headings), the disease tree (C) and mental
  disorders (F03): about 5,200 descriptors and 60,000 names. *PHAROS dictionaries* (`dictionaries.yml`) checks on
  the 2nd of every month and loads a new release when NLM publishes one (once a year). Run it by hand once after
  the first deploy of 0061.
- **Products: the watchlist, then RxNorm.** A product whose name or brand is a watched ingredient's is that
  ingredient; anything else is looked up on RxNav (NLM's free RxNorm service), at the ingredient level, with each
  ingredient's UNII (the FDA's substance code).

**How a case is coded.** Right after a case is read, and on **Suggest the codes again** (after the words of the
form changed and were saved), `collectors/coding/coder.py` suggests the codes. For each reaction, indication and
medical-history condition, best first:

1. *Chosen before*: the code a reviewer chose for the same words in a confirmed or sent case. Every
   confirmation teaches the next suggestion.
2. *Suggested*: the reader (Claude) names the condition in standard English from words in any language, PHAROS
   looks those names up in MeSH, and the reader picks the most specific descriptor among what MeSH returned, with
   one sentence of reason. It can only choose a descriptor PHAROS found; it never writes a code.
3. *Closest name*: MeSH's names closest to the words themselves (all there is when the reader is not set up).

The suggestions are kept beside the form (`safety_case.coding`), never in it: nothing is coded until a reviewer
presses **Use**, and a page open on the case never goes stale because of them. A reviewer can also search MeSH on
the case page. The chosen codes are saved and confirmed with the form, and kept in each `case_event` copy.

**MedDRA.** The E2B(R3) file still needs each reaction's MedDRA LLT code and version (ICH E2B and the EDA take
MedDRA only); the reviewer types them when the authority or a partner has coded the case. MeSH codes do not go
into the E2B file.

**MedDRA from the subscription (migration 0102).** The PSMF inspection noted that the company had no MedDRA
subscription. Once MSSO sends the release, an administrator uploads it in *03 MedDRA* on the Cases screen: the zip
as MSSO sends it (`MedDRA_xx_x_English.zip`, a zip inside it is opened too), or the `.asc` files of its `MedAscii`
folder when the zip is locked with a password. The files go to the private storage bucket `meddra` (administrators
only) under `uploads/<UTC time>/`; *PHAROS dictionaries* (job `meddra`, every two hours) loads the newest upload
asked for in one transaction (`meddra_pt` with each PT's primary HLT, HLGT and SOC; `meddra_llt` with currency) and
writes its answer on the upload, which the panel shows. On the case page each reaction then has *MedDRA code*:
"Search MedDRA" (words or an 8-digit code; the LLT chosen before for the same words first, a non-current LLT
last), and "Use" writes the LLT code and the loaded version into the form. A typed code is named from the
dictionary, and a code not in it, a non-current LLT or another version is flagged. MedDRA's files and terms never
go into this repository or a run log (the log names the version and counts only); the tests use invented codes.
A new release (MSSO publishes in March and September) is uploaded the same way and replaces the old one.

**What the coded terms say (migration 0062).** Section *05 Reactions by MeSH* of the Ingredients screen counts, for
the days chosen and the same number of days just before:

- *Cases*: the reactions as the reviewers coded them, in cases to confirm, confirmed or sent.
- *Papers*: the literature papers of the ingredient (suggested links left out) whose MeSH headings NLM's indexers
  marked "chemically induced" (qualifier Q000139) or put under Chemically-Induced Disorders (C25). The daily
  *Coding* step of *PHAROS collect* (`python -m collectors.coding --papers --labels`) fetches the headings from
  PubMed for every literature paper of the last year; a paper NLM has not indexed yet is asked again after 30 days.
- *Safety topics* (`safety_topic`): 31 groups of MeSH descriptors with everything beneath them in the tree (liver
  injury, severe skin reactions, QT prolongation, suicide and self-harm …), in place of MedDRA's SMQs, which need a
  MedDRA licence. A topic is a search aid, not an SMQ.
- *Label*: the same step finds the MeSH names in section 4.8 of our label (when it is in English) and in the
  reference product's latest English label (else any English label of the ingredient: SmPC 4.8 or the US "Adverse
  reactions"). A reaction is *In our label* when our label names it or a broader heading above it, *In the reference
  label* when only that one does, and *Not in our label* when neither does; when no label of ours in English is
  coded, a reaction the reference label does not name is *Not in the reference label* instead. The same tag is on
  each coded reaction of a case. A label is read again when it changes or a MeSH release is loaded.

Counting is not judging: the numbers and the label are shown side by side, and the team decides whether a term is
a signal (Signals). *Not in our label* means no MeSH name was found in the text, which is a reason to read the
label, not a finding that the reaction is unexpected.

## FDA adverse event reports (FAERS)

Section *06 FDA adverse event reports* of the Ingredients screen counts the reports to the FDA Adverse Event
Reporting System (FAERS) that name the ingredient (migration 0071). The weekly workflow *PHAROS FAERS counts*
(`faers.yml`, Wednesday 04:13 Cairo; `python -m collectors.faers`) asks openFDA (`api.fda.gov/drug/event.json`) to
count them; no report is downloaded, only numbers come back, and the log names no ingredient.

- **The period**: the last 8 complete calendar quarters openFDA holds, by the day FDA received each report (on 6 Nov
  2026: October 2024 to September 2026, 2.68 million reports). FAERS changes once a quarter, so an ingredient counted
  in the last 6 days is left; run the workflow by hand with *force* to count every ingredient again.
- **The drug over-represented with a flag** (migrations 0076, 0078): one report names every drug the patient took,
  and the count takes a report whatever role the ingredient had in it. For each flagged reaction the run asks openFDA
  which other drugs those reports name (`activesubstance.activesubstancename`, the substance FAERS coded, the 25 most
  frequent; `openfda.generic_name` missed relugolix in every one of those reports), leaves out the ingredient, a salt
  of it and a combination holding it, and weighs each against all the ingredient's reports of the period (one list a
  run, only when a reaction is flagged; a drug missing from a list too long to be whole is counted on its own). It
  keeps the most reported drug named in at least 3 of the reaction's reports and in a share of them at least twice
  its share of all the ingredient's; section 06 shows it under the flag ("Most often with RELUGOLIX (84% of these
  reports, <1% of all CARVEDILOL reports)"). Found on 6 Nov 2026: carvedilol's HOT FLUSH (PRR 4.1) came from reports
  naming the prostate-cancer drug relugolix as the suspect in 199 of 239, with carvedilol only taken alongside; the
  weighing (0078) drops drugs taken with the ingredient whatever the reaction (aspirin, furosemide or amlodipine in
  25–43% of a reaction's reports), which explain nothing.
- **A flag that stands on one repeated case series** (migration 0081): one patient can be reported to FDA many times
  (every follow-up is a report, and a published case is filed by each company selling a drug it names), and each
  report repeats the same list of reactions. For each flagged reaction the run counts its reports by the patient's age
  in years (`patient.patientonsetage` with `patientonsetageunit` 801), takes the age whose year either side holds the
  most (ages under 2 left out: babies share an age without being one patient), and counts that band's reports by sex.
  When one sex in that band holds at least a quarter of the reaction's reports, and at least 5, the flag is kept and
  marked "One case series?" on section 06; its tooltip gives the group ("18 of the 28 reports of PSORIASIS describe a
  man aged 54 to 56"). Up to two more requests per flagged reaction. Whether the flag would stand without the group is
  not asked: a quarter of the reports give no age, so the same patient's undated reports keep it standing
  (paracetamol's lupus would fall and its pemphigus stand, both from one woman of 44). Measured on 6 Nov 2026 (ages of
  any unit): 20 of paracetamol's 26 flags (a woman of 43–45, with leflunomide), 12 of levofloxacin's 22 (a man of
  64–66), 18 of ivabradine's 27 (mostly a man of 54–56), 21 of phenylephrine's 29, 3 of guaifenesin's 8, none of
  carvedilol's 13.
- **How an ingredient is found**: its INN in capitals, exactly, in three fields at once: `openfda.generic_name` and
  `openfda.substance_name` (filled only when FDA matched the product to a US label) and
  `activesubstance.activesubstancename` (the substance as FAERS coded it, also for products sold outside the US).
  Checked on the live API on 6 Nov 2026: carvedilol 136,140 reports in each US field and 142,304 in the three
  together; lornoxicam, not sold in the US, none in the US fields and 396 as the active substance. An exact search
  takes the whole value only: a salt written with the name ("CARVEDILOL PHOSPHATE") is not counted. A US name that
  differs from the INN is searched with it: RxNorm's name for the ingredient's RxNorm code (FDA files paracetamol as
  ACETAMINOPHEN, 100,540 reports, and has none under PARACETAMOL). When RxNorm does not answer, the ingredient keeps
  its last counts until the next run. A reaction openFDA cannot search by its exact name (FDA writes an apostrophe as
  ^, as in "WERNICKE^S ENCEPHALOPATHY") is counted by its words instead.
- **What is kept**: the reports per quarter, and the 100 most reported reactions of the whole period with their
  reports in each quarter. A reaction is kept by its name exactly as FDA publishes it (a MedDRA preferred term in
  capitals); PHAROS holds no MedDRA licence and stores no MedDRA code.
- **PRR, ROR and the flag**: each reaction's reports are compared with every drug's in a 2×2 table: PRR and ROR with
  their 95% confidence intervals and chi-squared with Yates' correction (`faers.disproportion`). *Disproportionate*
  means the reaction stands out in the ingredient's own profile: at least 3 reports, the lower end of its PRR's
  95% interval at least 2, and a PRR at least twice the median PRR of the ingredient's 100 kept reactions (a reaction
  no other drug has counts as the highest). This is PHAROS's own rule, not a published standard. Evans' criteria (3
  reports, PRR 2, chi-squared 4) were used until 6 Nov 2026 and flagged 88 of paracetamol's 100: reports of a drug
  often taken with others name more reactions than FDA's average report, so fatigue or nausea passed. On that day's
  counts the new rule flags carvedilol 13 (BRASH syndrome, hyperkalaemia, cardiac failure), levofloxacin 22 (tendon
  rupture, tendonitis), paracetamol 26 and phenylephrine 29. It is a reason to look, not a signal: stimulated
  reporting, an indication's own symptoms and duplicates all raise a PRR.
- **The label tag**: the reaction's name is matched to MeSH by its exact name (`coding_norm`), and the label tag is the
  one of section 05, except that a reaction neither label names is *Not in our label* only when our label is read;
  when only the reference label is coded it is *Not in the reference label* (migration 0080; ivabradine, 6 Nov 2026,
  had no label of ours in English). A name MeSH does not have (OFF LABEL USE, for one) has no tag.
- **The key**: `OPENFDA_API_KEY` (a repository secret, optional) allows 240 requests a minute and lists up to 1,000
  reactions per request; without it openFDA allows 40 a minute and 100 reactions, so the run takes longer and a
  quarter's rarer reactions show "–". A run starts no ingredient after 45 minutes; the rest wait for the next run.
  openFDA's 404 "No matches found" is a zero; a 429 or a server error is asked again after 5, 15 and 35 seconds.

The screen says under the table that the data are FDA's, that a report is not proof the drug caused the reaction,
that the counts are not how often it happens, and that FDA does not endorse PHAROS.

## Clinical trials (ClinicalTrials.gov)

Section *07 Clinical trials* of the Ingredients screen lists the clinical trials whose interventions name the
ingredient, from ClinicalTrials.gov, the registry of the U.S. National Library of Medicine (migration 0067). The API
(v2) needs no key; NLM asks that it is named as the source and never as endorsing PHAROS, and the section says so.

- **When.** *PHAROS clinical trials* (`trials.yml`) runs every Wednesday at 04:11 UTC and by hand. Run it by hand
  once after the first deploy of 0067, and after adding an ingredient, so the section fills at once. A run takes a
  few minutes; ClinicalTrials.gov asks for about 50 requests a minute at most, and the collector waits 1.3 seconds
  between requests.
- **What is searched.** For each active ingredient, one search of the interventions (`query.intr`) for its English
  name and its other English names on the watchlist (brands and synonyms of four letters or more, codes left out),
  each in quotes and joined by OR. ClinicalTrials.gov also matches its own synonyms of a drug name, so a search
  finds trials that name a brand. The names searched are shown under the section.
- **What is fetched.** The search lists each study's last update. Only a study that is new or was updated since the
  last run is fetched again (100 at a time): title, phase, overall status, start and completion dates (a day or a
  month, as published), lead sponsor, enrolment (actual or estimated), whether results are posted and when they
  were first posted, and the adverse-event tables of the results. A study the search no longer returns is unlinked
  from the ingredient, but only after a search that read every page; a study no ingredient links is removed.
- **What is flagged.** *New results*: results first posted in the last 90 days. *Status changed*: the overall status
  differs from the one PHAROS kept, dated the day the run saw it (the first time a study is kept is never a change,
  so this flag starts with the second run). The section counts the trials flagged.
- **Serious adverse events.** For the trials with results, each serious event term is summed over the trials: the
  number of participants affected and at risk, over **every arm of each trial, comparators and placebo included**,
  with each arm's own numbers kept in `trial_event.groups`. The 15 terms with the most participants affected are
  shown. The terms are the sponsors' words as published (usually MedDRA terms, in the version the sponsor used):
  PHAROS shows them as they are and never builds a MedDRA dictionary from them. A term that appears often is a
  reason to open the trial and read its arms, not a finding.
- **The log.** The run's log is public (the repository is public): it prints counts only ("12 ingredients
  searched, 25 studies fetched, 310 unchanged"), never an ingredient, a sponsor or a request address. A run in
  which every search failed ends red; one ingredient's failed search is counted ("1 to try again"), changes nothing
  for that ingredient, and is tried again the next week.

## Quality: deviations, audits and CAPA

The **Quality** tab (migration 0107) follows Dr Sama's SOPs: an observation that needs a CAPA comes from a
deviation (PV-SOP-021) or from an audit (PV-SOP-022), and both end in the same CAPA plan. Everyone signed in sees
the tab; a reviewer or an administrator records and takes the steps (a reader sees no buttons).

- **01 Deviations.** *Record a deviation* (form PV-FM-009): the title, what happened in full, the days it happened
  and was detected, and the potential impact (patient safety, regulatory compliance, document quality). It is
  numbered D001/2026, D002/2026 … (the numbers start again each year). Notify QA at once: QA sets the level
  (1 no impact, 2 may affect compliance, 3 impact on patient safety) with the reason. Opening a deviation shows
  the record, the six investigation questions and the root cause (*Write the investigation*), its CAPAs (*Add a
  CAPA*), the history and the next step: start the investigation; root cause found, plan the CAPA (once the level
  and the root cause are known); the QA Manager marks it satisfactory and approves it, or not satisfactory (back to
  the investigation); close it, only when every CAPA of it is effective.
- **02 Audits.** *Plan or record an audit*: internal (the PV department, last quarter of the year; the audit plan
  goes to the QPPV two weeks before) or external (another marketing authorisation holder), the auditor, the days,
  and the day the report was received. From that day each audit shows its deadlines: QPPV review by day 1, meeting
  by day 2, draft CAPA by day 10, all CAPAs approved by day 12, CAPA submitted by day 14 — "Draft CAPA by Thu 19 Nov
  · 3 days left", "late by 2 days" or "done". *Done on…* records the day each was done; *Change the days* records
  the final report, the closure confirmation and a request for information (answered within 72 hours). Opening an
  audit shows its observations (graded critical, major or minor, assigned to a stakeholder, with the root cause)
  and each observation's CAPAs. An audit closes with the lead auditor's closure confirmation and every CAPA
  effective. Audit reports are confidential: they stay within the team.
- **03 CAPA plan.** Every CAPA from both sources in one list, the late ones first, filtered by status and by
  source: its number (CAPA-001/2026), where it comes from ("from D001/2026", "from Audit …, observation 2"), the
  actions, the owner (a PHAROS person, or someone outside PHAROS by name), the due day, the status and the
  evidence. Draft → approved (an owner and a due day) → in progress → done (the evidence: what was done, a document
  reference or a link) → verified effective, or not effective (back to work).

A judgement (a level, an approval, effective or not, closing) needs a comment. If someone else changed the record a
moment before, the step is refused and the tab reloads. **Nothing is ever deleted**: every change is a new line in
the record's history (who, when, the comment, and what it was before and after), and the history itself cannot be
changed.

Deploying: apply migration 0107 before the new app (the tab calls its functions).

- **In the morning reminder.** The same daily message as the findings and the signal steps (never a second one)
  ends with two blocks, each line with the link to the Quality tab: **CAPA due** — every CAPA not done or
  effective whose due day is within two days or past, oldest first: its number, where it comes from (D001/2026, or
  the audit and its observation number), the owner, "due Thu 19 Nov" or "late by 3 days"; **Audit deadlines** —
  for each audit with a report received and not closed, its next deadline (QPPV review, meeting, draft CAPA,
  approval, submission) when it is within two days or late. When nothing at all is due, nothing is sent. If the
  quality records cannot be read (0107 not applied yet), the run logs it and the rest of the reminder goes as
  before.
- **In the inspection pack.** Section 07 *Quality: deviations, audits and CAPA* and the Excel sheets
  *Deviations*, *Audits* and *CAPA plan*, for the pack's days (read in pieces of at most 366 days): the deviations
  recorded (number, title, level, dates, root cause, the QA Manager's judgement, status, its CAPAs); the audits
  whose report was received (kind, auditor, report day, each deadline on time, late or not yet, the observations
  with their grade and CAPAs, the closure); every CAPA opened in the days or still open (number, where it comes
  from, owner, due, done, effective, evidence) with the open, late and closed counts; and the number of history
  rows per kind in the days. Lateness is as on the day the pack is made. The summary counts them too.

- **Proposed deviations (0108).** PHAROS keeps four kinds of deadline: the five-day clock to the EDA, the steps of
  a signal, the due day of a CAPA and the deadlines of an audit. Each morning from 07:00 the reminder run first
  proposes as a deviation every one of them that passed unmet, once each, worded in full ("The finding … was due to
  the Egyptian Drug Authority on Tue 3 Nov 2026 … and had not been reported by …"). They wait above the register
  on *01 Deviations*, with when each was due, when it was found and a link to the ingredient where there is one.
  A reviewer or an administrator decides: *Record as deviation* opens the usual form filled in with what PHAROS
  found (change anything), and saving gives it its D-number and history; *Dismiss* needs the reason. **PHAROS
  never records, approves or closes a deviation itself.** A dismissed or recorded missed deadline is never proposed
  again. Only deadlines due on or after the day 0108 was applied are proposed (app_setting
  `deviation_proposals_since`). The morning message ends with **Proposed deviations** (how many wait, with the link)
  and goes even when nothing else is due. The inspection pack adds *Missed deadlines reviewed, not deviations* (the
  dismissed ones of the days, who dismissed them and why) to section 07, a sheet *Deadlines reviewed* and a summary
  row. Deploying: apply migration 0108 before the new app; before it, the tab shows no proposals and the reminder
  goes as before.

- **Drafted root cause and CAPA (0109).** On a deviation and on an audit observation not closed, a reviewer or
  an administrator clicks *Draft the root cause and CAPA*. The quality-draft Edge Function records the ask and
  starts `quality-draft.yml` (the 4-hourly collection's *Quality drafts* step is the safety net). The reader (the
  same Claude model as the case reports, signed in by federation, no stored key) is given only what is recorded on
  that record — the description, dates, impact, level, the six investigation answers, the root cause so far and the
  CAPAs already there, or the observation, its grade and audit — and returns four short texts: root cause,
  corrective action, preventive action, and what must be checked first. It is told never to invent a fact or name
  a person. The draft shows under *Draft*, marked "Draft, not recorded"; *Use as the root cause* and *Use in a new
  CAPA* open the usual forms filled in with it. **Nothing is recorded until she saves the form**, and the history
  shows her as the author. A failure (reader not reachable, refused) shows on the record with *Draft again*;
  passing failures are tried up to 3 times. Deploying: apply 0109 and deploy the Edge Function before the app;
  before that the tab offers no draft.

- **Effectiveness check day (0110).** PV-SOP-022 ("Follow up") asks that every completed CAPA is checked to be
  still running as communicated. When a CAPA is marked done, PHAROS sets the day of that check itself: three months
  after the day it was done. The CAPA card shows *Effectiveness check* ("Check by Wed 10 Feb · 91 days left", "late
  by 2 days", "Checked Tue 17 Nov" once verified). A reviewer may move it under *Change the CAPA* while the CAPA is
  done: today or later, with the reason, kept in the history. Not effective sends the CAPA back to work and clears
  the day; done again sets a new one from the new done day. In the CAPA plan a done CAPA is ranked by its check day
  (a late check is listed with the late CAPAs and counted late). The morning reminder's **CAPA due** block lists
  the checks due within two days or late ("effectiveness check due Thu 19 Nov"); the inspection pack gives the day
  ("check by …", column *Effectiveness check by*) and counts a late check as late. **PHAROS never judges
  effectiveness**: *Verified effective* and *Not effective* stay the reviewer's, with her comment. CAPAs already
  done or effective when 0110 was applied got their day from their done day. Deploying: apply 0110 before the new
  app and the morning run (both read the new column).

## PRAC agendas

- **PRAC agendas.** The `ema-prac` source also reads the agendas and minutes of PRAC meetings
  (`/en/committees/prac/prac-agendas-minutes-highlights`). An agenda names each substance PRAC will discuss,
  weeks before a recommendation, so a watched ingredient on it becomes a notice (Safety update, "Agenda of the
  PRAC meeting …") with the page where it is named. If that page stops listing documents, the run warns and the
  signal recommendations are still read.
- **A revised agenda is read again.** EMA publishes an agenda as a draft and replaces it under the same address,
  marking it "Last updated". The revised agenda is a new notice ("… (updated 9 September 2026)", dated that
  day) whose PDF is screened again, so a substance added to it is not missed. An agenda never revised keeps
  its address as its identity.
