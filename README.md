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
- **Years of experience:** if a posting states a required years figure, it's
  compared against `candidate.ai_years`/`total_years`/`max_years_tolerated`
  in `config.yaml` — a soft signal (never excludes), since "years required"
  is frequently unstated or negotiable.
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
src/scrapers/   -> email_alerts (IMAP — LinkedIn/Indeed/Naukrigulf/GulfTalent/
                    Bayt), Greenhouse & Lever (official public board APIs),
                    google_discovery + google_watch (Google Custom Search,
                    shared daily budget), Bayt HTML (best-effort), Adzuna
                    (wired up but disabled — see caveat below)
src/validator.py -> hard filters (seniority/domain/location/exclusions) +
                     0-100 quality score (skills + salary + location +
                     years-of-experience fit + priority_targets tier bonus +
                     thin-data cap)
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

Direct scraping of LinkedIn, Indeed, Naukrigulf, GulfTalent and Bayt gets an
IP blocked within days and risks the account — none of that is attempted
here. **Adzuna was originally the intended primary API source but is
disabled by default** — a live test run confirmed it returns 404 for
country code `ae`; the UAE simply isn't one of Adzuna's covered markets, so
no amount of correct credentials fixes it. Real coverage instead comes from
four legitimate routes:

- **Job-alert emails over IMAP** (`src/scrapers/email_alerts.py`) — the
  actual route into LinkedIn and Indeed. You create a **daily email alert**
  for each target title on each board (LinkedIn, Indeed, Naukrigulf,
  GulfTalent, Bayt), scoped to Dubai/UAE, delivered to one inbox; this reads
  that inbox over IMAP and parses the postings out of the alert HTML. Each
  board hands over exactly what its own search already filtered for — no
  scraping, no bot detection, no account risk, and it doesn't break when a
  site redesigns. One-time setup cost: creating ~30 saved searches by hand
  (see below).
- **Dubai Careers** (`src/scrapers/dubai_careers.py`) — the Government of
  Dubai's Oracle Taleo portal, covering the government entities (RTA, Dubai
  Municipality, DEWA, Dubai Police, Digital Dubai, the cultural authorities)
  that run no public ATS board. Taleo is session-driven and exposes no
  usable JSON API on this instance, but the search page embeds its full
  result set in a hidden `initialHistory` field; the scraper parses that and
  builds a real `jobdetail.ftl?job=<id>` link per posting. Roughly the 25
  most recent openings, which suits a daily run. See
  `scripts/check_boards.py`'s sibling `scripts/probe_taleo.py` if the parse
  ever breaks — it dumps the live page structure.
- **Workday** (`src/scrapers/workday.py`) — Workday's public CXS JSON
  endpoint needs no credentials and does not block datacenter traffic.
  Tenants are discovered with `scripts/probe_workday.py`, since a public
  Workday URL has three independent unknowns (tenant, `wdN` shard, site
  slug). Set expectations honestly: a 124-tenant sweep found only four with
  UAE openings, and no Gulf employer (ADNOC, Emaar, Aldar, Majid Al Futtaim,
  Emirates NBD, DP World, Etihad) runs a reachable Workday tenant. This is a
  cheap supplementary source, not a fix for AI-role coverage. Note it
  searches your *role keywords* and filters results by location, not the
  reverse — a Dubai AI role whose text never says "Dubai" is exactly the
  case that matters.
- **Greenhouse** / **Lever** — most tech companies' own ATS expose a public,
  unauthenticated JSON jobs API (`boards-api.greenhouse.io`, `api.lever.co`).
  `config.yaml`'s Greenhouse list is verified live (via `scripts/check_boards.py`,
  run through `check-boards.yml`): `datacamp` (33 jobs, 8 UAE), `careem` (20
  jobs, 12 UAE), `bybit` (152 jobs, 61 UAE) — the other guessed tokens (and
  every guessed Lever slug) 404'd and were pruned. Re-run
  `python scripts/check_boards.py` after adding new candidate companies.
