"""Shared helpers for Google Custom Search JSON API scrapers
(google_watch.py, google_discovery.py)."""

from __future__ import annotations

ENDPOINT = "https://www.googleapis.com/customsearch/v1"

# Domains that are never an actual job posting — filters CSE noise.
SKIP_DOMAINS = (
    "wikipedia.org", "youtube.com", "reddit.com", "quora.com",
    "coursera.org", "udemy.com", "medium.com", "facebook.com",
    "twitter.com", "x.com", "pinterest.com", "slideshare.net",
)


def is_noise_link(url: str) -> bool:
    return any(domain in url for domain in SKIP_DOMAINS)


def company_from(result: dict) -> str:
    meta = result.get("pagemap", {}) or {}
    for posting in meta.get("jobposting", []) or []:
        name = posting.get("hiringorganization") or posting.get("name")
        if name:
            return str(name)[:80]
    for org in meta.get("organization", []) or []:
        if org.get("name"):
            return str(org["name"])[:80]
    display = result.get("displayLink", "")
    host = display.replace("www.", "").split(".")[0]
    return host.title() if host else ""


def location_from(result: dict) -> str:
    for posting in (result.get("pagemap", {}) or {}).get("jobposting", []) or []:
        loc = posting.get("joblocation") or posting.get("addresslocality")
        if loc:
            return str(loc)[:80]
    return ""


# --- Credential diagnostics -------------------------------------------------
#
# GitHub masks secret values as *** in Actions logs, so a bare
# "400 Bad Request" from the Custom Search API is undiagnosable from the
# outside: a wrong API key, a wrong cx, and a disabled API all look
# identical. Google's own error body names the cause and contains no secret
# material, so surfacing it turns a guessing game into a one-line fix.

_CREDENTIAL_REASONS = {
    "keyinvalid",            # GOOGLE_API_KEY is not a valid API key
    "badrequest",            # usually a malformed/wrong cx
    "invalid",               # "Request contains an invalid argument"
    "accessnotconfigured",   # Custom Search API not enabled on the project
    "forbidden",
    "iprefererblocked",      # key restricted to referrers/IPs the runner isn't
    "dailylimitexceeded",
    "ratelimitexceeded",
}

_REMEDIES = {
    "keyinvalid": (
        "GOOGLE_API_KEY is not a valid key. It must be the Cloud Console API "
        "key, which always starts with 'AIza'."
    ),
    "accessnotconfigured": (
        "The Custom Search API is not enabled for the project that owns this "
        "key. Enable 'Custom Search API' in Google Cloud Console -> APIs & Services."
    ),
    "forbidden": (
        "Almost always 'this project does not have access to Custom Search "
        "JSON API' — creating an API key does not enable any API. Go to Google "
        "Cloud Console -> APIs & Services -> Library, search 'Custom Search "
        "API', and press Enable on the SAME project the key belongs to."
    ),
    "ipreferrerblocked": (
        "The API key has an Application restriction (HTTP referrer / IP) that "
        "blocks the GitHub Actions runner. Set Application restrictions to "
        "'None' for this key."
    ),
    "badrequest": (
        "Usually a wrong GOOGLE_CSE_ID. It must be the Programmable Search "
        "Engine's 'Search engine ID' (the cx= value), not the full "
        "https://cse.google.com/... URL, and not the API key."
    ),
    "invalid": (
        "Usually a wrong GOOGLE_CSE_ID. It must be the Programmable Search "
        "Engine's 'Search engine ID' (the cx= value), not the full "
        "https://cse.google.com/... URL, and not the API key."
    ),
    "dailylimitexceeded": (
        "The 100 free queries/day quota is spent. Lower "
        "sources.google_search.max_daily_queries or enable billing."
    ),
    "ratelimitexceeded": (
        "The 100 free queries/day quota is spent. Lower "
        "sources.google_search.max_daily_queries or enable billing."
    ),
}


def _error_metadata(err: dict) -> dict:
    """Pulls Google's google.rpc.ErrorInfo metadata out of an error body.

    This is the part that actually resolves a "but I DID enable it" standoff:
    `consumer` names the project the API key resolves to (as a project
    number), and `activationUrl` is a link that enables the API on *that*
    project. When the console shows the API enabled but calls still 403, the
    key belongs to a different project than the one being looked at, and this
    is what proves it. Project numbers are identifiers, not credentials — the
    key and cx are still never logged.
    """
    for detail in err.get("details") or []:
        if not isinstance(detail, dict):
            continue
        meta = detail.get("metadata")
        if isinstance(meta, dict) and meta:
            return {k: str(v) for k, v in meta.items()}
    return {}


def explain_cse_error(resp) -> tuple[str, str]:
    """Turns a failed Custom Search response into (reason, human_message).

    Reads only Google's structured error fields — never echoes `key` or `cx`,
    so this is safe to log in a public Actions run.
    """
    reason, message, meta = "", "", {}
    try:
        err = (resp.json() or {}).get("error", {}) or {}
        message = str(err.get("message", "") or "")
        details = err.get("errors") or []
        if details:
            reason = str(details[0].get("reason", "") or "")
        if not reason:
            reason = str(err.get("status", "") or "")
        meta = _error_metadata(err)
    except Exception:
        # Non-JSON error page (proxy, HTML 5xx); status code alone is the signal.
        message = (getattr(resp, "text", "") or "")[:200]

    remedy = _REMEDIES.get(reason.lower(), "")
    human = f"HTTP {getattr(resp, 'status_code', '?')} reason={reason or 'unknown'}: {message}"
    if meta:
        interesting = {k: meta[k] for k in ("service", "consumer", "activationUrl") if k in meta}
        if interesting:
            human += " | " + ", ".join(f"{k}={v}" for k, v in interesting.items())
    if remedy:
        human += f" | FIX: {remedy}"
    return reason, human


def is_credential_error(resp) -> bool:
    """True when retrying further queries is pointless — the key, the cx, or
    the project setup is wrong, so every remaining query will fail the same
    way (and, on a quota error, burn nothing but log noise)."""
    status = getattr(resp, "status_code", 0)
    if status in (401, 403):
        return True
    reason, _ = explain_cse_error(resp)
    return reason.lower() in _CREDENTIAL_REASONS


def check_credential_shape(api_key: str, cse_id: str) -> list[str]:
    """Cheap pre-flight on the *shape* of the two secrets, so an obviously
    swapped or pasted-URL value is caught before spending any quota.
    Returns a list of human-readable problems (empty when both look sane)."""
    problems: list[str] = []
    key = (api_key or "").strip()
    cx = (cse_id or "").strip()

    # Google API keys are 39 chars. A short one is a truncated paste, which
    # is invisible through GitHub's *** masking but breaks every call.
    if key and key.startswith("AIza") and len(key) != 39:
        problems.append(
            f"GOOGLE_API_KEY is {len(key)} characters; a Google API key is 39. "
            "The value looks truncated or has extra characters."
        )

    if key and not key.startswith("AIza"):
        problems.append(
            "GOOGLE_API_KEY does not start with 'AIza' — that is not a Google "
            "Cloud API key. Check the two secrets are not swapped."
        )
    if cx.startswith("AIza"):
        problems.append(
            "GOOGLE_CSE_ID starts with 'AIza' — that is an API key, not a "
            "Search engine ID. The two secrets are swapped."
        )
    if cx.startswith("http") or "cse.google.com" in cx or "cx=" in cx:
        problems.append(
            "GOOGLE_CSE_ID looks like a URL. Store only the 'Search engine ID' "
            "itself (the value after cx=), not the whole Public URL."
        )
    return problems
