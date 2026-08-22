"""Modal PUA mapping editor with a filterable table and live validation badges."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from thaipua.core.fonttools.map_validation import (
    IssueSeverity,
    PuaMapIssue,
    PuaSlotContext,
    parse_codepoint,
    validate_pua_map,
)
from thaipua.core.fonttools.specs import decompose_thai_cluster

_ERROR_BACKGROUND = QColor(190, 60, 60, 46)
_WARNING_BACKGROUND = QColor(216, 160, 40, 40)
_ERROR_FOREGROUND = QColor(224, 85, 85)
_WARNING_FOREGROUND = QColor(217, 154, 43)


class _Column(IntEnum):
    """Table columns."""

    THAI = 0
    PUA = 1
    STATUS = 2
    PARTS = 3


_COLUMN_COUNT = len(_Column)
_COLUMN_LABELS: dict[_Column, str] = {
    _Column.THAI: "Thai Cluster",
    _Column.PUA: "PUA Codepoint",
    _Column.STATUS: "Status",
    _Column.PARTS: "Parts",
}

_ROOT_INDEX = QModelIndex()
"""Module-level invalid index; avoids a function call in method-argument defaults."""


@dataclass(slots=True)
class _Row:
    """One editable mapping entry with its original value for dirty tracking."""

    thai_key: str
    original_char: str
    pua_char: str


def _parts_text(thai_key: str) -> str:
    """Render a cluster's decomposed parts as `ก + ่`, or `(invalid)`."""
    decomposed = decompose_thai_cluster(thai_key)
    if decomposed is None:
        return "(invalid)"
    cons_uni, below_uni, above_uni, tone_uni = decomposed
    chars = [chr(cons_uni)]
    chars.extend(chr(codepoint) for codepoint in (below_uni, above_uni, tone_uni) if codepoint)
    return " + ".join(chars)


