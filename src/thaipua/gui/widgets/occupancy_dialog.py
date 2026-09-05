"""Report of foreign PUA slot occupants with override, relocate, and remap actions."""

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from thaipua.core.font.occupancy import PuaOccupant
from thaipua.core.font.ownership import SlotOwnership
from thaipua.gui import theme


@dataclass(slots=True)
class OccupancyRow:
    """One foreign slot rendered into the dialog, with mapping context for its actions."""

    occupant: PuaOccupant
    path: QPainterPath | None
    mapped: bool
    overridden: bool


def _ownership_color(ownership: SlotOwnership) -> str:
    """Return the verdict text color for `ownership` from the active palette."""
    palette = theme.get_palette()
    if ownership is SlotOwnership.LOCKED:
        return palette.ERROR
    if ownership is SlotOwnership.REPLACEABLE:
        return palette.WARNING
    return palette.TEXT_DIM


class _Thumb(QWidget):
    """Small canvas painting a glyph preview path scaled to fit."""

    def __init__(self, path: QPainterPath | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self.setFixedSize(44, 44)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the glyph path centered at an optical fit, or nothing when empty."""
        del event
        if self._path is None or self._path.isEmpty():
            return
        rect = self._path.boundingRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = theme.get_palette()
        margin = 4.0
        avail_width = self.width() - margin * 2
        avail_height = self.height() - margin * 2
        scale = min(avail_width / rect.width(), avail_height / rect.height())
        painter.setPen(QPen(QColor(palette.GLYPH_PEN), 1.0 / scale))
        painter.setBrush(QColor(palette.GLYPH_FILL))
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(scale, -scale)
        painter.translate(-rect.center().x(), -rect.center().y())
        painter.drawPath(self._path)


class OccupancyDialog(QDialog):
    """Modal report over foreign PUA slots emitting override/relocate/remap requests."""

    override_toggled = Signal(int, bool)
    """`(codepoint, approve)` — emitted when a row's Override/Revoke button is pressed."""

    relocate_requested = Signal(int)
    """`codepoint` — emitted when a row's Relocate button is pressed."""

    remap_requested = Signal(int)
    """`codepoint` — emitted when a row's Remap button is pressed."""

    bulk_override_requested = Signal()
    bulk_relocate_requested = Signal()
    bulk_remap_requested = Signal()
    """Emitted by the *All* buttons; they act on every mapped, non-overridden slot."""

    def __init__(self, rows: list[OccupancyRow], parent: QWidget | None = None) -> None:
        """Build the report from `rows`; call `refresh` to swap in updated rows later."""
        super().__init__(parent)
        self.setWindowTitle("PUA Slots")
        self.resize(620, 620)
        outer = QVBoxLayout(self)
        self._summary = QLabel(self)
        outer.addWidget(self._summary)
        bulk = QHBoxLayout()
        for label, signal in (
            ("Override All", self.bulk_override_requested),
            ("Relocate All", self.bulk_relocate_requested),
            ("Remap All", self.bulk_remap_requested),
        ):
            btn = QPushButton(label, self)
            btn.clicked.connect(signal.emit)
            bulk.addWidget(btn)
        bulk.addStretch(1)
        outer.addLayout(bulk)
        self._list_host = QWidget(self)
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_host)
        outer.addWidget(scroll, 1)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.reject)
        outer.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.refresh(rows)

    def refresh(self, rows: list[OccupancyRow]) -> None:
        """Rebuild every row widget and the summary line from `rows`."""
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for row in rows:
            self._list_layout.addWidget(self._build_row(row))
        self._list_layout.addStretch(1)
        self._update_summary(rows)

    def _update_summary(self, rows: list[OccupancyRow]) -> None:
        """Refresh the summary line with per-state counts; zero buckets are omitted."""
        overridden = sum(1 for r in rows if r.overridden)
        mapped = sum(1 for r in rows if r.mapped and not r.overridden)
        unmapped = len(rows) - overridden - mapped
        parts = [f"{len(rows)} foreign slot(s)"]
        if overridden:
            parts.append(f"{overridden} overridden")
        if mapped:
            parts.append(f"{mapped} awaiting decision")
        if unmapped:
            parts.append(f"{unmapped} unmapped")
        self._summary.setText(" · ".join(parts))

    def _build_row(self, row: OccupancyRow) -> QWidget:
        """Assemble thumbnail, identity labels with a colored verdict, and action buttons.

        Override applies only to locked slots — foreign composites are replaced
        on install anyway, so they offer relocation/remapping instead.
        """
        host = QWidget(self._list_host)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(8, 4, 8, 4)
        occ = row.occupant
        layout.addWidget(_Thumb(row.path, host))
        color = _ownership_color(occ.ownership)
        info = QLabel(
            f"<b>U+{occ.codepoint:04X}</b> · {occ.glyph_name}"
            f"<br><small>{occ.detail} · <span style='color:{color}'>{occ.ownership.value}</span></small>",
            host,
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info, 1)
        if row.overridden:
            revoke_btn = QPushButton("Revoke", host)
            revoke_btn.clicked.connect(lambda _, cp=occ.codepoint: self.override_toggled.emit(cp, False))
            layout.addWidget(revoke_btn)
        elif row.mapped and occ.ownership is SlotOwnership.LOCKED:
            override_btn = QPushButton("Override", host)
            override_btn.clicked.connect(lambda _, cp=occ.codepoint: self.override_toggled.emit(cp, True))
            layout.addWidget(override_btn)
        if row.mapped:
            if not row.overridden:
                relocate_btn = QPushButton("Relocate", host)
                relocate_btn.clicked.connect(lambda _, cp=occ.codepoint: self.relocate_requested.emit(cp))
                layout.addWidget(relocate_btn)
            remap_btn = QPushButton("Remap…", host)
            remap_btn.clicked.connect(lambda _, cp=occ.codepoint: self.remap_requested.emit(cp))
            layout.addWidget(remap_btn)
        else:
            note = QLabel("(unmapped)", host)
            note.setStyleSheet(f"color: {theme.get_palette().TEXT_DIM}; font-size: 8pt;")
            layout.addWidget(note)
        return host