- **Google Custom Search**, split into two sources sharing one daily query
  budget (`sources.google_search.max_daily_queries`, default 90 of the free
  100/day tier — discovery spends first, watch gets the remainder):
  - `src/scrapers/google_discovery.py` — broad (title × suffix) search
    across `search.queries` × `sources.google_discovery.suffixes`, catching
    roles at companies entirely outside `priority_targets` (career pages,
    Workday postings, ATS boards that never reach aggregators). Scoped to
    the curated job-board/ATS/company domain list configured on the
    Programmable Search Engine itself (see setup step 2) — Google
    deprecated "search the entire web" for new engines, so this was never
    going to be unrestricted anyway; the curated list keeps results
    job-relevant by construction rather than needing noise-filtering.
  - `src/scrapers/google_watch.py` — one targeted query per `watch: true`
    company in `priority_targets`, restricted to that company's domain.
    Currently 16 watched companies.

  Needs `GOOGLE_API_KEY` + `GOOGLE_CSE_ID`.
- **Bayt** is also included as a best-effort HTML scraper (`src/scrapers/bayt.py`),
  but cloud/datacenter IPs — including GitHub Actions runners — get 403'd by
  its anti-bot layer more often than not, on top of markup that can change
  without notice. Treat it as opportunistic, not reliable; it's isolated
  from the rest of the system and fails without affecting the other sources.

You can add more sources by writing a new class in `src/scrapers/` that
implements `BaseScraper` (see `src/scrapers/base.py`) and wiring it into
`src/main.py`.

## One-time setup

### 1. Job-alert emails (the LinkedIn/Indeed route) — ~30-40 minutes

This is the one genuinely manual step, and it's what makes LinkedIn/Indeed
coverage possible without scraping them.

1. Decide which Gmail address to use — the one already set up for
   `EMAIL_ADDRESS`/`EMAIL_APP_PASSWORD` below works fine as a single inbox
   that both receives board alerts and sends the digest. (A dedicated fresh
   Gmail keeps this out of a personal inbox if you'd rather.)
2. On each board, run the search and save it as a **daily** email alert to
   that address, for each target title in `search.queries`
   (`config.yaml`) crossed with Dubai/UAE as location:
   - **LinkedIn** — Jobs → search title + location `Dubai, UAE` → toggle
     *Job alert* on, frequency Daily. Repeat per title. Also confirm alert
     email delivery is on in Settings → Notifications.
   - **Indeed** (`ae.indeed.com`) — search, then "Get new jobs for this search".
   - **Naukrigulf** (`naukrigulf.com`) — Recommended Jobs → Create job alert.
   - **GulfTalent** — Job alerts, filter UAE + IT/Technology.
   - **Bayt** (`bayt.com`) — worth adding, one of the largest Gulf boards.
3. That's ~30 saved searches (titles × boards) — tedious once, but it's the
   backbone of real LinkedIn/Indeed coverage. `sources.email_alerts.senders`
   in `config.yaml` already maps each board's sending domain; add more there
   if you set up additional boards (Monster Gulf, Glassdoor are pre-wired).
4. `IMAP_USER`/`IMAP_PASSWORD` default to `EMAIL_ADDRESS`/`EMAIL_APP_PASSWORD`
   below — only set them separately if the alerts land in a different inbox.

### 2. Google Custom Search — CURRENTLY DISABLED (optional)

> **Status: switched off in `config.yaml`.** Every query returned HTTP 403,
> `"This project does not have the access to Custom Search JSON API"`, and
> the usual causes were each ruled out by direct testing against the
> endpoint: the API key was valid and complete (Google answered `forbidden`,
> not `invalid`), it belonged to the same Cloud project whose console showed
> Custom Search API **Enabled**, the `cx` was correct, and the failure
> persisted well past the enablement propagation window. What remains is
> project standing on Google's side — most often a Cloud free trial that
> ended without upgrading, which suspends a project's API access while the
> console still displays those APIs as enabled.
>
> The pipeline runs fine without it (see *Why these job sources*). **Skip
> this section** unless you want the extra breadth. To re-enable: fix the
> project's billing standing (or create a fresh project and redo the three
> steps below in it), confirm the key works in a browser, then set
> `sources.google_discovery.enabled` and `sources.google_watch.enabled`
> back to `true`. No code changes needed — the scrapers, the shared query
> budget, and the `watch: true` company list are all still wired up.

