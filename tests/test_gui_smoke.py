"""Offscreen GUI smoke: toolbar/grid/controls signals reach service state without modal dialogs."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch
from conftest import SAMPLE_FONT_PATH
from fontTools.ttLib import TTFont
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from thaipua.core.domain.settings import default_placement_settings, settings_to_dict
from thaipua.gui.main_window import MainWindow
from thaipua.gui.state import current_mark_offset
from thaipua.gui.widgets.pua_mapping_dialog import PuaMapTableModel

# Headless runners have no display server; force offscreen before Qt picks a platform.
# Paths that exec() a modal dialog (_on_pua_slots/_on_edit_mapping/_on_settings/_on_find_substitution)
# stay out of this suite — a modal exec with no one to dismiss it hangs forever.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """Share one QApplication; Qt reads the platform env on first construction."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    yield app
    app.processEvents()


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    """Build a window isolated to tmp paths; close without the dirty prompt on teardown."""
    win = MainWindow()
    win._service.set_layout_path(str(tmp_path / "layout.json"))
    win._service.set_pua_map_path(str(tmp_path / "pua.json"))
    yield win
    win._state.dirty = False
    win.close()
    win.deleteLater()
    qapp.processEvents()


@pytest.fixture
def loaded_window(window: MainWindow, monkeypatch: MonkeyPatch, tmp_path: Path) -> MainWindow:
    """Run the real open-font flow with a stubbed file dialog and no stem profile on disk."""
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(SAMPLE_FONT_PATH), ""))
    monkeypatch.setattr(window._service, "default_profile_path", lambda: tmp_path / "absent.json")
    window._toolbar.open_font_requested.emit()
    assert window._service.is_loaded
    return window


def test_window_builds_unloaded(window: MainWindow) -> None:
    assert window.windowTitle() == "ThaiPUA"
    assert not window._service.is_loaded
    assert window._toolbar is not None
    assert window._grid_pane is not None
    assert window._controls_pane is not None


def test_grid_pagination_wiring_without_font(window: MainWindow) -> None:
    window._grid_pane.next_page_requested.emit()
    assert window._state.consonants_page == 1
    window._grid_pane.prev_page_requested.emit()
    assert window._state.consonants_page == 0


def test_open_font_flow_populates_grid(loaded_window: MainWindow) -> None:
    window = loaded_window
    assert window._state.font_path == str(SAMPLE_FONT_PATH)
    assert len(window._spec_index()) == 2016
    assert window._service.settings is not None
    assert "ThaiPUA" in window.windowTitle()


def test_grid_click_flow_selects_spec(loaded_window: MainWindow, monkeypatch: MonkeyPatch) -> None:
    window = loaded_window
    calls: list[tuple[list[Any], dict[str, Any]]] = []
    monkeypatch.setattr(window._grid_pane, "show_pua", lambda visuals, **kwargs: calls.append((visuals, kwargs)))
    window._grid_pane.consonant_clicked.emit(0x0E01)
    assert window._state.active_consonant_uni == 0x0E01
    assert len(calls) == 1
    visuals, kwargs = calls[0]
    assert len(visuals) == 36
    assert kwargs["page_index"] == 0
    assert kwargs["total_pages"] == 2
    assert kwargs["consonant_label"] == "ก"
    code = visuals[0].key
    window._grid_pane.pua_clicked.emit(code)
    assert window._state.active_pua_code == code
    assert window._current_category is not None
    spec = window._active_spec()
    assert spec is not None
    assert spec.pua_code == code


def test_offset_edit_flow_mutates_settings(loaded_window: MainWindow) -> None:
    window = loaded_window
    window._grid_pane.consonant_clicked.emit(0x0E01)
    code = next(iter(window._spec_index()))
    window._grid_pane.pua_clicked.emit(code)
    spec = window._active_spec()
    settings = window._service.settings
    assert spec is not None
    assert window._current_category is not None
    before = current_mark_offset(spec, settings, category=window._current_category)
    window._controls_pane.offset_changed.emit(10, -5)
    after = current_mark_offset(spec, window._service.settings, category=window._current_category)
    assert after != before
    assert window._state.dirty
    assert window._grid_refresh_timer.isActive()


def test_undo_redo_flow_restores_offset_edit(loaded_window: MainWindow) -> None:
    window = loaded_window
    window._grid_pane.consonant_clicked.emit(0x0E01)
    code = next(iter(window._spec_index()))
    window._grid_pane.pua_clicked.emit(code)
    spec = window._active_spec()
    assert spec is not None
    assert window._current_category is not None
    pristine = current_mark_offset(spec, window._service.settings, category=window._current_category)
    assert not window._toolbar._undo_btn.isEnabled()
    window._controls_pane.offset_changed.emit(10, -5)
    edited = current_mark_offset(spec, window._service.settings, category=window._current_category)
    assert edited != pristine
    assert window._toolbar._undo_btn.isEnabled()
    assert "Offset" in window._toolbar._undo_btn.toolTip()
    window._toolbar.undo_requested.emit()
    assert current_mark_offset(spec, window._service.settings, category=window._current_category) == pristine
    assert not window._toolbar._undo_btn.isEnabled()
    assert window._toolbar._redo_btn.isEnabled()
    window._toolbar.redo_requested.emit()
    assert current_mark_offset(spec, window._service.settings, category=window._current_category) == edited
    assert window._toolbar._undo_btn.isEnabled()
    assert not window._toolbar._redo_btn.isEnabled()


