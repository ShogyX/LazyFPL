import logging

from fpl_engine.config import Settings
from fpl_engine.logging_setup import RedactionFilter


def test_secrets_are_redacted_in_repr_and_str():
    s = Settings(fpl_session_cookie="supersecretcookie", sharpapi_key="abc123")
    text = repr(s) + str(s.fpl_session_cookie)
    assert "supersecretcookie" not in text
    assert "abc123" not in text
    # but the real value is retrievable explicitly
    assert s.fpl_session_cookie.get_secret_value() == "supersecretcookie"


def test_secret_values_collects_populated_secrets():
    s = Settings(fpl_session_cookie="cookieval", pushover_token="tok")
    vals = s.secret_values()
    assert "cookieval" in vals
    assert "tok" in vals


def test_redaction_filter_scrubs_log_message():
    flt = RedactionFilter(["supersecret"])
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "leaking supersecret here", None, None
    )
    assert flt.filter(record) is True
    assert "supersecret" not in record.getMessage()
    assert "REDACTED" in record.getMessage()
