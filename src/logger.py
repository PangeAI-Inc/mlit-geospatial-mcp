import json
import logging
import os
import sys

import structlog
from structlog.dev import ConsoleRenderer

try:
    from .redaction import redact_processor, severity_processor
except ImportError:
    # server.py runs as a bare script (see README), not as part of the `src` package.
    from redaction import redact_processor, severity_processor

APP_ENV = os.environ.get("APP_ENV", "local")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
SERVICE_NAME = "mlit-geospatial-mcp"


def _standardize_log_structure(logger, method_name, event_dict):
    event_dict.setdefault("appEnv", APP_ENV)
    event_dict.setdefault("service", SERVICE_NAME)
    message = event_dict.get("event") or event_dict.get("message")
    if message:
        event_dict["message"] = message
    return event_dict


def _get_renderer():
    # Raw env var, not the APP_ENV constant: its "local" default would match in a container.
    if os.environ.get("APP_ENV") == "local" or sys.stderr.isatty():
        return ConsoleRenderer()
    return structlog.processors.JSONRenderer(serializer=json.dumps)


def _configure() -> None:
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            severity_processor,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _standardize_log_structure,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            redact_processor,
            _get_renderer(),
        ],
        # stderr: stdout is this server's MCP protocol channel.
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            severity_processor,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _standardize_log_structure,
            structlog.stdlib.ExtraAdder(),
            redact_processor,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _get_renderer(),
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # "" is the root logger, so existing logging.getLogger call sites need no change.
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [handler]
        std_logger.propagate = False
        std_logger.setLevel(level)


_configure()


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
