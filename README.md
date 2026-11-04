<p align="center"><img src="web/public/brand/pharos-logo-stacked.png" alt="PHAROS, Pharmaceutical Alerts &amp; Regulatory Observation System" width="420"></p>

# PHAROS

**Pharmaceutical Alerts & Regulatory Observation System**: the regulatory safety-notification monitor for
the pharmacovigilance team, by Sato Pharma.

It watches the active ingredients the team adds (starting with lornoxicam). On a schedule it reads the safety
channels and drug databases of 25 reference regulators, from both web pages and PDFs. Every regulator is
screened **in its own language**, and nothing is translated. Everything it reads is kept in one database and an
untouchable archive. The team sees one simple table of the notices found, opens any row for the full detail and
review, and linked people get a Telegram message.

This is a standalone project. It shares nothing with Phoenix Workforce.

## Layout

| Path | What lives there |
|---|---|
| `collectors/` | Python 3.12: source catalogue (`sources.yaml`), fetch and archive, one parser per source, PDF text, matching, issue merging, SPC watch, alerts, monthly report, backfill |
| `supabase/migrations/` | Postgres schema, row-level security, scheduled watchdog |
| `supabase/functions/` | Edge Functions: Telegram webhook, ingredient lookup, source probe, invite |
| `web/` | Vite + React + TypeScript app (Cloudflare Pages), PHAROS identity |
| `.github/workflows/` | Collect, probe, backfill, monthly report, CI, web deploy, nightly database backup |
| `tests/` | Fixtures (real saved HTML, PDF and JSON from every source) and tests |
| `docs/` | Setup (accounts and secrets), operations, validation notes |

## Contracts shared by every part

- **Database:** `supabase/migrations/0001_core.sql` is the single source of truth. The collectors connect
  with `SUPABASE_DB_URL` (service role, direct Postgres). The web app uses the anon key plus the signed-in
  person's session, and row-level security decides what that person can do.
- **Source ids:** `collectors/sources.yaml` is the catalogue. The collectors sync it into the `source` table on
  every run (`origin = catalogue`). They never touch sources a person added in the app (`origin = user`).
- **Archive:** Cloudflare R2. The object key is `sha256/<first 2 hex>/<sha256>`, and the bucket lock forbids
  overwrite and delete.
- **Telegram:** `app_setting.telegram_dry_run` starts at `true`. No real message is sent until the owner
  approves the first one.
- **Times:** stored in UTC and shown in Cairo local time.
