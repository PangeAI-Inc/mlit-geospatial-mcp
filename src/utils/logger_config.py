import logging

# Importing this configures the shared structlog chain and the root handler that renders these
# records; without it a bare-script entry point would leave them with no handler at all.
try:
    import logger  # noqa: F401
except ImportError:
    from src import logger  # noqa: F401


# ログ設定
def setup_logger(name: str, level=logging.INFO) -> logging.Logger:
    """Return a stdlib logger whose records render through the shared chain in logger.py.

    A shim, so the existing call sites do not change. It deliberately adds no handler of its
    own: one here plus the root handler emits every line twice, once as unstructured plaintext
    carrying no severity.
    """
    std_logger = logging.getLogger(name)
    std_logger.setLevel(level)

    return std_logger
