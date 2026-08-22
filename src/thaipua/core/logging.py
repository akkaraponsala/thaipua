"""Configure application-wide console and rotating-file logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from thaipua.core.constants import APP_DATA_DIR

LOG_FILE_NAME: str = "thaipua.log"
LOG_FORMAT: str = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
FILE_MAX_BYTES: int = 1_000_000
FILE_BACKUP_COUNT: int = 5

_CONFIGURED_FLAG: str = "_thaipua_logging_configured"


def setup_logging(
    base_dir: Path | None = None,
    *,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> Path:
    """Attach console and rotating-file handlers to the root logger once, returning the log path."""
    root_logger = logging.getLogger()
    if getattr(root_logger, _CONFIGURED_FLAG, False):
        return log_file_path(base_dir)

    log_path = log_file_path(base_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=FILE_MAX_BYTES, backupCount=FILE_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)

    root_logger.setLevel(min(console_level, file_level))
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    setattr(root_logger, _CONFIGURED_FLAG, True)
    return log_path


def log_file_path(base_dir: Path | None = None) -> Path:
    """Return the log file path under `base_dir` (or `APP_DATA_DIR`)."""
    return (Path(base_dir) if base_dir is not None else APP_DATA_DIR) / LOG_FILE_NAME
