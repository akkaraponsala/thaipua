"""Middle pane rendering the glyph canvas with typographic guides and pan/zoom navigation."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from thaipua.gui import theme
from thaipua.gui.font_service import ComponentBox, GlyphRender

_GUIDE_BASELINE_COLOR = QColor("#EF4444")
_GUIDE_CAP_COLOR = QColor("#3B82F6")
_GUIDE_XHEIGHT_COLOR = QColor("#22C55E")
_GUIDE_ADVANCE_COLOR = QColor("#A855F7")
_COMPONENT_BOX_COLOR = QColor("#9CA3AF")
_VIEW_MARGIN_PX = 24
_VERTICAL_METRIC_PAD_EM = 0.1
_MIN_ZOOM = 0.1
_MAX_ZOOM = 40.0
_ZOOM_STEP_FACTOR = 1.15
_EMPTY_HINT = "(no glyph selected)"


def _codepoint_label(codepoint: int) -> str:
    """Format `codepoint` as a `U+XXXX`/`U+XXXXX` string with min 4 hex digits."""
    return f"U+{codepoint:04X}"


class _Viewport(QWidget):
    """Zoomable, pannable canvas drawing the glyph with metric guides.

    The base fit derives from font metrics only, so scale and baseline stay consistent
    across every glyph of one font; user zoom multiplies it and drag accumulates pan.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize an empty viewport with a centered fit (pan=0, zoom=1)."""
        super().__init__(parent)
        self._render: GlyphRender | None = None
        self._path: QPainterPath | None = None
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._dragging = False
        self._last_pos = QPointF(0.0, 0.0)
        self.setMinimumSize(300, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_glyph(self, render: GlyphRender | None, path: QPainterPath | None) -> None:
        """Display a new glyph, keeping the typographic origin stable when possible."""
        old_origin = None
        if self._has_drawable_glyph():
            old_origin = self._device_point_for_font(0.0, 0.0)
        self._render = render
        self._path = path
        self._apply_idle_cursor()
        if old_origin is not None and self._has_drawable_glyph():
            self._keep_font_point_at_device(0.0, 0.0, old_origin)
        self._ensure_glyph_visible()
        self.update()

    def reset_view(self) -> None:
        """Reset pan/zoom to the centered fit (the empty default)."""
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._dragging = False
        self._apply_idle_cursor()
        self.update()

    def _has_drawable_glyph(self) -> bool:
        """Return `True` when a glyph with a non-empty path is currently set.

        Also requires `units_per_em != 0` so a non-zero `base_scale` is derivable; an
        unset/em-zero render is treated as the empty state and the hint is drawn
        instead.
        """
        render = self._render
        return (
            render is not None
            and render.glyph_name is not None
            and (render.units_per_em != 0)
            and (self._path is not None)
            and (not self._path.isEmpty())
        )

    def _view_params(self) -> tuple[float, float, float, float] | None:
        """Fit the font metric box to the widget, returning scale and centering parameters."""
        render = self._render
        if render is None or render.units_per_em == 0:
            return None
        upem = render.units_per_em
        ascender = max(render.ascender, 0)
        descender = min(render.descender, 0)
        pad = _VERTICAL_METRIC_PAD_EM * upem
        metric_h = max(ascender - descender + 2 * pad, 1.0)
        metric_w = max(upem, 1.0)
        avail_w = max(self.width() - 2 * _VIEW_MARGIN_PX, 1)
        avail_h = max(self.height() - 2 * _VIEW_MARGIN_PX, 1)
        base_scale = min(avail_w / metric_w, avail_h / metric_h)
        advance = render.advance_width
        bbox = render.bbox
        x_min = min(bbox[0] if bbox else 0, 0, advance)
        x_max = max(bbox[2] if bbox else 0, 0, advance)
        glyph_cx = (x_min + x_max) / 2.0
        metric_cy = (ascender + descender) / 2.0
        return (base_scale, glyph_cx, metric_cy, base_scale * self._zoom)

    def _glyph_bbox_font(self) -> tuple[float, float, float, float] | None:
        """Union the glyph's ink bounds in font space, excluding origin and advance."""
        render = self._render
        if render is None:
            return None
        boxes: list[tuple[float, float, float, float]] = []
        if render.bbox is not None:
            x0, y0, x1, y1 = render.bbox
            boxes.append((float(x0), float(y0), float(x1), float(y1)))
        if render.component_boxes:
            for component_box in render.component_boxes:
                x0, y0, x1, y1 = component_box.bbox
                boxes.append((float(x0), float(y0), float(x1), float(y1)))
        if not boxes and self._path is not None and not self._path.isEmpty():
            r = self._path.boundingRect()
            boxes.append((float(r.left()), float(r.top()), float(r.right()), float(r.bottom())))
        if not boxes:
            return None
        x_min = min(b[0] for b in boxes)
        y_min = min(b[1] for b in boxes)
        x_max = max(b[2] for b in boxes)
        y_max = max(b[3] for b in boxes)
        if x_max <= x_min:
            x_max = x_min + 1.0
        if y_max <= y_min:
            y_min = min(float(render.descender), 0.0)
            y_max = max(float(render.ascender), 0.0)
        if y_max <= y_min:
            y_max = y_min + 1.0
        return (x_min, y_min, x_max, y_max)

    def _device_rect_for_bbox(self, bbox: tuple[float, float, float, float]) -> QRectF | None:
        """Map a font-space `bbox` to the current device-space rectangle."""
        params = self._view_params()
        if params is None:
            return None
        _base_scale, glyph_cx, metric_cy, eff_scale = params
        x_min, y_min, x_max, y_max = bbox
        vcx = self.width() / 2.0
        vcy = self.height() / 2.0
        left = vcx + self._pan.x() + (x_min - glyph_cx) * eff_scale
        right = vcx + self._pan.x() + (x_max - glyph_cx) * eff_scale
        top = vcy + self._pan.y() - (y_max - metric_cy) * eff_scale
        bottom = vcy + self._pan.y() - (y_min - metric_cy) * eff_scale
        return QRectF(
            QPointF(min(left, right), min(top, bottom)),
            QPointF(max(left, right), max(top, bottom)),
        )

    def _device_point_for_font(self, font_x: float, font_y: float) -> QPointF | None:
        """Map a font-space point to device space under the current view."""
        params = self._view_params()
        if params is None:
            return None
        _base_scale, glyph_cx, metric_cy, eff_scale = params
        vcx = self.width() / 2.0
        vcy = self.height() / 2.0
        x = vcx + self._pan.x() + (font_x - glyph_cx) * eff_scale
        y = vcy + self._pan.y() - (font_y - metric_cy) * eff_scale
        return QPointF(x, y)

    def _keep_font_point_at_device(self, font_x: float, font_y: float, device_point: QPointF) -> None:
        """Adjust `_pan` so that the font-space point stays at `device_point`."""
        params = self._view_params()
        if params is None:
            return
        _base_scale, glyph_cx, metric_cy, eff_scale = params
        vcx = self.width() / 2.0
        vcy = self.height() / 2.0
        self._pan = QPointF(
            device_point.x() - vcx - (font_x - glyph_cx) * eff_scale,
            device_point.y() - vcy + (font_y - metric_cy) * eff_scale,
        )

    def _ensure_glyph_visible(self, margin: float = 0.0) -> bool:
        """Pan minimally when the glyph bbox leaves the viewport; return `True` when adjusted."""
        if not self._has_drawable_glyph():
            return False
        bbox = self._glyph_bbox_font()
        if bbox is None:
            return False
        rect = self._device_rect_for_bbox(bbox)
        if rect is None:
            return False
        view = QRectF(0.0, 0.0, float(self.width()), float(self.height())).adjusted(margin, margin, -margin, -margin)
        if view.width() <= 0.0 or view.height() <= 0.0:
            return False
        dx = 0.0
        dy = 0.0
        if rect.width() <= view.width():
            if rect.left() < view.left():
                dx = view.left() - rect.left()
            elif rect.right() > view.right():
                dx = view.right() - rect.right()
        else:
            if rect.right() < view.left():
                dx = view.left() - rect.right()
            elif rect.left() > view.right():
                dx = view.right() - rect.left()
        if rect.height() <= view.height():
            if rect.top() < view.top():
                dy = view.top() - rect.top()
            elif rect.bottom() > view.bottom():
                dy = view.bottom() - rect.bottom()
        else:
            if rect.bottom() < view.top():
                dy = view.top() - rect.bottom()
            elif rect.top() > view.bottom():
                dy = view.bottom() - rect.top()
        if abs(dx) < 0.01:
            dx = 0.0
        if abs(dy) < 0.01:
            dy = 0.0
        if dx != 0.0 or dy != 0.0:
            self._pan = QPointF(self._pan.x() + dx, self._pan.y() + dy)
            self.update()
            return True
        return False

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the canvas background, guides, and glyph path with pan/zoom applied."""
        palette = theme.get_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(palette.BG_PANE))
        if not self._has_drawable_glyph():
            painter.setPen(QColor(palette.TEXT_DIM))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _EMPTY_HINT)
            return
        render = self._render
        assert render is not None
        assert self._path is not None
        params = self._view_params()
        assert params is not None
        _base_scale, glyph_cx, metric_cy, eff_scale = params
        ascender = max(render.ascender, 0)
        descender = min(render.descender, 0)
        cap_height = render.cap_height
        x_height = render.x_height
        advance = render.advance_width
        vcx = self.width() / 2.0
        vcy = self.height() / 2.0
        self._draw_guides(
            painter,
            vcx=vcx,
            vcy=vcy,
            glyph_cx=glyph_cx,
            metric_cy=metric_cy,
            eff_scale=eff_scale,
            ascender=ascender,
            cap_height=cap_height,
            x_height=x_height,
            descender=descender,
            advance=advance,
        )
        transform = QTransform()
        transform.translate(vcx + self._pan.x(), vcy + self._pan.y())
        transform.scale(eff_scale, -eff_scale)
        transform.translate(-glyph_cx, -metric_cy)
        painter.setTransform(transform)
        painter.setPen(QPen(QColor(palette.GLYPH_PEN), 1.0 / eff_scale))
        painter.setBrush(QColor(palette.GLYPH_FILL))
        painter.drawPath(self._path)
        self._draw_component_boxes(painter, render.component_boxes, eff_scale)

    def _draw_guides(
        self,
        painter: QPainter,
        *,
        vcx: float,
        vcy: float,
        glyph_cx: float,
        metric_cy: float,
        eff_scale: float,
        ascender: int,
        cap_height: int,
        x_height: int,
        descender: int,
        advance: int,
    ) -> None:
        """Draw full-width baseline, height, and advance guides in device space."""

        def y_dev(font_y: int) -> float:
            """Map a font-space `font_y` to its device Y under the current view."""
            return vcy + self._pan.y() - (font_y - metric_cy) * eff_scale

        def h_line(font_y: int, color: QColor) -> None:
            """Draw a full-width horizontal guide at font-space `font_y`."""
            pen = QPen(color)
            pen.setStyle(Qt.PenStyle.SolidLine)
            pen.setWidthF(1.0)
            painter.setPen(pen)
            y = y_dev(font_y)
            painter.drawLine(QPointF(0.0, y), QPointF(float(self.width()), y))

        h_line(0, _GUIDE_BASELINE_COLOR)
        h_line(ascender, _GUIDE_CAP_COLOR)
        h_line(cap_height, _GUIDE_CAP_COLOR)
        h_line(x_height, _GUIDE_XHEIGHT_COLOR)
        h_line(descender, _GUIDE_BASELINE_COLOR)
        x_advance = vcx + self._pan.x() + (advance - glyph_cx) * eff_scale
        adv_pen = QPen(_GUIDE_ADVANCE_COLOR)
        adv_pen.setStyle(Qt.PenStyle.SolidLine)
        adv_pen.setWidthF(1.0)
        painter.setPen(adv_pen)
        painter.drawLine(QPointF(x_advance, 0.0), QPointF(x_advance, float(self.height())))

    def _draw_component_boxes(
        self, painter: QPainter, component_boxes: list[ComponentBox] | None, eff_scale: float
    ) -> None:
        """Outline each placed component box at a constant device-pixel width."""
        if component_boxes is None:
            return
        for component_box in component_boxes:
            x_min, y_min, x_max, y_max = component_box.bbox
            box_pen = QPen(_COMPONENT_BOX_COLOR)
            box_pen.setStyle(Qt.PenStyle.SolidLine)
            box_pen.setWidthF(1.0 / eff_scale)
            painter.setPen(box_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(QPointF(x_min, y_min), QPointF(x_max, y_max)))

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom the canvas toward the cursor with the mouse wheel."""
        if not self._has_drawable_glyph():
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        factor = _ZOOM_STEP_FACTOR if delta > 0 else 1.0 / _ZOOM_STEP_FACTOR
        self._apply_zoom(event.position(), factor)
        event.accept()

    def _apply_zoom(self, cursor: QPointF, factor: float) -> None:
        """Scale the zoom by `factor` while keeping `cursor` anchored in device space."""
        new_zoom = max(_MIN_ZOOM, min(_MAX_ZOOM, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        ratio = new_zoom / self._zoom
        vcx = self.width() / 2.0
        vcy = self.height() / 2.0
        self._pan = QPointF(
            (1.0 - ratio) * (cursor.x() - vcx) + ratio * self._pan.x(),
            (1.0 - ratio) * (cursor.y() - vcy) + ratio * self._pan.y(),
        )
        self._zoom = new_zoom
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a pan drag on the left mouse button when a glyph is shown."""
        if event.button() != Qt.MouseButton.LeftButton or not self._has_drawable_glyph():
            event.ignore()
            return
        self._dragging = True
        self._last_pos = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Accumulate device-space pan while the left button is held."""
        if not self._dragging:
            event.ignore()
            return
        delta = event.position() - self._last_pos
        self._pan = QPointF(self._pan.x() + delta.x(), self._pan.y() + delta.y())
        self._last_pos = event.position()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """End a pan drag on the left mouse button."""
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            event.ignore()
            return
        self._dragging = False
        self._apply_idle_cursor()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Reset pan/zoom to the centered fit on a left-button double-click."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self.reset_view()
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Repaint on resize so guides and glyph re-fit the new widget size."""
        super().resizeEvent(event)
        self.update()

    def _apply_idle_cursor(self) -> None:
        """Restore the idle cursor (open hand if a glyph is shown, arrow otherwise)."""
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._has_drawable_glyph() else Qt.CursorShape.ArrowCursor)


class GlyphPreviewPane(QWidget):
    """Middle pane header bar with metadata, plus the painted glyph viewport."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the *Glyph Preview* pane in the empty state."""
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QLabel("Glyph Preview", self)
        header.setObjectName("PaneHeader")
        outer.addWidget(header)
        meta_bar = QWidget(self)
        meta_layout = QHBoxLayout(meta_bar)
        meta_layout.setContentsMargins(8, 6, 8, 6)
        meta_layout.setSpacing(4)
        self._unicode_label = QLabel("—", meta_bar)
        self._name_label = QLabel("—", meta_bar)
        self._unicode_label.setObjectName("MetaValue")
        self._name_label.setObjectName("MetaValue")
        dot = QLabel("·", meta_bar)
        dot.setObjectName("Label")
        meta_layout.addWidget(self._unicode_label)
        meta_layout.addWidget(dot)
        meta_layout.addWidget(self._name_label)
        meta_layout.addStretch(1)
        outer.addWidget(meta_bar)
        self._viewport = _Viewport(self)
        outer.addWidget(self._viewport, 1)

    def set_metadata(self, codepoint: int | None, glyph_name: str | None) -> None:
        """Update the unicode/glyph-name metadata row; `None` clears it."""
        self._unicode_label.setText(_codepoint_label(codepoint) if codepoint else "—")
        self._name_label.setText(glyph_name or "—")

    def set_render(self, render: GlyphRender | None, path: QPainterPath | None) -> None:
        """Hand a freshly built `QPainterPath` + metrics to the viewport for repaint."""
        self._viewport.set_glyph(render, path)

    def clear(self) -> None:
        """Reset the preview to its empty placeholder state."""
        self._viewport.set_glyph(None, None)

    def refresh(self) -> None:
        """Repaint the canvas for the active theme palette."""
        self._viewport.update()
