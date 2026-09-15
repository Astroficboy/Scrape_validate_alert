"""The Custom Search secrets are masked as *** in Actions logs, so these
helpers are the only thing standing between a bad credential and an
undiagnosable '400 Bad Request' repeated once per query."""

from src.scrapers.google_cse_common import (
    check_credential_shape,
    explain_cse_error,
    is_credential_error,
)


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _google_error(reason: str, message: str, code: int = 400) -> _Resp:
    return _Resp(code, {"error": {"code": code, "message": message, "errors": [{"reason": reason}]}})


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


def test_credential_errors_stop_the_run_but_transient_ones_do_not():
    assert is_credential_error(_google_error("keyInvalid", "bad key"))
    assert is_credential_error(_google_error("accessNotConfigured", "API disabled", code=403))
    assert is_credential_error(_google_error("dailyLimitExceeded", "quota", code=403))
    # A 5xx is Google having a bad moment — the next query may well succeed.
    assert not is_credential_error(_Resp(503, payload=None, text="unavailable"))


def test_swapped_secrets_are_caught_before_spending_quota():
    problems = check_credential_shape(api_key="d179f055be7bc42d0", cse_id="AIzaSyExampleKeyValue")
    assert len(problems) == 2
    assert any("swapped" in p for p in problems)


def test_pasted_public_url_instead_of_cx_is_caught():
    problems = check_credential_shape(
        api_key="AIzaSyExampleKeyValue",
        cse_id="https://cse.google.com/cse?cx=d179f055be7bc42d0",
    )
    assert any("URL" in p for p in problems)


def test_correctly_shaped_credentials_raise_no_complaints():
    assert check_credential_shape("AIzaSyExampleKeyValue", "d179f055be7bc42d0") == []
