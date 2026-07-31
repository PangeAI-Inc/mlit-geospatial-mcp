"""Key-based redaction for structlog. Values never reach storage unredacted."""

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


def _normalize(key: str) -> str:
    return key.replace("_", "").replace("-", "").lower()


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
    """structlog processor: masks denied keys at any depth."""
    return _redact(event_dict)


# Cloud Logging reads severity from a top-level `severity` field, not structlog's `level`.
_SEVERITY_BY_LEVEL = {
    "critical": "CRITICAL",
    "error": "ERROR",
    "warning": "WARNING",
    "warn": "WARNING",
    "info": "INFO",
    "debug": "DEBUG",
    "trace": "DEBUG",
}


def severity_processor(logger, method_name, event_dict):
    """structlog processor: adds the Cloud Logging severity for the line's level."""
    level = event_dict.get("level") or method_name or ""
    event_dict["severity"] = _SEVERITY_BY_LEVEL.get(str(level).lower(), "DEFAULT")
    return event_dict