class PuaMapTableModel(QAbstractTableModel):
    """Table model over the Thai-to-PUA map with per-row validation state."""

    issues_recomputed = Signal(int, int, int)
    """Emitted after each revalidation: `(errors, warnings, edited_rows)`."""

    def __init__(self, mapping: dict[str, str], slot_ctx: PuaSlotContext | None, parent: QWidget | None = None) -> None:
        """Build the model from `mapping`, validating against `slot_ctx` when given."""
        super().__init__(parent)
        self._rows = [_Row(thai_key, pua_char, pua_char) for thai_key, pua_char in mapping.items()]
        self._slot_ctx = slot_ctx
        self._row_issues: list[tuple[PuaMapIssue, ...]] = [()] * len(self._rows)
        self._revalidate()

    def row_at(self, row: int) -> _Row:
        """Return the internal `_Row` at `row` (for the filter proxy)."""
        return self._rows[row]

    def row_issues(self, row: int) -> tuple[PuaMapIssue, ...]:
        """Return the merged issues of `row`; empty means clean."""
        return self._row_issues[row]

    def result_mapping(self) -> dict[str, str]:
        """Return the current (possibly edited) Thai-key → PUA-char mapping."""
        return {row.thai_key: row.pua_char for row in self._rows}

    def next_issue_row(self, start_row: int) -> int | None:
        """Return the first flagged row at or after `start_row`, wrapping around."""
        total = len(self._rows)
        for offset in range(total):
            index = (start_row + offset) % total
            if self._row_issues[index]:
                return index
        return None

    def _revalidate(self) -> None:
        """Re-run the validator over the whole map and refresh issue state."""
        mapping = {row.thai_key: row.pua_char for row in self._rows}
        grouped: dict[str, list[PuaMapIssue]] = {}
        for issue in validate_pua_map(mapping, self._slot_ctx):
            grouped.setdefault(issue.thai_key, []).append(issue)
        self._row_issues = []
        errors = warnings = 0
        for row in self._rows:
            entries = tuple(grouped.get(row.thai_key, ()))
            self._row_issues.append(entries)
            has_error = any(entry.severity is IssueSeverity.ERROR for entry in entries)
            if has_error:
                errors += 1
            elif entries:
                warnings += 1
        edited = sum(1 for row in self._rows if row.pua_char != row.original_char)
        if self._rows:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, _COLUMN_COUNT - 1)
            self.dataChanged.emit(top_left, bottom_right)
        self.issues_recomputed.emit(errors, warnings, edited)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        """Return the row count (flat table — `parent` is always invalid here)."""
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        """Return the fixed column count."""
        return _COLUMN_COUNT

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return column labels / 1-based row numbers for header decoration."""
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return _COLUMN_LABELS.get(_Column(section))
        return str(section + 1)

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        """Make only the PUA-codepoint column editable."""
        base = super().flags(index)
        if index.column() == int(_Column.PUA):
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Serve display/edit/decoration roles for one cell."""
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        issues = self._row_issues[index.row()]
        if role == Qt.ItemDataRole.BackgroundRole and issues:
            has_error = any(entry.severity is IssueSeverity.ERROR for entry in issues)
            return _ERROR_BACKGROUND if has_error else _WARNING_BACKGROUND
        match _Column(index.column()):
            case _Column.THAI:
                if role == Qt.ItemDataRole.DisplayRole:
                    return row.thai_key
            case _Column.PUA:
                if role == Qt.ItemDataRole.DisplayRole:
                    if len(row.pua_char) == 1:
                        return f"U+{ord(row.pua_char):04X}"
                    return repr(row.pua_char)
                if role == Qt.ItemDataRole.EditRole:
                    return f"{ord(row.pua_char):04X}" if len(row.pua_char) == 1 else row.pua_char
            case _Column.STATUS:
                if role == Qt.ItemDataRole.DisplayRole:
                    if not issues:
                        return "OK"
                    has_error = any(entry.severity is IssueSeverity.ERROR for entry in issues)
                    return "ERROR" if has_error else "WARN"
                if role == Qt.ItemDataRole.ForegroundRole and issues:
                    has_error = any(entry.severity is IssueSeverity.ERROR for entry in issues)
                    return _ERROR_FOREGROUND if has_error else _WARNING_FOREGROUND
                if role == Qt.ItemDataRole.TextAlignmentRole:
                    return int(Qt.AlignmentFlag.AlignCenter)
            case _Column.PARTS:
                if role == Qt.ItemDataRole.DisplayRole:
                    return _parts_text(row.thai_key)
        if role == Qt.ItemDataRole.ToolTipRole and issues and _Column(index.column()) != _Column.PUA:
            return "\n".join(f"{entry.severity.value}: {entry.message}" for entry in issues)
        return None

    def setData(
        self, index: QModelIndex | QPersistentModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        """Commit a parsed PUA-codepoint edit and revalidate the whole map."""
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() != int(_Column.PUA):
            return False
        parsed = parse_codepoint(str(value))
        if parsed is None:
            return False
        self._rows[index.row()].pua_char = parsed
        self._revalidate()
        return True


class PuaMapFilterProxy(QSortFilterProxyModel):
    """Text/issues-only filter over `PuaMapTableModel` rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build an empty filter accepting every row until configured."""
        super().__init__(parent)
        self._query = ""
        self._issues_only = False

    def set_query(self, query: str) -> None:
        """Filter rows whose Thai key or PUA hex contains `query` (case-insensitive)."""
        self._query = query.strip().lower()
        self.invalidateFilter()

    def set_issues_only(self, issues_only: bool) -> None:
        """Restrict visible rows to those carrying at least one issue."""
        self._issues_only = issues_only
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        """Keep rows matching both the text query and the issues-only toggle."""
        model = self.sourceModel()
        if not isinstance(model, PuaMapTableModel):
            return True
        row = model.row_at(source_row)
        if self._issues_only and not model.row_issues(source_row):
            return False
        if self._query and self._query not in row.thai_key.lower():
            hex_label = f"{ord(row.pua_char):04x}" if len(row.pua_char) == 1 else ""
            if self._query not in hex_label:
                return False
        return True


class PuaMappingDialog(QDialog):
    """Modal editor over `pua_mapping.json`: browse, filter, edit, apply."""

    def __init__(
        self,
        mapping: dict[str, str],
        slot_ctx: PuaSlotContext | None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the editor over `mapping`; `slot_ctx=None` skips font-aware checks."""
        super().__init__(parent)
        self.setWindowTitle("PUA Mapping")
        self.resize(860, 640)
        self._model = PuaMapTableModel(mapping, slot_ctx, self)
        self._proxy = PuaMapFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        outer = QVBoxLayout(self)
        outer.addLayout(self._build_filter_row())
        outer.addWidget(self._build_table(), 1)
        outer.addLayout(self._build_button_row())
        self._summary = QLabel(self)
        self._update_summary(0, 0, 0)
        outer.insertWidget(1, self._summary)
        self._model.issues_recomputed.connect(self._update_summary)

    def result_mapping(self) -> dict[str, str]:
        """Return the mapping as currently edited (Apply semantics are the caller's)."""
        return self._model.result_mapping()

    def _build_filter_row(self) -> QHBoxLayout:
        """Build the Filter input, Issues-only toggle, and summary placeholder row."""
        row = QHBoxLayout()
        row.addWidget(QLabel("Filter:", self))
        self._filter_input = QLineEdit(self)
        self._filter_input.setPlaceholderText("Thai cluster or hex (e.g. E003)")
        self._filter_input.textChanged.connect(self._proxy.set_query)
        row.addWidget(self._filter_input, 1)
        self._issues_toggle = QCheckBox("Issues only", self)
        self._issues_toggle.toggled.connect(self._proxy.set_issues_only)
        row.addWidget(self._issues_toggle)
        return row

    def _build_table(self) -> QWidget:
        """Build the mapped `QTableView` with row selection and inline editing."""
        self._view = QTableView(self)
        self._view.setModel(self._proxy)
        self._view.setAlternatingRowColors(True)
        self._view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._view.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked
            | QTableView.EditTrigger.SelectedClicked
            | QTableView.EditTrigger.EditKeyPressed
        )
        self._view.verticalHeader().setVisible(False)
        header = self._view.horizontalHeader()
        for column in (_Column.PUA, _Column.STATUS):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_Column.THAI, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_Column.PARTS, QHeaderView.ResizeMode.Stretch)
        return self._view

    def _build_button_row(self) -> QHBoxLayout:
        """Build Jump-to-Next-Issue plus Cancel/Apply buttons."""
        row = QHBoxLayout()
        jump_btn = QPushButton("Jump to Next Issue", self)
        jump_btn.clicked.connect(self._jump_to_next_issue)
        row.addWidget(jump_btn)
        row.addStretch(1)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)
        apply_btn = QPushButton("Apply", self)
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.accept)
        row.addWidget(apply_btn)
        return row

    def _update_summary(self, errors: int, warnings: int, edited: int) -> None:
        """Refresh the summary line from the latest recomputation totals."""
        total = self._model.rowCount()
        parts = [f"{total} entries"]
        parts.append(f"{errors} error(s)" if errors == 1 else f"{errors} errors")
        parts.append(f"{warnings} warning(s)" if warnings == 1 else f"{warnings} warnings")
        if edited:
            parts.append(f"{edited} edited")
        self._summary.setText(" · ".join(parts))

    def _jump_to_next_issue(self) -> None:
        """Select and scroll to the next flagged row after the current selection."""
        current = self._view.selectionModel().currentIndex()
        source_row = self._proxy.mapToSource(current).row() if current.isValid() else -1
        target = self._model.next_issue_row(source_row + 1)
        if target is None:
            target = self._model.next_issue_row(0)
        if target is None:
            return
        proxy_index = self._proxy.mapFromSource(self._model.index(target, 0))
        self._view.selectionModel().setCurrentIndex(
            proxy_index, self._view.selectionModel().SelectionFlag.ClearAndSelect
        )
        self._view.scrollTo(proxy_index)


__all__ = ["PuaMapFilterProxy", "PuaMapTableModel", "PuaMappingDialog"]