def test_override_toggle_flow(loaded_window: MainWindow) -> None:
    window = loaded_window
    window._on_override_toggled(0xE001, True)
    assert 0xE001 in window._service.allowed_locked()
    assert "*" in window.windowTitle()
    window._on_override_toggled(0xE001, False)
    assert 0xE001 not in window._service.allowed_locked()


def test_relocate_flow_moves_key_to_tail(loaded_window: MainWindow) -> None:
    window = loaded_window
    tail = window._service.layout_tail_start()
    assert tail is not None
    assert window._service.pua_map["ก่"] == chr(0xE001)
    window._on_relocate_requested(0xE001)
    assert ord(window._service.pua_map["ก่"]) >= tail


def test_save_font_flow_writes_rebuilt_font(
    loaded_window: MainWindow, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    window = loaded_window
    out = tmp_path / "saved.ttf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(out), ""))
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: shown.append(("info", args[1])))
    critical: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: critical.append(args[1]))
    window._toolbar.save_font_requested.emit()
    assert out.is_file()
    assert critical == []
    assert len(shown) == 1
    assert not window._state.dirty
    reopened = TTFont(str(out))
    try:
        names = [
            name
            for codepoint, name in reopened.getBestCmap().items()
            if 0xE000 <= codepoint <= 0xF8FF and name.startswith("thaipua_")
        ]
        assert len(names) == 2016
    finally:
        reopened.close()


def test_encode_flow_writes_encoded_file(loaded_window: MainWindow, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    window = loaded_window
    source = tmp_path / "words.txt"
    source.write_text("ก่", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([str(source)], ""))
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: shown.append(args[1]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: shown.append(args[1]))
    window._toolbar.encode_thai_requested.emit()
    assert (tmp_path / "words_encoded.txt").is_file()
    assert len(shown) == 1


def test_reset_defaults_flow_guards_on_cancel(loaded_window: MainWindow, monkeypatch: MonkeyPatch) -> None:
    window = loaded_window
    window._on_global_mark_offset_changed("tone_mark", 0x0E48, 3, 4)
    assert settings_to_dict(window._service.settings) != settings_to_dict(default_placement_settings())
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
    window._controls_pane.reset_defaults_requested.emit()
    assert settings_to_dict(window._service.settings) != settings_to_dict(default_placement_settings())
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window._controls_pane.reset_defaults_requested.emit()
    assert settings_to_dict(window._service.settings) == settings_to_dict(default_placement_settings())


def _open_with_stem_profile(window: MainWindow, monkeypatch: MonkeyPatch, tmp_path: Path, payload: str) -> None:
    """Point the stem profile at `payload` and run the real open-font flow."""
    profile = tmp_path / "Sarabun-Regular.json"
    profile.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(window._service, "default_profile_path", lambda: profile)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(SAMPLE_FONT_PATH), ""))
    window._toolbar.open_font_requested.emit()
    assert window._service.is_loaded


def test_legacy_profile_offers_manual_adoption(window: MainWindow, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: shown.append(args[1]))
    _open_with_stem_profile(window, monkeypatch, tmp_path, '{"version": 1}')
    assert len(shown) == 1
    assert settings_to_dict(window._service.settings) == settings_to_dict(default_placement_settings())


def test_unreadable_profile_warns_and_loads_defaults(
    window: MainWindow, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: shown.append(args[1]))
    _open_with_stem_profile(window, monkeypatch, tmp_path, "{not json")
    assert len(shown) == 1
    assert settings_to_dict(window._service.settings) == settings_to_dict(default_placement_settings())


def test_mapping_model_reports_row_issues(qapp: QApplication) -> None:
    _ = qapp
    from thaipua.gui.widgets.pua_mapping_dialog import _Column

    emitted: list[tuple[int, int, int]] = []
    model = PuaMapTableModel({"ก่": "\ue001", "bogus": "\ue002"}, None, None)
    model.issues_recomputed.connect(lambda errors, warnings, edited: emitted.append((errors, warnings, edited)))
    assert model.rowCount() == 2
    assert model.issue_totals() == (1, 0, 0)
    assert model.result_mapping() == {"ก่": "\ue001", "bogus": "\ue002"}
    assert model.next_issue_row(0) == 1
    assert model.setData(model.index(1, int(_Column.PUA)), "E900")
    assert model.result_mapping()["bogus"] == chr(0xE900)
    assert emitted
    assert emitted[-1] == (1, 0, 1)
