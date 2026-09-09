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
- **Priority employers:** `config.yaml`'s `priority_targets` ranks known
  high-paying/target companies (banks, the G42/sovereign-AI cluster, big
  tech regional offices, well-funded product companies) above unknown ones
  via a per-tier score bonus, and pushes down companies that typically
  undershoot the salary target (India-benchmarked IT services firms) via a
  negative bonus. Matched by company name in the posting or domain in the
  URL — fully editable, tiers and bonuses are just data in `config.yaml`.
- **Availability:** informational note in the digest (late Oct/early Nov
  2026) — not used to filter jobs, since job postings rarely state a start
  date requirement.

Tune any of this — keywords, weights, salary threshold, locations, digest
size — by editing `config/config.yaml`. No code changes needed.

## Architecture

```
src/scrapers/   -> Greenhouse & Lever (official public board APIs), Bayt
                    (best-effort HTML), Google Custom Search (company watch),
                    Adzuna (wired up but disabled — see caveat below)
src/validator.py -> hard filters (seniority/domain/location/exclusions) +
                     0-100 quality score (skills + salary + location +
                     priority_targets tier bonus)
src/store.py     -> data/seen_jobs.json dedup store, so only *new* postings
                     get alerted; the workflow commits it back to the repo
                     after each run since Actions runners are ephemeral
src/notifiers/   -> email (Gmail SMTP) and WhatsApp (Twilio)
src/digest.py    -> formats the WhatsApp text + HTML email
src/main.py      -> orchestrates all of the above; every scraper and every
                     notifier fails independently and is logged, so one
                     broken source/channel never blocks the rest of the run
.github/workflows/daily-job-alert.yml -> runs it daily at 09:00 Gulf time
.github/workflows/check-boards.yml    -> manual: verifies Greenhouse/Lever
                     tokens in config.yaml actually resolve (see below)
```

### Why these job sources

Bayt/GulfTalent/NaukriGulf/LinkedIn/Indeed HTML changes often and most are
heavily JS-rendered or anti-bot protected, so scraping them reliably from an
unattended daily cron job is fragile. **Adzuna was originally the primary
source but is disabled by default** — a live test run confirmed it returns
404 for country code `ae`; the UAE simply isn't one of Adzuna's covered
markets, so no amount of correct credentials fixes it. Real coverage instead
comes from:

- **Greenhouse** / **Lever** — most tech companies' own ATS expose a public,
  unauthenticated JSON jobs API (`boards-api.greenhouse.io`, `api.lever.co`).
  `config.yaml` ships with a starter list of guessed tokens for UAE-relevant
  companies (`datacamp` confirmed live) — run `python scripts/check_boards.py`
  (or the `check-boards.yml` workflow, `workflow_dispatch`) to see which
  actually resolve and prune the rest.
- **Google Custom Search** (`src/scrapers/google_watch.py`) — most Tier-1
  targets (banks, the G42/sovereign-AI cluster, big tech regional offices)
  run their own careers portal (Workday, in-house), not a scrapable public
  ATS. Instead of scraping each directly, this runs one targeted Google
  search per `watch: true` company in `config.yaml`'s `priority_targets`,
  restricted to that company's domain and biased toward senior AI roles in
  Dubai/UAE. Free tier: 100 queries/day; budget-capped via
  `sources.google_watch.daily_query_budget` (currently 16 watched companies,
  well under the default 35 cap). Needs `GOOGLE_API_KEY` + `GOOGLE_CSE_ID`.
- **Bayt** is included as a best-effort HTML scraper (`src/scrapers/bayt.py`)
  since it's a major UAE job board, but cloud/datacenter IPs — including
  GitHub Actions runners — get 403'd by its anti-bot layer more often than
  not, on top of markup that can change without notice. Treat it as
  opportunistic, not reliable; it's isolated from the rest of the system and
  fails without affecting the other sources.

You can add more sources by writing a new class in `src/scrapers/` that
implements `BaseScraper` (see `src/scrapers/base.py`) and wiring it into
`src/main.py`.

## One-time setup

### 1. Google Custom Search (free, powers the priority-company watch)

1. In a Google Cloud project, enable the "Custom Search API" and create an
   API key — this is `GOOGLE_API_KEY`.
2. Create a Programmable Search Engine at
   https://programmablesearchengine.google.com/, set it to "Search the
   entire web", and copy its Search engine ID — this is `GOOGLE_CSE_ID`.
3. Free tier is 100 queries/day; this system uses at most
   `sources.google_watch.daily_query_budget` (default 35) per run.

### 1b. Adzuna API (optional — currently disabled)

Adzuna doesn't cover the UAE (see above), so this isn't needed unless you
also want it for another market. Register at https://developer.adzuna.com/
for an `app_id`/`app_key` and flip `sources.adzuna.enabled` to `true` in
`config.yaml` if you ever want it back on.

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
GOOGLE_API_KEY
GOOGLE_CSE_ID
EMAIL_ADDRESS
EMAIL_APP_PASSWORD
EMAIL_TO                 (optional — defaults to)
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_WHATSAPP_FROM
TWILIO_WHATSAPP_TO        (optional — defaults to +)
TWILIO_CONTENT_SID        (optional — required only for production WhatsApp sends)
ADZUNA_APP_ID              (optional — Adzuna is disabled by default, see above)
ADZUNA_APP_KEY              (optional)
```

That's it — `.github/workflows/daily-job-alert.yml` runs automatically every
day at 09:00 Gulf Standard Time (05:00 UTC), and can also be triggered
manually from the Actions tab (`workflow_dispatch`). No server, no UI, no
manual step after this.

### 5. Target companies

`config.yaml` ships pre-populated with two things, both fully editable:

- `sources.greenhouse.companies` / `sources.lever.companies` — Greenhouse/
  Lever board tokens. Most are unverified guesses; run
  `python scripts/check_boards.py` (needs `requests`/`PyYAML`, or just run
  the `check-boards.yml` workflow from the Actions tab) to see which
  actually resolve, and delete the ones that don't from `config.yaml`.
- `priority_targets` — tiered lists of target companies (banks, sovereign-AI,
  big tech, product/tech, crypto, deprioritised IT-services firms) with a
  per-tier score bonus and a `watch: true` flag for the ones worth spending
  a Google Custom Search query on each run (see above). Add, remove, or
  re-tier companies freely — it's just data the validator reads.

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

- Adzuna is disabled — confirmed (live 404s) that it doesn't cover the UAE.
  Wired up in code in case that changes; flip `sources.adzuna.enabled` back
  on if so.
- Bayt scraping is best-effort HTML parsing and frequently gets 403'd from
  cloud/datacenter IPs (including GitHub Actions runners) regardless of
  markup changes — isolated failure, doesn't affect other sources.
- The Greenhouse/Lever token lists in `config.yaml` include unverified
  guesses — run `python scripts/check_boards.py` periodically and prune
  ones that 404.
- Google Custom Search results for a `watch: true` company are a best-effort
  signal, not a guarantee: `site:domain` search results can include stale,
  unrelated, or non-Dubai pages on that domain — the digest flags these
  postings as "targeted search — verify on click-through" rather than
  asserting the location as fact.
- LinkedIn and Indeed are intentionally not scraped — both aggressively
  block automated/unauthenticated scraping and doing so against their terms
  isn't something this system attempts. Add LinkedIn jobs manually by
  watching your saved searches.
- FX rates are static approximations in `config.yaml`, not live-fetched;
  update them occasionally if you rely heavily on non-AED-denominated
  listings.