1. In a Google Cloud project, enable the "Custom Search API" and create an
   API key — this is `GOOGLE_API_KEY`.
2. Create a Programmable Search Engine at
   https://programmablesearchengine.google.com/. Give it any name and,
   since a "Sites to search" entry is required to create it, add any one
   placeholder domain to get past that screen (you'll replace it next).
3. **"Search the entire web" is deprecated for new engines** — Google now
   restricts it to legacy engines created before the cutoff, so there's no
   toggle for it anymore. Instead, open the created engine's control panel
   → Basics → "Sites to search", and replace the placeholder with this
   curated list of job-relevant domains (well under Google's 50-domain cap
   per engine):

   ```
   linkedin.com/jobs/*
   *.indeed.com
   bayt.com/*
   naukrigulf.com/*
   gulftalent.com/*
   monstergulf.com/*
   glassdoor.com/*
   boards.greenhouse.io/*
   jobs.lever.co/*
   *.myworkdayjobs.com
   *.workday.com
   *.smartrecruiters.com
   *.icims.com
   emiratesnbd.com/*
   bankfab.com/*
   mashreqbank.com/*
   adcb.com/*
   g42.ai/*
   core42.ai/*
   presight.ai/*
   adnoc.ae/*
   google.com/*
   microsoft.com/*
   amazon.jobs/*
   careem.com/*
   noon.com/*
   talabat.com/*
   dpworld.com/*
   emiratesgroupcareers.com/*
   ```

   This is job boards + ATS platforms (google_discovery's territory) plus
   the 16 `watch: true` companies from `priority_targets` (google_watch's
   territory) — no code needs to know about this list, since the site
   restriction is enforced by Google on the engine itself regardless of
   the query text sent to it. If you add/re-tier `watch: true` companies
   in `config.yaml` later, add their domain here too, or the watch query
   for that company will return zero results (filtered out server-side by
   the engine, not by an error).
4. Copy the **Search engine ID** from the same Basics page — this is
   `GOOGLE_CSE_ID`.
5. Free tier is 100 queries/day; `sources.google_search.max_daily_queries`
   (default 90) caps total spend across both Google sources.

**Telling the two secrets apart.** They are easy to mix up, and GitHub masks
both as `***` in Actions logs, so a wrong value shows up only as an opaque
`400 Bad Request`:

| Secret | Where it comes from | How to recognise it |
| --- | --- | --- |
| `GOOGLE_API_KEY` | Google Cloud Console -> APIs & Services -> Credentials | **always** starts with `AIza`, ~39 chars |
| `GOOGLE_CSE_ID` | Programmable Search Engine -> Basics -> *Search engine ID* | short alphanumeric string, **never** starts with `AIza` |

`GOOGLE_CSE_ID` is the bare ID only — the value after `cx=` in the Public
URL, not `https://cse.google.com/cse?cx=...` itself.

**If the Google sources fail.** The run logs Google's own error reason and a
suggested fix rather than a bare status code, and stops after the first
credential-level rejection instead of repeating the same failure once per
query. Read the `FIX:` line in the Actions log:

- `reason=keyInvalid` -> `GOOGLE_API_KEY` is wrong (check it starts with `AIza`).
- `reason=badRequest` / `invalid` -> `GOOGLE_CSE_ID` is wrong (see above).
- `reason=forbidden` / `accessNotConfigured` ("this project does not have
  access to Custom Search JSON API") -> the key is recognised, but Custom
  Search API is not enabled for **the project that key belongs to**. That is
  not necessarily the project open in your console tab. If the console shows
  the API enabled and calls still 403, then either the key was created under
  a different project, or it carries an **API restriction** (Credentials ->
  the key -> *API restrictions*) whose allowed list excludes Custom Search
  API. Fastest way out is to create a fresh key inside the project that has
  the API enabled, with Application restrictions **None** and API
  restrictions **Don't restrict key**, and verify it in a browser before
  storing it.
- `reason=ipRefererBlocked` -> the key has an Application restriction that
  blocks the Actions runner; set Application restrictions to **None**.
- `reason=dailyLimitExceeded` -> the 100/day quota is spent; lower
  `max_daily_queries`.

The pipeline also pre-checks the *shape* of both secrets before spending any
quota, so an obviously swapped or pasted-URL value is reported without
burning a query.

**Always verify a key in a browser before storing it as a secret.** Once it
is in GitHub it is masked as `***` and cannot be read back, so a wrong value
can only be diagnosed indirectly. Open this, substituting your own values:

```
https://www.googleapis.com/customsearch/v1?key=YOUR_API_KEY&cx=YOUR_CSE_ID&q=test
```

- JSON containing `"items"` -> the pair works; store exactly these values.
- A 403/400 error -> fix it here first. Storing it will only reproduce the
  same error inside the workflow, where it is much harder to see.

This also distinguishes the two failure classes cleanly: if the browser
works but the workflow does not, the problem is the stored secret (stale or
mistyped); if the browser fails too, the problem is the key or its project.

### 2b. Adzuna API (optional — currently disabled)

Adzuna doesn't cover the UAE (see above), so this isn't needed unless you
also want it for another market. Register at https://developer.adzuna.com/
for an `app_id`/`app_key` and flip `sources.adzuna.enabled` to `true` in
`config.yaml` if you ever want it back on.

### 3. Email (Gmail)

1. Enable 2-Step Verification on the Gmail account (the same one used for
   job alerts above, unless you set IMAP_USER separately).
2. Create an App Password: https://myaccount.google.com/apppasswords
3. Use that Gmail address as `EMAIL_ADDRESS` and the 16-character app
   password as `EMAIL_APP_PASSWORD`. `EMAIL_TO` is where the digest goes
   (defaults to `pranavwankhedkar@gmail.com` from `config.yaml` if unset).
   This same App Password also authenticates the IMAP read in step 1.

### 4. WhatsApp (Twilio)

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

### 5. Wire it into GitHub Actions

In the repo: **Settings → Secrets and variables → Actions → New repository
secret**, add:

```
EMAIL_ADDRESS
EMAIL_APP_PASSWORD
EMAIL_TO                 (optional — defaults to)
GOOGLE_API_KEY
GOOGLE_CSE_ID
IMAP_USER                 (optional — defaults to EMAIL_ADDRESS)
IMAP_PASSWORD              (optional — defaults to EMAIL_APP_PASSWORD)
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

### 6. Target companies

`config.yaml` ships pre-populated with two things, both fully editable:

- `sources.greenhouse.companies` / `sources.lever.companies` — Greenhouse/
  Lever board tokens, every one confirmed live by `scripts/check_boards.py`.

  The checker has two modes:

  ```bash
  # Re-verify the tokens already in config.yaml (do this every month or so —
  # companies migrate ATS and boards go quiet without warning).
  python scripts/check_boards.py

  # Probe scripts/candidate_boards.txt for boards worth adding.
  python scripts/check_boards.py --candidates scripts/candidate_boards.txt
  ```

  The candidate sweep sorts results into *has UAE postings* (add these),
  *board is live but no UAE roles today* (cheap to add — one request/day,
  and the location gate drops non-UAE rows anyway) and *no such board*.
  Dead guesses stay in `candidate_boards.txt` commented out rather than
  deleted, so a later sweep doesn't re-guess them.

  Run either mode from the Actions tab via the **Verify Greenhouse/Lever
  Board Tokens** workflow, picking `configured` or `candidates` — useful
  because these APIs block many sandbox networks but not Actions runners.

  Most UAE-headquartered firms (Talabat, noon, Tabby, Property Finder,
  Dubizzle, Kitopi, DP World, Aramex) turned out **not** to run public
  Greenhouse/Lever boards at all — they're on Workday, SuccessFactors or
  in-house portals with no open JSON API. Those are reachable only through
  the job-alert-email route (step 1) or Google Custom Search (step 2).
- `priority_targets` — tiered lists of target companies (banks, sovereign-AI,
  big tech, product/tech, crypto, deprioritised IT-services firms) with a
  per-tier score bonus and a `watch: true` flag for the ones worth spending
  a Google Custom Search query on each run (see above). Add, remove, or
  re-tier companies freely — it's just data the validator reads. Matching is
  restricted to the job's `company` field and URL host, deliberately never
  the description — AWS, Databricks, Oracle and Google Cloud show up
  constantly as *required skills* in AI postings, and matching those would
  wrongly tag half the feed as "big tech".

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
- **Clean dedup across sources:** `src/models.py`'s `canonical_url()` strips
  tracking params (`utm_*`, `trkEmail`, `refId`, etc.) before hashing, so the
  same posting reached via two different alert emails or a Google result
  still dedupes to one entry instead of alerting twice.
- **Thin-data guard:** a bare title-only hit (e.g. a sparse search snippet)
  is capped at 72/100 so it can't outrank a fully-described real match —
  lifted by the priority-employer bonus, since a named Tier-1 company is
  itself strong evidence even with little text.
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
- New Greenhouse/Lever candidates you add to `config.yaml` yourself are
  unverified until you run `python scripts/check_boards.py` — do that before
  (or right after) adding a company, and periodically since companies
  migrate ATS.
- Both Google Custom Search sources are **disabled** (see setup step 2 for
  the diagnosis). Consequence worth knowing: the UAE-headquartered employers
  in `priority_targets` that run no public ATS board — Talabat, noon, Tabby,
  Property Finder, Dubizzle, Kitopi, DP World, Aramex, Emirates Group, and
  the banks — are currently reachable **only** through the job-alert-email
  route in setup step 1. Until you create those saved alerts, the feed is
  effectively ATS boards only. Their `priority_targets` score bonuses still
  apply to any matching job arriving from any source.
- When Google is re-enabled, its results are a best-effort signal rather
  than a guarantee: `site:domain`/broad search results can include stale,
  unrelated, or non-Dubai pages — the digest flags those postings as
  "targeted search — verify on click-through" rather than asserting the
  location as fact.
- **Naukri Gulf cannot be scraped from CI** (measured 19 Sep 2026 by
  `scripts/probe_naukrigulf.py`): all 22 probe attempts — four API endpoint
  shapes x five app/system id header sets, plus the plain HTML search pages
  — read-timed-out from a GitHub runner. The connection is accepted and then
  never answered, which is silent datacenter-IP dropping rather than a
  refusal that a different request could satisfy. Bayt does the same thing
  more visibly (HTTP 403). This is precisely why the job-alert-email route
  exists, and it is the only way Naukri Gulf listings can reach this system.
- LinkedIn and Indeed are **not scraped directly** — both aggressively block
  automated/unauthenticated scraping. Instead, `src/scrapers/email_alerts.py`
  reads the board's own daily alert emails over IMAP (see setup step 1),
  which is legitimate but has its own limits: it only sees what you've
  saved a search for, the HTML parser is heuristic (company/location
  extraction can occasionally misfire on an unusual email layout), and if a
  board changes its alert email template the URL-pattern classifier in
  `email_alerts.py` may need a small update.
- Dubai Careers postings carry listing-level detail only (title, employer,
  job category, posting date) — the full description lives behind the
  posting link, which the scraper deliberately does not fetch per job. The
  validator's thin-data cap therefore applies to them, so they rank below
  equivalently-matched roles with a full description. Open the link to read
  the requirements.
- Dubai Careers postings are labelled `Dubai, UAE` by construction, since
  the portal only carries Government of Dubai roles. If Dubai Careers ever
  lists a role outside the emirate, it will still be labelled this way.
- Years-of-experience extraction (`_extract_required_years` in
  `validator.py`) is a regex heuristic over free text ("5+ years", "8-10
  yrs") — it can miss unusually phrased requirements; treated as a soft
  score signal for exactly that reason, never a hard exclusion.
- FX rates are static approximations in `config.yaml`, not live-fetched;
  update them occasionally if you rely heavily on non-AED-denominated
  listings.
