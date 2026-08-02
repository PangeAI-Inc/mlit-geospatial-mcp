import json
import os
import subprocess
import sys


def _run(code: str) -> list[dict]:
    """Run code in a fresh process against the real logger and return its JSON lines."""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        # Explicit, so an exported APP_ENV=local cannot flip this to console output.
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


def test_credentials_inside_text_are_scrubbed():
    line = _emit(
        error="HTTPSConnectionPool: https://api.example.com/v1?apiKey=SECRET123 failed",
        exception="OperationalError: postgres://user:PASSWORD123@db.internal:5432/app",
    )

    assert "SECRET123" not in line["error"]
    assert "PASSWORD123" not in line["exception"]
    assert line["error"].startswith("HTTPSConnectionPool")
    # Only the secret param goes: the rest of the URL is what makes the line debuggable.
    assert "apiKey=[Redacted]" in line["error"]
    assert "api.example.com/v1" in line["error"]
    assert "[Redacted]@db.internal:5432" in line["exception"]


# Coordinates are this service's whole input, so they are logged, not masked.
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


def test_stdlib_extra_fields_reach_the_event_dict():
    code = (
        "from src.utils.logger_config import setup_logger\n"
        "setup_logger('payload').info(\n"
        "    'build payload',\n"
        "    extra={'payload': {'coordinates': [{'lat': 35.6, 'lon': 139.7}]}},\n"
        ")\n"
    )

    line = _run(code)[-1]

    assert line["payload"]["coordinates"] == [{"lat": 35.6, "lon": 139.7}]
    assert line["severity"] == "INFO"


# requests puts the URL, API key included, in its exception text.
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


def test_setup_logger_emits_exactly_one_structured_line():
    code = (
        "from src.utils.logger_config import setup_logger\n"
        "setup_logger('probe').error('single line please')\n"
    )

    lines = _run(code)

    assert len(lines) == 1
    assert lines[0]["severity"] == "ERROR"

def test_deployed_conditions_render_json():
    result = subprocess.run(
        [sys.executable, "-c", "from src.logger import get_logger\nget_logger('x').info('probe')\n"],
        capture_output=True,
        text=True,
        env={**os.environ, "APP_ENV": "production"},
        check=True,
    )
    output = f"{result.stdout}\n{result.stderr}".strip()
    line = json.loads([x for x in output.splitlines() if x.startswith("{")][-1])

    assert line["severity"] == "INFO"
    assert "\x1b[" not in output, "ANSI escapes mean the console renderer was selected"


def test_app_env_local_keeps_console_output():
    result = subprocess.run(
        [sys.executable, "-c", "from src.logger import get_logger\nget_logger('x').info('probe')\n"],
        capture_output=True,
        text=True,
        env={**os.environ, "APP_ENV": "local"},
        check=True,
    )

    assert "\x1b[" in f"{result.stdout}{result.stderr}", "APP_ENV=local should stay readable"


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

def test_third_party_warnings_are_captured_but_not_their_chatter():
    code = (
        "import logging, warnings\n"
        "import src.logger  # noqa: F401  configures logging\n"
        "logging.getLogger('langchain_core').warning('tracer failed')\n"
        "logging.getLogger('httpx').info('HTTP Request: POST https://x')\n"
        "warnings.warn('deprecated', DeprecationWarning)\n"
    )

    lines = _run(code)
    messages = " ".join(line["message"] for line in lines)

    assert any(line["severity"] == "WARNING" for line in lines)
    assert "tracer failed" in messages
    assert "deprecated" in messages, "warnings.warn should route through captureWarnings"
    assert "HTTP Request" not in messages, "third-party INFO is below the root WARNING floor"
