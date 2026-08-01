"""Key-based redaction for structlog. Values never reach storage unredacted."""

import re

REDACTED = "[Redacted]"

# OWASP "never log": secrets. Unconditional, dev included.
_SECRET_KEYS = {
    "password",
    "passwordconfirm",
    "currentpassword",
    "newpassword",
    "token",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "sessiontoken",
    "apikey",
    "secret",
    "authorization",
    "cookie",
    "setcookie",
    "xapikey",
    "connectionstring",
    "databaseurl",
    "dsn",
}

# OWASP "log with caution": personal data, pseudonymised.
_PII_KEYS = {
    "email",
    "phone",
    "phonenumber",
    "address",
    "street",
    "postalcode",
    "zip",
    "latitude",
    "longitude",
    "lat",
    "lng",
    "lon",
    "coordinates",
    "coords",
    "firstname",
    "lastname",
    "fullname",
}

_DENY_KEYS = _SECRET_KEYS | _PII_KEYS

# Values that arrive inside a string instead of under a key, where matching on the key cannot
# reach them: requests/urllib3 put the full request URL in their exception text, psycopg puts
# the connection string in its own, and an f-string log message bakes in whatever it formatted.
_TEXT_KEYS = {"event", "message", "error", "exception", "stack", "traceback", "excinfo"}

_URL_CREDENTIALS_RE = re.compile(r"([a-zA-Z][\w+.-]*://[^\s:/@]+):[^\s@/]+@")

# Only the sensitive query params, not the whole query string: in a tile request the dataset in
# `url=` is the most useful thing on the line, and nuking it costs more than it protects.
_SENSITIVE_PARAM_RE = re.compile(
    r"([?&][^=&\s]*(?:key|token|secret|password|signature|sig|credential|auth)[^=&\s]*=)"
    r"[^&\s\"'>]+",
    re.IGNORECASE,
)


def _normalize(key: str) -> str:
    return key.replace("_", "").replace("-", "").lower()


def _scrub_text(text: str) -> str:
    text = _URL_CREDENTIALS_RE.sub(rf"\1:{REDACTED}@", text)

    return _SENSITIVE_PARAM_RE.sub(rf"\g<1>{REDACTED}", text)


def _redact(value):
    if isinstance(value, dict):
        return {
            k: REDACTED if _normalize(str(k)) in _DENY_KEYS else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def redact_processor(logger, method_name, event_dict):
    """structlog processor: masks denied keys at any depth, scrubs credentials out of log text.

    The scrub is top-level only. Exception text and the log message live there, whereas a
    nested `message` is user prose — scrubbing that would silently mangle what we log to
    debug with, for no gain.
    """
    redacted = _redact(event_dict)

    for key, value in redacted.items():
        if _normalize(str(key)) in _TEXT_KEYS and isinstance(value, str):
            redacted[key] = _scrub_text(value)

    return redacted


# Cloud Logging reads severity from a top-level `severity` field, not structlog's `level`.
_SEVERITY_BY_LEVEL = {
    "critical": "CRITICAL",
    "error": "ERROR",
    "warning": "WARNING",
    "info": "INFO",
    "debug": "DEBUG",
}


def severity_processor(logger, method_name, event_dict):
    """structlog processor: adds the Cloud Logging severity for the line's level."""
    level = event_dict.get("level") or method_name or ""
    event_dict["severity"] = _SEVERITY_BY_LEVEL.get(str(level).lower(), "DEFAULT")
    return event_dict
