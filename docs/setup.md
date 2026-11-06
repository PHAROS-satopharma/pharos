# PHAROS setup: the owner's checklist (milestone M0)

PHAROS (Pharmaceutical Alerts & Regulatory Observation System), by Sato Pharma.

Every account belongs to the company mailbox **pharos@satopharma.com**. Turn on 2-step login on every
account as soon as you create it. You paste every secret yourself; nobody else types a password or a token.
Work through the steps in this order.

## 0. The mailbox

1. Check that you can sign in to **pharos@satopharma.com** and that 2-step login is on.
2. Turn on IMAP for the mailbox, then create an **app password** for it named "PHAROS". Keep it for step 6.
   - satopharma.com mail runs on **Turbify** (Yahoo business mail), and app passwords are made per
     mailbox. Sign in to pharos@satopharma.com, open *Account info → Account security → Generate app
     password*, and name it "PHAROS".
   - The IMAP server is the one Turbify shows in its mail settings, usually `imap.mail.yahoo.com`, port
     `993` (SSL).
3. Subscribe **pharos@satopharma.com** to:
   - the **Fimea** safety newsletter (fimea.fi, newsletter or "tilaa uutiskirje" page);
   - the **TGA** safety alerts email (tga.gov.au, "Subscribe to TGA email updates": safety alerts and
     medicines safety updates).

   Click the confirmation link in each welcome email. PHAROS reads these emails every 4 hours.

## 1. GitHub

1. On github.com, create a new account with **pharos@satopharma.com**. Turn on 2-step login.
2. Create an **organisation** (*Your organisations → New organisation → Free*). Name it after PHAROS or Sato
   Pharma, for example `sato-pharos`.
3. *Organisation → People → Invite member*: invite your personal account **Omar-3-xx** with the role
   **Owner**. Accept the invitation from your personal account.
4. *Organisation → Settings → Authentication security*: tick **Require two-factor authentication**.
5. *Organisation → Settings → Profile*: upload `web/public/brand/pharos-profile-640-white.png` as the picture.
6. Tell the lead the organisation name. The lead creates the private repository **`pharos`** and pushes the code.

## 2. Supabase (database and sign-in)

1. On supabase.com, sign up with **pharos@satopharma.com**. Turn on 2-step login (*Account → Security*).
2. Create an organisation (Free plan), then a project:
   - name **`pharos`**;
   - region **Central EU (Frankfurt)**, the closest to Cairo;
   - a long database password from your password manager (this is `SUPABASE_DB_PASSWORD` in step 6).
3. *Organisation → Team → Invite*: add **Omar-3-xx's** email as **Owner**.
4. *Authentication → Sign In / Providers*: turn **off** "Allow new users to sign up". Keep Email on.
5. *Authentication → URL Configuration*: set **Site URL** to `https://pharos-satopharma.pages.dev`.
6. *Authentication → Emails → SMTP Settings*: turn on custom SMTP with the pharos@satopharma.com mail
   server. Use the app password from step 0, or a second app password. Supabase's own mail only reaches
   team members, so invitations need this.

## 3. Cloudflare (archive and website)

1. On cloudflare.com, sign up with **pharos@satopharma.com**. Turn on 2-step login. *Manage account →
   Members*: add your personal email as **Super Administrator**.
2. **R2 → Create bucket** named **`pharos-archive`**, location Automatic (Europe).
3. In the bucket, open *Settings → Bucket lock rules → Add rule*:
   - prefix `sha256/`, retention **Indefinite** (originals can never be changed or deleted);
   - prefix `inbound/`, retention **Indefinite**;
   - prefix `reports/`, retention **Indefinite**;
   - prefix `backups/`, retention **90 days**.
4. In the bucket, open *Settings → Object lifecycle rules → Add rule*: prefix `backups/`, delete objects
   **91 days** after upload.
5. In the bucket, open *Settings → CORS policy → Add*. Allow origin `https://pharos-satopharma.pages.dev`, method
   `GET`, header `Range`. This lets the app show PDFs inline.
6. *R2 → Manage R2 API tokens → Create API token*: permission **Object Read & Write**, only bucket
   `pharos-archive`. Keep the **Access Key ID** and **Secret Access Key**. Also copy the **Account ID**,
   which is shown on the R2 overview page.
7. *My Profile → API Tokens → Create Token*: use the template **Edit Cloudflare Workers**, and also add
   **Account → Cloudflare Pages → Edit**. This is `CLOUDFLARE_API_TOKEN`.
8. You do not need to create the Pages project. The first website deploy creates **`pharos-satopharma`** at
   `https://pharos-satopharma.pages.dev`. Nothing goes into the Cloudflare Pages settings, because the site is built
   in GitHub.

## 4. Telegram bot

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Name: **PHAROS**. Username: for example **`PHAROS_SatoPV_bot`** (it must end in `bot`; choose another if
   it is taken).
3. BotFather replies with the **bot token**. Keep it.
4. Send BotFather `/setprivacy` and choose **Enable**, then `/setjoingroups` and choose **Disable**.
   Then send `/setuserpic`, choose the bot, and send the picture `web/public/brand/pharos-profile-640-white.png`
   (the stacked PHAROS logo on white).
5. Make up a **webhook secret**: 40 or more letters and digits from your password manager.

## 5. NCBI (PubMed, phase 2)

1. Sign in at **ncbi.nlm.nih.gov** with pharos@satopharma.com. Open *Account settings → API Key Management →
   Create an API Key*.

## 5b. The case reader (Cases)

