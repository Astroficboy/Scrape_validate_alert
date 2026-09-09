# Dubai AI Job Alert System

A backend-only, no-UI daily job alert pipeline for a senior AI/ML engineering
job search in Dubai/UAE. It scrapes jobs, filters and scores them against a
target candidate profile, and sends a daily digest to WhatsApp and email.
Runs on a GitHub Actions cron schedule — no server to maintain.

## What it targets

Configured in `config/config.yaml` from the candidate's CV:

- **Roles:** Lead AI Engineer, GenAI Lead, Principal AI Engineer, AI Solutions
  Architect, Applied AI Lead, Head of AI, Senior/Lead ML/MLOps Engineer, and
  other senior AI/engineering titles (Lead/Senior/Principal/Staff/Architect/
  Director/Head of/Manager).
- **Location:** Dubai primarily, UAE broadly (Abu Dhabi, Sharjah included).
- **Salary:** AED 45,000/month target. Jobs with no disclosed salary are
  **not** excluded (most Gulf listings don't disclose salary) — salary only
  excludes a job when a *disclosed* figure is clearly below target, and boosts
  ranking when it meets/exceeds target. Figures in other currencies are
  converted to AED using the static FX table in `config.yaml`.
- **Skill match:** jobs are scored against the candidate's actual skills
  (Agentic AI, GenAI, LLMs, RAG, LangChain, Python, PyTorch/TensorFlow, GCP/
  AWS, Databricks, MLOps, FastAPI, etc.) to rank the best fits first.
- **Availability:** informational note in the digest (late Oct/early Nov
  2026) — not used to filter jobs, since job postings rarely state a start
  date requirement.

Tune any of this — keywords, weights, salary threshold, locations, digest
size — by editing `config/config.yaml`. No code changes needed.

## Architecture

```
src/scrapers/   -> Adzuna (official API), Greenhouse & Lever (official public
                    board APIs), Bayt (best-effort HTML, see caveat below)
src/validator.py -> hard filters (seniority/domain/location/exclusions) +
                     0-100 quality score (skills + salary + location)
src/store.py     -> data/seen_jobs.json dedup store, so only *new* postings
                     get alerted; the workflow commits it back to the repo
                     after each run since Actions runners are ephemeral
src/notifiers/   -> email (Gmail SMTP) and WhatsApp (Twilio)
src/digest.py    -> formats the WhatsApp text + HTML email
src/main.py      -> orchestrates all of the above; every scraper and every
                     notifier fails independently and is logged, so one
                     broken source/channel never blocks the rest of the run
.github/workflows/daily-job-alert.yml -> runs it daily at 09:00 Gulf time
```

### Why these job sources

Bayt/GulfTalent/NaukriGulf/LinkedIn/Indeed HTML changes often and most are
heavily JS-rendered or anti-bot protected, so scraping them reliably from an
unattended daily cron job is fragile. Instead this defaults to **stable,
documented JSON APIs**:

- **Adzuna** — free-tier job search API with real `salary_min`/`salary_max`
  fields and UAE coverage. Primary source. Needs a free API key.
- **Greenhouse** / **Lever** — most tech companies' own ATS expose a public,
  unauthenticated JSON jobs API (`boards-api.greenhouse.io`, `api.lever.co`).
  Add specific companies you're targeting to `config.yaml` under
  `sources.greenhouse.companies` / `sources.lever.companies` (the token/slug
  is in their careers page URL, e.g. `jobs.lever.co/<slug>`). Empty by
  default — add your target companies.
- **Bayt** is included as a best-effort HTML scraper (`src/scrapers/bayt.py`)
  since it's a major UAE job board, but its markup can change without notice.
  If it starts returning 0 results, that scraper's selectors likely need
  updating — it's isolated from the rest of the system and fails without
  affecting Adzuna/Greenhouse/Lever.

You can add more sources by writing a new class in `src/scrapers/` that
implements `BaseScraper` (see `src/scrapers/base.py`) and wiring it into
`src/main.py`.

## One-time setup

### 1. Adzuna API (free)

Register at https://developer.adzuna.com/ for an `app_id` and `app_key`.

### 2. Email (Gmail)

1. Enable 2-Step Verification on the sending Gmail account.
2. Create an App Password: https://myaccount.google.com/apppasswords
3. Use that Gmail address as `EMAIL_ADDRESS` and the 16-character app
   password as `EMAIL_APP_PASSWORD`. `EMAIL_TO` is where the digest goes
   (defaults to `pranavwankhedkar@gmail.com` from `config.yaml` if unset).

### 3. WhatsApp (Twilio)

1. Create a Twilio account: https://www.twilio.com/try-twilio
2. Get `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` from the console.
3. **Testing (fastest):** use the Twilio Sandbox for WhatsApp
   (`TWILIO_WHATSAPP_FROM=whatsapp:+14155238886`) and have the receiving
   number (``) send the sandbox's join code once via WhatsApp.
   Freeform messages then work for 24h sessions/testing.
4. **Production (required for unattended daily sends):** WhatsApp requires a
   pre-approved message template for business-initiated messages outside a
   24h customer-service window — which a daily automated alert always is.
   In the Twilio Console, go to Messaging → Content Template Builder, create
   a template with one `{{1}}` variable (the digest text), get it WhatsApp-
   approved, and set `TWILIO_CONTENT_SID` to its SID plus a real
   `TWILIO_WHATSAPP_FROM` sender number. Without this, WhatsApp sends will
   silently stop working once the sandbox/session window lapses — email
   still works regardless.

### 4. Wire it into GitHub Actions

In the repo: **Settings → Secrets and variables → Actions → New repository
secret**, add:

```
ADZUNA_APP_ID
ADZUNA_APP_KEY
EMAIL_ADDRESS
EMAIL_APP_PASSWORD
EMAIL_TO                 (optional — defaults to)
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_WHATSAPP_FROM
TWILIO_WHATSAPP_TO        (optional — defaults to +)
TWILIO_CONTENT_SID        (optional — required only for production WhatsApp sends)
```

That's it — `.github/workflows/daily-job-alert.yml` runs automatically every
day at 09:00 Gulf Standard Time (05:00 UTC), and can also be triggered
manually from the Actions tab (`workflow_dispatch`). No server, no UI, no
manual step after this.

### 5. Target companies (optional but recommended)

`sources.greenhouse.companies` and `sources.lever.companies` in
`config.yaml` are empty by default — add the Greenhouse/Lever tokens of
specific companies you want covered (find them from their careers page URL).
This is the most reliable way to track specific high-paying employers, since
job-board salary data is rarely disclosed for senior roles.

## Local usage

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in credentials for a local test run
python -m src.main
```

Run the tests (no network/credentials required — everything is mocked):

```bash
pip install pytest
pytest -v
```

## How deduplication works

`data/seen_jobs.json` stores a hash of every job already alerted on (by URL).
Each run only notifies about postings not already in that file, then the
GitHub Actions workflow commits the updated file back to the repo — since
Actions runners are thrown away after each run, this file *is* the
database. Entries older than 60 days are pruned automatically so the file
doesn't grow forever.

## Notable design decisions / features beyond the base ask

- **Fail-soft everywhere:** each scraper and each notifier is isolated — a
  broken source or a down email/WhatsApp channel is logged, not fatal, so
  the rest of the pipeline still runs and you still get alerts.
- **Self-alerting on failure:** if every query against a source fails (e.g.
  bad API key, site blocking requests), the system emails you a warning
  instead of silently going quiet — see `notify_on_source_failure` in
  `config.yaml`.
- **Salary normalization:** disclosed salaries in USD/SAR/EUR/GBP/INR/etc.
  are converted to AED using the FX table in `config.yaml` (approximate,
  update periodically) so a good match isn't missed just because a listing
  posted salary in a different currency; annual figures are auto-detected
  and converted to monthly.
- **No hard salary requirement:** most senior Gulf job listings don't
  disclose salary at all — the system doesn't discard those, only ones that
  explicitly disclose a below-target figure.
- **Ranked by resume fit:** every alerted job carries a 0-100 score and the
  specific matched skills/reasons, so the highest-fit roles are listed first
  and it's clear *why* each one matched.
- **Two-tier digest:** WhatsApp gets a short top-10 list (WhatsApp message
  length is constrained); the full-length digest (up to 30) goes to email.
- **Quiet on empty by default for WhatsApp:** an empty day sends a lightweight
  email note but skips WhatsApp, so daily "no results" pings don't spam your
  phone. Configurable via `digest.notify_whatsapp_on_empty`.

## Known limitations

- Bayt scraping is best-effort HTML parsing and may need selector updates if
  Bayt changes its page structure (isolated failure, doesn't affect other
  sources).
- LinkedIn and Indeed are intentionally not scraped — both aggressively
  block automated/unauthenticated scraping and doing so against their terms
  isn't something this system attempts. Use Adzuna (which aggregates many
  boards) and the Greenhouse/Lever company sources instead, or add LinkedIn
  jobs manually by watching your saved searches.
- FX rates are static approximations in `config.yaml`, not live-fetched;
  update them occasionally if you rely heavily on non-AED-denominated
  listings.
