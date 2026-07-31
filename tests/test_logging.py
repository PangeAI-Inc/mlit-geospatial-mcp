import json
import os
import subprocess
import sys


def _emit(**fields):
    """Run one line through the real logger in a fresh process and return the parsed JSON."""
    code = (
        "from src.logger import get_logger\n"
        f"get_logger('test').error('probe', **{fields!r})\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        # Any value but "local" selects the JSON renderer; passed explicitly so a
        # shell with APP_ENV=local exported does not turn this into console output.
        env={**os.environ, "APP_ENV": "test", "LOG_LEVEL": "INFO"},
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_line_carries_cloud_logging_severity():
    assert _emit(keep="yes")["severity"] == "ERROR"


def test_secrets_and_pii_are_redacted_at_any_depth():
    line = _emit(api_key="sk-live-1", user={"email": "a@b.co", "id": "u1"}, keep="yes")

    assert line["api_key"] == "[Redacted]"
    assert line["user"]["email"] == "[Redacted]"
    assert line["user"]["id"] == "u1"
    assert line["keep"] == "yes"
