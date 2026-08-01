"""Key-based redaction for structlog."""

import re

REDACTED = "[Redacted]"

# OWASP "never log": secrets.
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

# Direct identifiers: no debugging value, since user ids are logged alongside them.
_PII_KEYS = {
    "email",
    "phone",
    "phonenumber",
    "firstname",
    "lastname",
    "fullname",
}

# Location and address keys are intentionally absent: they are what these services analyse.

_DENY_KEYS = _SECRET_KEYS | _PII_KEYS

# Text fields, where a credential can sit inside the string with no key to match.
_TEXT_KEYS = {"event", "message", "error", "exception", "stack"}

_URL_CREDENTIALS_RE = re.compile(r"([a-zA-Z][\w+.-]*://[^\s:/@]+):[^\s@/]+@")

# Only the sensitive params: the rest of a URL is what makes the line debuggable.
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
    """Mask denied keys at any depth; scrub credentials from top-level text only.

    Nested text is user prose, and rewriting it would mangle what we debug from.
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
