"""App-wide tooltips anchored under the hovered widget instead of beside the mouse."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLabel, QWidget

from thaipua.gui import theme

_GAP_PX = 6
_EDGE_MARGIN_PX = 4
_HOVER_SLACK_PX = 12
_MAX_WIDTH_PX = 420
_AUTO_HIDE_MS = 10_000
_WAKE_UP_MS = 300
_RADIUS_PX = 6
_SHADOW_REACH_PX = 5
_SHADOW_DROP_PX = 3
_SHADOW_ALPHA = 25


class _TipWindow(QLabel):
    """Frameless translucent top-level label painting its rounded box manually for reliability."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setMaximumWidth(_MAX_WIDTH_PX)
        # Asymmetric vertical padding: the drop bias shifts the shadow field downward.
        self.setContentsMargins(
            8 + _SHADOW_REACH_PX,
            4 + _SHADOW_REACH_PX - _SHADOW_DROP_PX,
            8 + _SHADOW_REACH_PX,
            4 + _SHADOW_REACH_PX + _SHADOW_DROP_PX,
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint stacked shadow layers below the rounded box, then the label text on top."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        reach = float(_SHADOW_REACH_PX)
        drop = float(_SHADOW_DROP_PX)
        # The window is the box inflated by the shadow field; painting outside bounds would clip.
        box = QRectF(self.rect()).adjusted(reach, reach - drop, -reach, -reach - drop)
        # Layered alpha rects approximate a blur; a QGraphicsDropShadowEffect is unreliable on
        # translucent top-level windows.
        painter.setPen(Qt.PenStyle.NoPen)
        for k in range(_SHADOW_REACH_PX, 0, -1):
            alpha = round(_SHADOW_ALPHA * (_SHADOW_REACH_PX + 1 - k) / _SHADOW_REACH_PX)
            painter.setBrush(QColor(0, 0, 0, alpha))
            spread = float(k)
            ring = box.adjusted(-spread, -spread, spread, spread).translated(0.0, drop)
            painter.drawRoundedRect(ring, _RADIUS_PX + k, _RADIUS_PX + k)
        painter.setBrush(QColor(theme.get_palette().BG_TOOLTIP))
        painter.drawRoundedRect(box, _RADIUS_PX, _RADIUS_PX)
        super().paintEvent(event)


class AnchoredTooltipFilter(QObject):
    """Application event filter that reroutes `QEvent.ToolTip` to widget-anchored popups."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tip = _TipWindow()
        self._anchor = QRect()
        self._pending: QWidget | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_tip)
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_pending)

    def attach(self, app: QApplication) -> None:
        """Start intercepting every application event."""
        app.installEventFilter(self)

    def hide_tip(self) -> None:
        """Hide the popup and stop the auto-hide timer."""
        self._hide_timer.stop()
        self._tip.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Show the anchored tip on ToolTip and dismiss it on interaction outside the anchor."""
        etype = event.type()
        if etype == QEvent.Type.ToolTip:
            return self._show_for(watched)
        if etype == QEvent.Type.Enter:
            self._arm(watched)
            return False
        if etype == QEvent.Type.Leave:
            self._disarm()
            if isinstance(watched, QWidget):
                self.hide_tip()
            return False
        if etype == QEvent.Type.MouseMove:
            if (
                isinstance(event, QMouseEvent)
                and self._tip.isVisible()
                and not self._anchor.contains(event.globalPosition().toPoint())
            ):
                self.hide_tip()
            return False
        if etype in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.Hide,
            QEvent.Type.WindowDeactivate,
            QEvent.Type.ApplicationDeactivate,
        ):
            self._disarm()
            if isinstance(watched, QWidget):
                self.hide_tip()
            return False
        return False

    def _arm(self, watched: QObject) -> None:
        """Start the fast wake-up timer when the newly entered widget owns tooltip content.

        Qt delivers `QEvent.ToolTip` only after its own ~700ms dwell; arming on Enter
        lets the popup appear at `_WAKE_UP_MS` instead.
        """
        widget = watched if isinstance(watched, QWidget) else None
        if widget is None:
            return
        self._disarm()
        resolved = self._resolve_tooltip(widget)
        if resolved is None:
            return
        self._pending = widget
        self._show_timer.start(_WAKE_UP_MS)

    def _disarm(self) -> None:
        """Cancel any pending fast-show timer."""
        self._show_timer.stop()
        self._pending = None

    def _show_pending(self) -> None:
        """Popup the armed widget's tooltip once the fast wake-up delay elapses."""
        widget = self._pending
        self._pending = None
        if widget is None:
            return
        try:
            resolved = self._resolve_tooltip(widget)
        except RuntimeError:
            # Armed widget was destroyed during the delay; dropping the popup is the fallback.
            return
        if resolved is not None:
            text, anchor_widget, anchor_rect = resolved
            self._popup(
                text,
                anchor_widget.mapToGlobal(anchor_rect.topLeft()),
                anchor_widget.mapToGlobal(anchor_rect.bottomRight()),
                anchor_widget,
            )

    def _resolve_tooltip(self, widget: QWidget) -> tuple[str, QWidget, QRect] | None:
        """Return `(text, anchor_widget, anchor_rect)` for `widget`, or `None` without content.

        Item-view viewports resolve their model's ToolTipRole and anchor to the hovered cell.
        """
        text = widget.toolTip()
        anchor_widget = widget
        anchor_rect = widget.rect()
        if not text:
            view = anchor_widget.parentWidget()
            if isinstance(view, QAbstractItemView):
                index = view.indexAt(anchor_widget.mapFromGlobal(QCursor.pos()))
                data = index.data(Qt.ItemDataRole.ToolTipRole)
                if isinstance(data, str) and data and view.visualRect(index).isValid():
                    text = data
                    anchor_rect = view.visualRect(index)
                    anchor_widget = view
        if not text or not anchor_widget.isVisible():
            return None
        return text, anchor_widget, anchor_rect

    def _show_for(self, watched: QObject) -> bool:
        """Popup `watched`'s tooltip under its rect; item-view cells anchor to their row cell.

        Return `True` when consumed; empty tooltips fall through to Qt's default path.
        """
        widget = watched if isinstance(watched, QWidget) else None
        self._show_timer.stop()
        if widget is None:
            return False
        resolved = self._resolve_tooltip(widget)
        if resolved is None:
            return False
        text, anchor_widget, anchor_rect = resolved
        self._popup(
            text,
            anchor_widget.mapToGlobal(anchor_rect.topLeft()),
            anchor_widget.mapToGlobal(anchor_rect.bottomRight()),
            anchor_widget,
        )
        return True

    def _popup(self, text: str, top_left: QPoint, bottom_right: QPoint, widget: QWidget) -> None:
        """Show `text` centered under the global anchor rect, flipping above and clamping to the screen."""
        self._tip.setText(text)
        self._tip.adjustSize()
        size = self._tip.size()
        avail = widget.screen().availableGeometry()
        x = (top_left.x() + bottom_right.x()) // 2 - size.width() // 2
        x = max(avail.left() + _EDGE_MARGIN_PX, min(x, avail.right() - size.width() - _EDGE_MARGIN_PX))
        y = bottom_right.y() + _GAP_PX - _SHADOW_REACH_PX + _SHADOW_DROP_PX
        if y + size.height() > avail.bottom() - _EDGE_MARGIN_PX:
            y = top_left.y() - size.height() - _GAP_PX + _SHADOW_REACH_PX + _SHADOW_DROP_PX
        y = max(avail.top() + _EDGE_MARGIN_PX, y)
        # Anchor rect (inflated) drives move-dismissal; cursor inside it keeps the tip up.
        self._anchor = QRect(top_left, bottom_right).adjusted(
            -_HOVER_SLACK_PX, -_HOVER_SLACK_PX, _HOVER_SLACK_PX, _HOVER_SLACK_PX
        )
        self._tip.move(x, y)
        self._tip.show()
        self._tip.raise_()
        self._hide_timer.start(_AUTO_HIDE_MS)


_filter: AnchoredTooltipFilter | None = None


def install_anchored_tooltips(app: QApplication) -> None:
    """Route every widget tooltip through one shared anchored-popup filter."""
    global _filter
    if _filter is None:
        _filter = AnchoredTooltipFilter(app)
    _filter.attach(app)
