# PHAROS email inbound (Cloudflare Email Worker) — optional alternative (needs the domain on Cloudflare)

> **Not used today.** PHAROS reads the regulator newsletters by polling `pharos@satopharma.com` over IMAP
> (the collectors fill `inbound_email`; see `docs/setup.md`). This Worker is kept as an alternative for the
> day the mail domain's DNS is on Cloudflare. Its deploy workflow runs only when started by hand.

Some regulators cannot be read from a datacenter: Fimea's website has a Cloudflare check, which PHAROS never
bypasses, and TGA may block GitHub's addresses. For these, the PV mailbox subscribes to the regulator's own
newsletter, and this Worker receives those emails.

For every email sent to an alias, the Worker:

1. Stores the raw message, unchanged, in R2 at `inbound/<YYYY-MM-DD>/<uuid>.eml`. The bucket lock keeps it.
2. Reads the text and HTML parts with `postal-mime`.
3. Inserts one `inbound_email` row with the service key. `source_id` comes from the alias: `fimea@` maps to
   `fimea-email` and `tga@` maps to `tga-email`. If the source row is not there yet, the row is kept with an
   empty `source_id`.
4. Forwards a copy to `FORWARD_TO` if it is set, so people still see subscription confirmations.

The collectors' `email_inbox` parser turns each row into items and sets `processed_at`.

Mail to any other address on the domain is rejected.

## Routing setup (once, in the Cloudflare dashboard)

1. **Domain.** Email Routing needs a domain whose DNS is on Cloudflare. Use the PV mailbox domain, or a
   subdomain of it, for example `alerts.<domain>`.
2. **Email → Email Routing → Get started.** Cloudflare adds the MX and SPF records. Accept them.
3. **Destination addresses.** Add the PV mailbox and click the link in the email Cloudflare sends. This is
   only needed for `FORWARD_TO`.
4. **Deploy the Worker.** Starting `.github/workflows/deploy-worker.yml` by hand (Actions → Run workflow) runs it. It uploads the
   Worker and its secrets (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `FORWARD_TO`).
5. **Routing rules → Create address**, once for each alias:
   - Custom address `fimea`, action **Send to a Worker**, Worker `pharos-email-inbound`.
   - Custom address `tga`, action **Send to a Worker**, Worker `pharos-email-inbound`.
6. **Subscribe.** Sign `fimea@<domain>` up for Fimea's safety newsletter and `tga@<domain>` up for TGA's
   safety alerts. The confirmation emails arrive in the PV mailbox through `FORWARD_TO`. Click each one.

## Adding another alias

Add `alias=source-id` to `ALIAS_SOURCES` in `wrangler.toml`. Add a routing rule as in step 5. Add the source
to `collectors/sources.yaml` with `channel: email` and `parser: email_inbox`.

## Settings

| Name | Where it is set | What it is |
|---|---|---|
| `ARCHIVE` | `wrangler.toml` (R2 binding) | Bucket `pharos-archive`; must equal `R2_BUCKET` |
| `ALIAS_SOURCES` | `wrangler.toml` | `alias=source-id`, comma-separated |
| `SUPABASE_URL` | Worker secret (from GitHub) | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Worker secret (from GitHub) | Service key, so the Worker can insert past row-level security |
| `FORWARD_TO` | Worker secret (from GitHub `PV_MAILBOX`) | Optional copy to a verified destination |