1. Sign in at **console.anthropic.com** with the company's account (pharos@satopharma.com). Under *Settings →
   Billing*, add the company's payment method and a monthly spend limit.
2. Open *API Keys → Create Key*, name it `pharos-cases`, and copy it once into the GitHub secret
   `ANTHROPIC_API_KEY` (step 6). Without it the Cases screen still opens cases; they wait unread until it is set.

## 6. Paste the secrets (once, all in GitHub)

Open GitHub, then *`pharos` repository → Settings → Secrets and variables → Actions → New repository
secret*. Paste each value below. The deploy copies them to Supabase (function secrets and Vault) and sets the
Telegram webhook, so you never paste a secret anywhere else.

| GitHub secret | Where you find it | Copied automatically to |
|---|---|---|
| `SUPABASE_URL` | Supabase *Project Settings → Data API*: Project URL, only `https://<ref>.supabase.co` (no `/rest/v1/`) | website build |
| `SUPABASE_ANON_KEY` | Supabase *Project Settings → API Keys*: `anon` public key | website build |
| `SUPABASE_SERVICE_ROLE_KEY` | Same page: `service_role` key (secret) | (optional email Worker only) |
| `SUPABASE_DB_URL` | Supabase *Connect → Session pooler* URI, with your database password filled in | collectors, backups |
| `SUPABASE_PROJECT_REF` | The 20 letters in the project URL `https://<ref>.supabase.co` | deploy |
| `SUPABASE_ACCESS_TOKEN` | Supabase *Account → Access Tokens → Generate* | deploy |
| `SUPABASE_DB_PASSWORD` | The password you chose in step 2 | deploy |
| `R2_ACCOUNT_ID` | Cloudflare R2 overview: Account ID | Supabase function secrets |
| `R2_ACCESS_KEY_ID` | Step 3.6 | Supabase function secrets |
| `R2_SECRET_ACCESS_KEY` | Step 3.6 | Supabase function secrets |
| `R2_BUCKET` | `pharos-archive` | Supabase function secrets |
| `CLOUDFLARE_API_TOKEN` | Step 3.7 | deploy |
| `TELEGRAM_BOT_TOKEN` | Step 4.3 | Supabase Vault (watchdog) |
| `TELEGRAM_BOT_USERNAME` | The bot's username without `@` | website build |
| `TELEGRAM_WEBHOOK_SECRET` | Step 4.5 | Supabase function secrets, Telegram webhook |
| `DISPATCH_TOKEN` | GitHub (pharos@ account) *Settings → Developer settings → Fine-grained tokens*: resource owner the organisation, repository `pharos` only, permission **Contents: Read and write** | Supabase function secret `GITHUB_DISPATCH_TOKEN` |
| `NCBI_API_KEY` | Step 5 | collectors |
| `ANTHROPIC_API_KEY` | Step 5b | collectors (the case reader) |
| `PHAROS_IMAP_HOST` | the Turbify IMAP server from step 0 (usually `imap.mail.yahoo.com`) | collectors |
| `PHAROS_IMAP_PORT` | `993` | collectors |
| `PHAROS_IMAP_USER` | `pharos@satopharma.com` | collectors |
| `PHAROS_IMAP_PASSWORD` | The app password from step 0 | collectors |
| `ADMIN_TELEGRAM_CHAT_ID` | Optional. Without it, admin alerts go to the first admin who has linked Telegram | Supabase Vault |
| `BACKUP_AGE_RECIPIENT` | Optional but strongly advised. The **public** key (`age1…`) from "Backup encryption" below. Without it the nightly backup is stored unencrypted and each run shows a warning | nightly backup |

### Backup encryption

The nightly backup contains the sign-in accounts' password hashes, so it is encrypted with
[age](https://age-encryption.org) before it is stored. Make the key pair once, on a trusted computer:

1. Install age (`winget install FiloSottile.age`, `brew install age` or `apt install age`).
2. Run `age-keygen -o key.txt`. It prints `Public key: age1…`.
3. Paste that `age1…` line as the GitHub secret `BACKUP_AGE_RECIPIENT`. To let two people restore, paste
   two public keys, one per line.
4. Keep `key.txt` (the private key, the line starting `AGE-SECRET-KEY-1`) **offline**: a password manager
   entry or an encrypted USB stick, with a second copy in a separate place. Never put it in GitHub, R2,
   Supabase, email or chat. Without it no encrypted backup can be restored, and nobody can recover it.

Backups made before the secret was set stay as plain `.sql.gz` until the 90-day rule deletes them.

GitHub does not allow secret names that start with `GITHUB_`, which is why the dispatch token is called
`DISPATCH_TOKEN` there.

## 7. First deploy, in this order

1. The lead merges the first pull request to `main`. Once **PHAROS CI** has passed on `main`, **PHAROS
   deploy Supabase** runs: it creates the tables, deploys the functions, copies the secrets and sets the
   Telegram webhook. **PHAROS deploy web** then publishes `https://pharos-satopharma.pages.dev`. Deploys
   only ever run from `main` after CI passes. If CI fails on `main`, that push is not deployed: fix it, or
   run the deploy by hand from `main`. The database deploy runs on every tested push to `main` (each step is
   safe to repeat), and the web deploy publishes everything changed since the live commit, so a later
   successful push also catches up anything an earlier one missed.
2. Supabase *Authentication → Users → Invite user*: invite your own work email. The lead then makes that
   account the first administrator (one line, in docs/operations.md under "First administrator").
3. Open the website from the invitation email, set your password, and link Telegram from your profile.
4. Collection starts on its own schedule. Telegram stays in **dry run**: no message goes to anyone until you
   approve the first one.
