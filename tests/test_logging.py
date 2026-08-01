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
    # Only the secret param goes: the rest of the URL is what makes the line debuggable.
    assert "apiKey=[Redacted]" in line["error"]
    assert "api.example.com/v1" in line["error"]
    assert "[Redacted]@db.internal:5432" in line["exception"]


# The payload shape build_payload produces, logged by both server.py and payload.py. The
# coordinates are the whole point of this service, so they are logged, not masked.
def test_tool_payload_stays_reproducible():
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

    assert line["payload"]["coordinates"] == [{"lat": 35.6812, "lon": 139.7671}]
    assert line["payload"]["target_apis"] == ["XKT013", "XKT014"]
    assert line["payload"]["year"] == "2024"


# payload.py logs through the stdlib logger, so it passes the payload as `extra=`. ExtraAdder
# puts it on the event dict where redaction can walk it; an f-string would be opaque to it.
def test_stdlib_extra_fields_reach_the_event_dict():
    code = (
        "import logging, src.logger\n"
        "logging.getLogger('payload').info(\n"
        "    'build payload',\n"
        "    extra={'payload': {'coordinates': [{'lat': 35.6, 'lon': 139.7}]}},\n"
        ")\n"
    )

    line = _run(code)[-1]

    assert line["payload"]["coordinates"] == [{"lat": 35.6, "lon": 139.7}]
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
    # Key names and non-secret params stay: that is what makes the line debuggable.
    assert "apiKey" in line["message"]
    assert "year=2024" in line["message"]


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

# The renderer decides between console and JSON. A deployed container has no terminal and does
# not set APP_ENV=local, which is the condition tile-server got wrong: it shipped ANSI-coloured
# plaintext with no severity to Cloud Logging. Piping this subprocess reproduces "no terminal".
def test_deployed_conditions_render_json():
    result = subprocess.run(
        [sys.executable, "-c", "from src.logger import get_logger\nget_logger('x').info('probe')\n"],
        capture_output=True,
        text=True,
        env={**os.environ, "APP_ENV": "production"},
        check=True,
    )
    output = f"{result.stdout}\n{result.stderr}".strip()
    line = json.loads([l for l in output.splitlines() if l.startswith("{")][-1])

    assert line["severity"] == "INFO"
    assert "\x1b[" not in output, "ANSI escapes mean the console renderer was selected"


# The explicit override a developer opts into, and which .env files already set.
def test_app_env_local_keeps_console_output():
    result = subprocess.run(
        [sys.executable, "-c", "from src.logger import get_logger\nget_logger('x').info('probe')\n"],
        capture_output=True,
        text=True,
        env={**os.environ, "APP_ENV": "local"},
        check=True,
    )

    assert "\x1b[" in f"{result.stdout}{result.stderr}", "APP_ENV=local should stay readable"


# mlit is a stdio MCP server: its stdout carries JSON-RPC frames, and the MCP spec forbids
# writing anything else there. The other services share the rule so all logs land on one stream.
def test_nothing_is_written_to_stdout():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.logger import get_logger\nget_logger('x').error('probe')\n",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "APP_ENV": "test"},
        check=True,
    )

    assert result.stdout == "", "stdout is a protocol channel; logs belong on stderr"
    assert json.loads(result.stderr.strip().splitlines()[-1])["severity"] == "ERROR"
