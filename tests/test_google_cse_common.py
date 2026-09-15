"""The Custom Search secrets are masked as *** in Actions logs, so these
helpers are the only thing standing between a bad credential and an
undiagnosable '400 Bad Request' repeated once per query."""

from src.scrapers.google_cse_common import (
    check_credential_shape,
    explain_cse_error,
    is_credential_error,
)


# 39 characters, matching a real Google API key's shape.
_VALID_SHAPED_KEY = "AIzaSy" + "B" * 33


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _google_error(reason: str, message: str, code: int = 400, metadata: dict | None = None) -> _Resp:
    body = {"error": {"code": code, "message": message, "errors": [{"reason": reason}]}}
    if metadata:
        body["error"]["details"] = [
            {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "metadata": metadata}
        ]
    return _Resp(code, body)


def test_invalid_api_key_reason_and_remedy_are_surfaced():
    resp = _google_error("keyInvalid", "API key not valid. Please pass a valid API key.")
    reason, human = explain_cse_error(resp)
    assert reason == "keyInvalid"
    assert "API key not valid" in human
    assert "AIza" in human  # the actionable discriminator


def test_bad_cx_points_at_the_search_engine_id():
    resp = _google_error("badRequest", "Request contains an invalid argument.")
    _, human = explain_cse_error(resp)
    assert "GOOGLE_CSE_ID" in human


def test_non_json_error_body_still_returns_something_useful():
    resp = _Resp(502, payload=None, text="<html>Bad Gateway</html>")
    reason, human = explain_cse_error(resp)
    assert reason == ""
    assert "502" in human


def test_forbidden_points_at_the_key_s_own_project():
    # The failure actually hit in production. The console showed Custom
    # Search API enabled, so the remedy must not just say "enable it" — the
    # useful part is that the error is about the project THIS KEY belongs to,
    # which may not be the one open in the console tab.
    resp = _google_error(
        "forbidden",
        "This project does not have the access to Custom Search JSON API.",
        code=403,
    )
    _, human = explain_cse_error(resp)
    assert "Custom Search" in human
    assert "different project" in human
    assert "API restrictions" in human


def test_credential_errors_stop_the_run_but_transient_ones_do_not():
    assert is_credential_error(_google_error("keyInvalid", "bad key"))
    assert is_credential_error(_google_error("accessNotConfigured", "API disabled", code=403))
    assert is_credential_error(_google_error("dailyLimitExceeded", "quota", code=403))
    # A 5xx is Google having a bad moment — the next query may well succeed.
    assert not is_credential_error(_Resp(503, payload=None, text="unavailable"))


def test_swapped_secrets_are_caught_before_spending_quota():
    problems = check_credential_shape(api_key="d179f055be7bc42d0", cse_id=_VALID_SHAPED_KEY)
    assert len(problems) == 2
    assert any("swapped" in p for p in problems)


def test_pasted_public_url_instead_of_cx_is_caught():
    problems = check_credential_shape(
        api_key=_VALID_SHAPED_KEY,
        cse_id="https://cse.google.com/cse?cx=d179f055be7bc42d0",
    )
    assert any("URL" in p for p in problems)


def test_correctly_shaped_credentials_raise_no_complaints():
    assert check_credential_shape(_VALID_SHAPED_KEY, "d179f055be7bc42d0") == []


def test_error_metadata_names_the_project_the_key_belongs_to():
    # The standoff this exists to break: the console shows the API enabled,
    # but calls still 403 because the key resolves to a different project.
    # `consumer` names that project, `activationUrl` enables the API on it.
    resp = _google_error(
        "forbidden",
        "This project does not have the access to Custom Search JSON API.",
        code=403,
        metadata={
            "service": "customsearch.googleapis.com",
            "consumer": "projects/987654321098",
            "activationUrl": "https://console.developers.google.com/apis/api/customsearch.googleapis.com/overview?project=987654321098",
        },
    )
    _, human = explain_cse_error(resp)
    assert "projects/987654321098" in human
    assert "customsearch.googleapis.com" in human
    assert "activationUrl=" in human


def test_truncated_api_key_is_caught_by_length():
    problems = check_credential_shape("AIzaShort", "d179f055be7bc42d0")
    assert any("39" in p for p in problems)


def test_correct_length_key_passes_the_length_check():
    assert check_credential_shape("AIza" + "x" * 35, "d179f055be7bc42d0") == []
