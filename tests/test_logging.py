"""Unit tests for application logging setup."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from thaipua.core.logging import _CONFIGURED_FLAG, log_file_path, setup_logging


@pytest.fixture
def _clean_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    was_configured = getattr(root, _CONFIGURED_FLAG, False)
    if was_configured:
        delattr(root, _CONFIGURED_FLAG)
    yield
    for handler in root.handlers[:]:
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    if was_configured:
        setattr(root, _CONFIGURED_FLAG, True)


@pytest.mark.usefixtures("_clean_root_logger")
def test_setup_logging_writes_file_and_respects_levels(tmp_path: Path) -> None:
    log_path = setup_logging(tmp_path)
    assert log_path == tmp_path / "thaipua.log"

    logging.getLogger("thaipua.test").info("visible message")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "visible message" in content


@pytest.mark.usefixtures("_clean_root_logger")
def test_setup_logging_is_idempotent(tmp_path: Path) -> None:
    first = setup_logging(tmp_path)
    handler_count = len(logging.getLogger().handlers)
    second = setup_logging(tmp_path / "elsewhere")
    assert second == tmp_path / "elsewhere" / "thaipua.log"
    assert not second.exists()
    assert len(logging.getLogger().handlers) == handler_count
    assert first.is_file()


def test_log_file_path_defaults_to_app_data_dir() -> None:
    from thaipua.core.constants import APP_DATA_DIR

    assert log_file_path() == APP_DATA_DIR / "thaipua.log"
