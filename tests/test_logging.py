import json
import os
import subprocess
import sys


def _run(code: str) -> list[dict]:
    """Run code in a fresh process against the real logger and parse the JSON lines it emits.

    Both streams are read: structlog renders to stdout, while the stdlib bridge's StreamHandler
    defaults to stderr. Cloud Logging keys off the `severity` field either way.
    """
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        # Any value but "local" selects the JSON renderer; passed explicitly so a
        # shell with APP_ENV=local exported does not turn this into console output.
        env={**os.environ, "APP_ENV": "test", "LOG_LEVEL": "INFO"},
        check=True,
    )
    output = f"{result.stdout}\n{result.stderr}".strip()

    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def _emit(**fields):
    code = (
        "from src.logger import get_logger\n"
        f"get_logger('test').error('probe', **{fields!r})\n"
    )
    return _run(code)[-1]


def test_line_carries_cloud_logging_severity():
    assert _emit(keep="yes")["severity"] == "ERROR"


def test_secrets_and_pii_are_redacted_at_any_depth():
    line = _emit(api_key="sk-live-1", user={"email": "a@b.co", "id": "u1"}, keep="yes")

    assert line["api_key"] == "[Redacted]"
    assert line["user"]["email"] == "[Redacted]"
    assert line["user"]["id"] == "u1"
    assert line["keep"] == "yes"


# A key-based deny list cannot reach these: the credential is inside the string, not under a key.
def test_credentials_inside_text_are_scrubbed():
    line = _emit(
        error="HTTPSConnectionPool: https://api.example.com/v1?apiKey=SECRET123 failed",
        exception="OperationalError: postgres://user:PASSWORD123@db.internal:5432/app",
    )

    assert "SECRET123" not in line["error"]
    assert "PASSWORD123" not in line["exception"]
    # The line stays useful: only the query string and the password are replaced.
    assert line["error"].startswith("HTTPSConnectionPool")
    assert "?[Redacted]" in line["error"]
    assert "[Redacted]@db.internal:5432" in line["exception"]


# The payload shape build_payload produces, logged by both server.py and payload.py. The
# coordinates are the whole point of this service and are also the PII in it.
def test_tool_payload_redacts_coordinates_and_keeps_the_rest():
    payload = {
        "coordinates": [{"lat": 35.6812, "lon": 139.7671}],
        "target_apis": ["XKT013", "XKT014"],
        "year": "2024",
    }
    code = (
        "from src.logger import get_logger\n"
        f"get_logger('server').info('Tool payload', payload={payload!r})\n"
    )

    line = _run(code)[-1]

    assert line["payload"]["coordinates"] == "[Redacted]"
    assert line["payload"]["target_apis"] == ["XKT013", "XKT014"]
    assert line["payload"]["year"] == "2024"


# payload.py logs through the stdlib logger, so it passes the payload as `extra=`. ExtraAdder
# puts it on the event dict where redaction can walk it; an f-string would be opaque.
def test_stdlib_extra_fields_are_redacted():
    code = (
        "import logging, src.logger\n"
        "logging.getLogger('payload').info(\n"
        "    'build payload',\n"
        "    extra={'payload': {'coordinates': [{'lat': 35.6, 'lon': 139.7}]}},\n"
        ")\n"
    )

    line = _run(code)[-1]

    assert line["payload"]["coordinates"] == "[Redacted]"
    assert line["severity"] == "INFO"


# The real failure path in requester.py: requests puts the full URL, API key included, inside
# the exception's own text, so dropping `params` from the log is not enough on its own.
def test_api_failure_never_logs_the_api_key():
    code = (
        "import logging, src.logger\n"
        "url = 'https://www.reinfolib.mlit.go.jp/ex-api/external/XKT013'\n"
        "logging.getLogger('requester').error(\n"
        "    f\"API呼び出し失敗 URL:{url} param_keys:['apiKey', 'year'] \"\n"
        "    f\"エラー:HTTPError 401 for url: {url}?apiKey=SECRET123&year=2024\"\n"
        ")\n"
    )

    line = _run(code)[-1]

    assert "SECRET123" not in json.dumps(line, ensure_ascii=False)
    assert line["severity"] == "ERROR"
    # Key names stay: knowing which params were sent is what makes the line debuggable.
    assert "apiKey" in line["message"]


# setup_logger used to attach its own handler while still propagating to the root one, which
# emitted every line twice — once as plaintext carrying no severity.
def test_setup_logger_emits_exactly_one_structured_line():
    code = (
        "from src.utils.logger_config import setup_logger\n"
        "setup_logger('probe').error('single line please')\n"
    )

    lines = _run(code)

    assert len(lines) == 1
    assert lines[0]["severity"] == "ERROR"
