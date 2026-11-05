"""Native graphical editor for flow diagrams (PySide6)."""

from __future__ import annotations

import copy
import math
import os
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QIcon,
                           QKeySequence, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QFrame, QGraphicsItem, QGraphicsObject, QGraphicsPathItem,
                               QGraphicsPolygonItem,
                               QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QPlainTextEdit, QScrollArea,
                               QSplitter, QVBoxLayout, QWidget)

from fluxograma import DARK, LIGHT


APP_QSS = """
QWidget { background: #101722; color: #e9f0f6; font-family: 'Segoe UI'; font-size: 10pt; }
QLabel { background: transparent; border: 0; }
QMainWindow, QWidget#root { background: #101722; }
QFrame#topbar, QFrame#panel, QFrame#canvasHeader, QFrame#canvasToolbar {
  background: #172333; border: 1px solid #27394d; border-radius: 12px;
}
QLabel#brand { color: #66d6bd; font-size: 11pt; font-weight: 700; letter-spacing: 1px; }
QLabel#pageTitle { color: #f5f8fb; font-size: 17pt; font-weight: 700; }
QLabel#muted, QLabel#pathLabel { color: #a3b3c4; }
QLabel#statusDirty { color: #e4bb68; font-weight: 600; }
QLabel#statusSaved { color: #67d2b8; font-weight: 600; }
QGroupBox { background: #172333; border: 1px solid #2a3d52; border-radius: 11px;
  margin-top: 13px; padding: 13px 12px 11px; font-weight: 650; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #9fb4c8; }
QLineEdit, QPlainTextEdit, QComboBox, QListWidget {
  background: #101a27; border: 1px solid #31475e; border-radius: 8px;
  padding: 7px 9px; selection-background-color: #226f69; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus { border: 1px solid #56bda9; }
QComboBox::drop-down { border: 0; width: 24px; }
QPushButton { background: #24364a; border: 1px solid #354c63; border-radius: 8px;
  padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #2b4258; border-color: #52718b; }
QPushButton:pressed { background: #192b3d; }
QPushButton#primary { background: #168879; border-color: #31a694; color: white; }
QPushButton#primary:hover { background: #1a9a87; }
QPushButton#accent { color: #70ddc4; border-color: #3b766f; }
QPushButton#danger { color: #ff9d9d; border-color: #75464d; }
QPushButton:checked { background: #24584f; border-color: #61c9b3; color: #d8fff5; }
QListWidget::item { padding: 7px 5px; border-radius: 5px; }
QListWidget::item:selected { background: #244c50; color: #effffb; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #101722; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #34495d; min-height: 26px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QGraphicsView { background: #0d141d; border: 1px solid #26394e; border-radius: 12px; }
QSplitter::handle { background: #101722; width: 7px; }
QStatusBar { background: #101722; color: #91a4b8; }
QPushButton#historyButton { min-width: 38px; padding: 7px 9px; font-size: 12pt; }
QLabel#sectionHint { color: #8298ad; font-size: 8.5pt; }
"""


class CommitTextEdit(QPlainTextEdit):
    editingFinished = Signal()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.editingFinished.emit()


class NodeItem(QGraphicsObject):
    clicked = Signal(str)
    moved = Signal(str, float, float)

    def __init__(self, node: Any, palette: dict[str, str]):
        super().__init__()
        self.node = node
        self.palette = palette
        self._press_pos: QPointF | None = None
        self.setPos(node.x, node.y)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(2)
        self.setToolTip("Arraste para reposicionar · clique para editar")

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.node.w, self.node.h)

    def shape_path(self) -> QPainterPath:
        r = self.boundingRect()
        path = QPainterPath()
        if self.node.shape == "diamond":
            path.moveTo(r.center().x(), r.top())
            path.lineTo(r.right(), r.center().y())
            path.lineTo(r.center().x(), r.bottom())
            path.lineTo(r.left(), r.center().y())
            path.closeSubpath()
        elif self.node.shape == "stadium":
            path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        else:
            path.addRoundedRect(r, 13, 13)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fills = {"alt": self.palette["alt_fill"], "bad": self.palette["bad_fill"],
                 "manual": self.palette["manual_fill"]}
        strokes = {"alt": self.palette["alt_border"], "bad": self.palette["bad_border"],
                   "manual": self.palette["manual_border"]}
        fill = QColor(fills.get(self.node.style, self.palette["panel"]))
        stroke = QColor(self.palette["accent"] if self.isSelected()
                        else strokes.get(self.node.style, self.palette["border"]))
        pen = QPen(stroke, 2.7 if self.isSelected() else 1.5)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawPath(self.shape_path())

        inner = self.boundingRect().adjusted(16, 8, -16, -8)
        title_font = QFont("Segoe UI", 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        sub_font = QFont("Segoe UI", 8)
        fm_title = QFontMetricsF(title_font)
        fm_sub = QFontMetricsF(sub_font)
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        title_rect = fm_title.boundingRect(QRectF(0, 0, inner.width(), 300), flags, self.node.title)
        sub_rect = (fm_sub.boundingRect(QRectF(0, 0, inner.width(), 200), flags, self.node.sub)
                    if self.node.sub else QRectF())
        tag_space = 19 if self.node.tag else 0
        total_h = title_rect.height() + (5 + sub_rect.height() if self.node.sub else 0) + tag_space
        y = max(inner.top(), inner.center().y() - total_h / 2)
        painter.setFont(title_font)
        painter.setPen(QColor(self.palette["text"]))
        title_h = min(title_rect.height() + 3, inner.height())
        painter.drawText(QRectF(inner.left(), y, inner.width(), title_h), flags, self.node.title)
        y += title_h
        if self.node.sub:
            y += 3
            painter.setFont(sub_font)
            painter.setPen(QColor(self.palette["muted"]))
            sub_h = min(sub_rect.height() + 2, max(0, inner.bottom() - y - tag_space))
            painter.drawText(QRectF(inner.left(), y, inner.width(), sub_h), flags, self.node.sub)

        if self.node.tag:
            tag_font = QFont("Segoe UI", 7)
            tag_font.setWeight(QFont.Weight.DemiBold)
            fm = QFontMetricsF(tag_font)
            tag_w = min(self.node.w - 28, fm.horizontalAdvance(self.node.tag) + 18)
            tag_rect = QRectF((self.node.w - tag_w) / 2, self.node.h - 22, tag_w, 15)
            tag_bg = QColor(self.palette["accent"])
            tag_bg.setAlpha(38)
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.setBrush(tag_bg)
            painter.drawRoundedRect(tag_rect, 7, 7)
            painter.setFont(tag_font)
            painter.setPen(QColor(self.palette["accent"]))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, self.node.tag)

    def mousePressEvent(self, event) -> None:
        self._press_pos = QPointF(self.pos())
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._press_pos is None:
            return
        delta = self.pos() - self._press_pos
        if abs(delta.x()) + abs(delta.y()) > 2:
            self.moved.emit(self.node.id, self.pos().x(), self.pos().y())
        else:
            self.clicked.emit(self.node.id)
        self._press_pos = None


class DiagramView(QGraphicsView):
    nodeClicked = Signal(str)
    nodeMoved = Signal(str, float, float)
    edgeClicked = Signal(int)

    def __init__(self, build_fn: Callable[[dict], Any], parent=None):
        super().__init__(parent)
        self.build_fn = build_fn
        self._node_items: dict[str, NodeItem] = {}
        self._palette = DARK
        self._panning = False
        self._pan_last = QPointF()
        scene = QGraphicsScene(self)
        self.setScene(scene)
        scene.selectionChanged.connect(self._scene_selection_changed)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMinimumWidth(500)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(self._palette["background"]))
        spacing = 28
        dots = []
        x = math.floor(rect.left() / spacing) * spacing
        while x <= rect.right():
            y = math.floor(rect.top() / spacing) * spacing
            while y <= rect.bottom():
                dots.append(QPointF(x, y))
                y += spacing
            x += spacing
        color = QColor("#263547" if self._palette.get("background") == DARK["background"] else "#dbe4ec")
        painter.setPen(QPen(color, 1))
        painter.drawPoints(QPolygonF(dots))

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        blank_canvas = self.itemAt(event.position().toPoint()) is None
        if event.button() == Qt.MouseButton.MiddleButton or (
                event.button() == Qt.MouseButton.LeftButton and blank_canvas):
            self._panning = True
            self._pan_last = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @staticmethod
    def _add_rounded_rect(scene: QGraphicsScene, rect: QRectF, radius: float,
                          pen: QPen, brush: QBrush) -> QGraphicsPathItem:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        item.setBrush(brush)
        scene.addItem(item)
        return item

    def set_diagram(self, spec: dict, selected_node: str | None = None,
                    selected_edge: int | None = None) -> None:
        chart = self.build_fn(spec)
        self._palette = chart.theme
        self.setBackgroundBrush(QColor(self._palette["background"]))
        scene = self.scene()
        scene.clear()
        self._node_items.clear()

        # Frames
        for frame in chart.frames:
            x, y, w, h = chart._frame_bounds(frame)
            pen = QPen(QColor(self._palette["frame"]), 1.4, Qt.PenStyle.DashLine)
            rect = self._add_rounded_rect(scene, QRectF(x, y, w, h), 12, pen,
                                          QBrush(Qt.BrushStyle.NoBrush))
            rect.setZValue(-3)
            label = QGraphicsSimpleTextItem(frame["label"])
            label.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            label.setBrush(QColor(self._palette["muted"]))
            label.setPos(x + 15, y + float(frame.get("label_dy", 24)) - 12)
            label.setZValue(-2)
            scene.addItem(label)

        # Connections and arrowheads
        routes: list[tuple[dict, list[tuple[float, float]]]] = []
        arrow_heads: list[QPolygonF] = []
        for edge_index, edge in enumerate(chart.edges):
            route = chart._edge_route(edge)
            routes.append((edge, route))
            path = QPainterPath(QPointF(*route[0]))
            for point in route[1:]:
                path.lineTo(QPointF(*point))
            route_color = self._palette["accent"] if edge_index == selected_edge else self._palette["muted"]
            hit = QGraphicsPathItem(path)
            hit_pen = QPen(QColor(0, 0, 0, 0), 14)
            hit.setPen(hit_pen)
            hit.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            hit.setData(0, "diagram-edge")
            hit.setData(1, edge_index)
            hit.setZValue(-0.5)
            scene.addItem(hit)

            pen = QPen(QColor(route_color), 2.4 if edge_index == selected_edge else 1.7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if edge.get("dashed"):
                pen.setStyle(Qt.PenStyle.DashLine)
            line = QGraphicsPathItem(path)
            line.setPen(pen)
            line.setZValue(-1)
            scene.addItem(line)
            if len(route) > 1:
                (x1, y1), (x2, y2) = route[-2], route[-1]
                angle = math.atan2(y2 - y1, x2 - x1)
                size, wing = 14, 6
                bx, by = x2 - size * math.cos(angle), y2 - size * math.sin(angle)
                points = QPolygonF([QPointF(x2, y2),
                                    QPointF(bx + wing * math.sin(angle),
                                            by - wing * math.cos(angle)),
                                    QPointF(bx - wing * math.sin(angle),
                                            by + wing * math.cos(angle))])
                arrow_heads.append(points)

        # Nodes
        for node in chart.nodes.values():
            item = NodeItem(node, self._palette)
            item.clicked.connect(self.nodeClicked.emit)
            item.moved.connect(self.nodeMoved.emit)
            item.setSelected(node.id == selected_node)
            self._node_items[node.id] = item
            scene.addItem(item)

        for points in arrow_heads:
            arrow = QGraphicsPolygonItem(points)
            arrow.setPen(QPen(QColor(self._palette["background"]), 0.7))
            arrow.setBrush(QColor(self._palette["accent"]))
            arrow.setZValue(3)
            scene.addItem(arrow)

        # Connector labels
        for edge, route in routes:
            label_text = edge.get("label")
            if not label_text:
                continue
            fraction = {"start": 0.2, "mid": 0.5, "end": 0.6}.get(edge.get("near", "mid"), 0.5)
            x, y = chart._point_on_route(route, fraction)
            if edge.get("at") is not None:
                x, y = edge["at"]
            x += float(edge.get("dx", 0) or 0)
            y += float(edge.get("dy", 0) or 0)
            label = QGraphicsSimpleTextItem(str(label_text))
            label.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            label.setBrush(QColor(self._palette["text"]))
            label_rect = label.boundingRect()
            anchor = edge.get("anchor", "middle")
            if anchor == "start":
                x_pos = x
            elif anchor == "end":
                x_pos = x - label_rect.width()
            else:
                x_pos = x - label_rect.width() / 2
            y_pos = y - label_rect.height() / 2
            bg = self._add_rounded_rect(scene, QRectF(x_pos - 6, y_pos - 3,
                label_rect.width() + 12, label_rect.height() + 6), 6,
                QPen(Qt.PenStyle.NoPen), QBrush(QColor(self._palette["background"])))
            bg.setZValue(3)
            label.setPos(x_pos, y_pos)
            label.setZValue(4)
            scene.addItem(label)

        # Diagram legend
        if chart.legend_items:
            bounds = scene.itemsBoundingRect()
            start_x, panel_top = bounds.left(), bounds.bottom() + 32
            panel_width = max(380, bounds.width())
            padding = 16
            gap = 8
            x = start_x + padding
            y = panel_top + 48
            row_height = 32
            legend_positions: list[tuple[float, float, float, str, str]] = []
            legend_font = QFont("Segoe UI", 9)
            metrics = QFontMetricsF(legend_font)
            for style, text in chart.legend_items:
                item_width = min(panel_width - 2 * padding,
                                 metrics.horizontalAdvance(text) + 52)
                if x + item_width > start_x + panel_width - padding:
                    x = start_x + padding
                    y += row_height + gap
                legend_positions.append((x, y, item_width, style, text))
                x += item_width + gap
            panel_height = (y - panel_top) + row_height + padding
            panel = self._add_rounded_rect(scene,
                QRectF(start_x, panel_top, panel_width, panel_height), 13,
                QPen(QColor(self._palette["border"]), 1),
                QBrush(QColor(self._palette["panel"])))
            panel.setZValue(-4)
            title = QGraphicsSimpleTextItem("LEGENDA DO FLUXO")
            title.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            title.setBrush(QColor(self._palette["muted"]))
            title.setPos(start_x + padding, panel_top + 14)
            title.setZValue(1)
            scene.addItem(title)
            for x, y, item_width, style, text in legend_positions:
                fill, stroke = chart._node_style(style if style != "frame" else "normal")
                card = self._add_rounded_rect(scene,
                    QRectF(x, y, item_width, row_height), 9,
                    QPen(QColor(self._palette["border"]), 0.8),
                    QBrush(QColor(self._palette["background"])))
                card.setZValue(-2)
                if style == "frame":
                    swatch = self._add_rounded_rect(scene, QRectF(x + 10, y + 10, 20, 12), 4,
                        QPen(QColor(self._palette["frame"]), 1.2, Qt.PenStyle.DashLine),
                        QBrush(Qt.BrushStyle.NoBrush))
                else:
                    swatch = self._add_rounded_rect(scene, QRectF(x + 10, y + 10, 20, 12), 4,
                                                    QPen(QColor(stroke), 1), QBrush(QColor(fill)))
                swatch.setZValue(1)
                item = QGraphicsSimpleTextItem(text)
                item.setFont(legend_font)
                item.setBrush(QColor(self._palette["text"]))
                item.setPos(x + 39, y + 7)
                item.setZValue(1)
                scene.addItem(item)

        rect = scene.itemsBoundingRect().adjusted(-55, -55, 55, 55)
        if rect.isNull() or rect.width() < 100 or rect.height() < 100:
            rect = QRectF(0, 0, 800, 600)
        scene.setSceneRect(rect)
        self.viewport().update()

    def _scene_selection_changed(self) -> None:
        for item in self.scene().selectedItems():
            if item.data(0) == "diagram-edge":
                self.edgeClicked.emit(int(item.data(1)))
                return

    def select_node(self, node_id: str | None) -> None:
        for key, item in self._node_items.items():
            item.setSelected(key == node_id)

    def select_nodes(self, node_ids: set[str]) -> None:
        for key, item in self._node_items.items():
            item.setSelected(key in node_ids)

    def fit_diagram(self) -> None:
        if not self.scene().sceneRect().isNull():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def fit_width(self) -> None:
        rect = self.scene().sceneRect()
        if rect.isNull() or rect.width() <= 0:
            return
        self.resetTransform()
        factor = min(1.1, max(0.2, (self.viewport().width() - 64) / rect.width()))
        self.scale(factor, factor)
        visible_height = self.viewport().height() / factor
        self.centerOn(rect.center().x(), rect.top() + visible_height / 2)

    def zoom(self, factor: float) -> None:
        self.scale(factor, factor)


class FlowEditorWindow(QMainWindow):
    def __init__(self, path: Path, callbacks: dict[str, Callable]):
        super().__init__()
        self.callbacks = callbacks
        self.example_path: Path | None = callbacks.get("example_path")
        self.path: Path | None = path if path.exists() else None
        self.is_example = self._same_path(self.path, self.example_path)
        self.spec = callbacks["load_spec"](path) if path.exists() else callbacks["blank_spec"]()
        self.spec.setdefault("meta", {})
        self.spec.setdefault("nodes", [])
        self.spec.setdefault("edges", [])
        self.spec.setdefault("frames", [])
        self.spec.setdefault("legend", [])
        self.selected_node: str | None = None
        self.selected_edge: int | None = None
        self.connect_mode = False
        self.connect_source: str | None = None
        self.merge_source_mode = False
        self.merge_destination_mode = False
        self.merge_sources: set[str] = set()
        self.dirty = False
        self._loading_form = False
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self._history_checkpoint = copy.deepcopy(self.spec)
        self._edit_session: tuple | None = None
        self._saved_snapshot = None if self.path is None else copy.deepcopy(self.spec)
        self.dirty = self.path is None

        self.setWindowTitle(f"Fluxo Studio · {self.path.name if self.path else 'Novo fluxo'}")
        self.resize(1480, 920)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(APP_QSS)
        self._build_ui()
        self._set_form_values()
        self._refresh_graph()
        self._sync_dirty_state()
        self._sync_history_buttons()
        QTimer.singleShot(160, self.view.fit_width)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 12)
        outer.setSpacing(12)

        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(16, 10, 14, 10)
        brand = QLabel("FLUXO STUDIO")
        brand.setObjectName("brand")
        top.addWidget(brand)
        top.addSpacing(10)
        self.new_button = QPushButton("Novo")
        self.new_button.setToolTip("Criar um fluxograma vazio · Ctrl+N")
        self.new_button.clicked.connect(self.new_flow)
        top.addWidget(self.new_button)
        self.open_button = QPushButton("Abrir")
        self.open_button.setToolTip("Abrir um fluxograma salvo · Ctrl+O")
        self.open_button.clicked.connect(self.open_flow)
        top.addWidget(self.open_button)
        self.example_button = QPushButton("Abrir exemplo")
        self.example_button.setToolTip("Carregar o fluxograma de exemplo incluído")
        self.example_button.clicked.connect(self.open_example)
        top.addWidget(self.example_button)
        self.path_label = QLabel()
        self.path_label.setObjectName("pathLabel")
        top.addWidget(self.path_label, 1)
        self.undo_button = QPushButton("Desfazer")
        self.undo_button.setObjectName("historyButton")
        self.undo_button.setToolTip("Desfazer · Ctrl+Z")
        self.undo_button.clicked.connect(self.undo)
        top.addWidget(self.undo_button)
        self.redo_button = QPushButton("Refazer")
        self.redo_button.setObjectName("historyButton")
        self.redo_button.setToolTip("Refazer · Ctrl+Y")
        self.redo_button.clicked.connect(self.redo)
        top.addWidget(self.redo_button)
        self.status_label = QLabel("Salvo")
        self.status_label.setObjectName("statusSaved")
        top.addWidget(self.status_label)
        self.save_button = QPushButton("Salvar")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        top.addWidget(self.save_button)
        self.save_as_button = QPushButton("Salvar como")
        self.save_as_button.setToolTip("Salvar uma cópia com outro nome · Ctrl+Shift+S")
        self.save_as_button.clicked.connect(self.save_as)
        top.addWidget(self.save_as_button)
        pdf_button = QPushButton("Exportar PDF")
        pdf_button.clicked.connect(lambda: self.export_diagram("pdf"))
        top.addWidget(pdf_button)
        svg_button = QPushButton("Exportar SVG")
        svg_button.clicked.connect(lambda: self.export_diagram("svg"))
        top.addWidget(svg_button)
        outer.addWidget(topbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        header = QFrame()
        header.setObjectName("canvasHeader")
        hbox = QVBoxLayout(header)
        hbox.setContentsMargins(18, 12, 18, 12)
        self.diagram_title = QLabel()
        self.diagram_title.setObjectName("pageTitle")
        self.diagram_description = QLabel()
        self.diagram_description.setObjectName("muted")
        self.diagram_description.setWordWrap(True)
        hbox.addWidget(self.diagram_title)
        hbox.addWidget(self.diagram_description)
        left_layout.addWidget(header)

        toolbar = QFrame()
        toolbar.setObjectName("canvasToolbar")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(6)
        toolrow = QHBoxLayout()
        toolrow.setSpacing(7)
        toolbar_layout.addLayout(toolrow)
        add_button = QPushButton("+  Nova etapa")
        add_button.setObjectName("accent")
        add_button.clicked.connect(self.add_node)
        toolrow.addWidget(add_button)
        decision_button = QPushButton("Nova decisão")
        decision_button.setToolTip("Criar uma etapa de decisão em formato de losango")
        decision_button.clicked.connect(self.add_decision)
        toolrow.addWidget(decision_button)
        route_label = QLabel("Saída:")
        route_label.setObjectName("sectionHint")
        toolrow.addWidget(route_label)
        self.connection_label_combo = QComboBox()
        self.connection_label_combo.addItem("Sem rótulo", "")
        self.connection_label_combo.addItem("Sim", "Sim")
        self.connection_label_combo.addItem("Não", "Não")
        self.connection_label_combo.setToolTip("Rótulo a exibir na nova seta")
        self.connection_label_combo.setMaximumWidth(120)
        toolrow.addWidget(self.connection_label_combo)
        self.connect_button = QPushButton("Conectar etapas")
        self.connect_button.setObjectName("accent")
        self.connect_button.setCheckable(True)
        self.connect_button.setToolTip(
            "Clique numa origem e continue clicando em destinos. Em sequência, cada destino vira a próxima origem; use Esc para terminar.")
        self.connect_button.clicked.connect(self.toggle_connect_mode)
        toolrow.addWidget(self.connect_button)
        self.keep_connection_source = QCheckBox("Manter origem")
        self.keep_connection_source.setToolTip(
            "Ativado: conecta vários destinos ao mesmo bloco. Desativado: cada destino vira a próxima origem.")
        toolrow.addWidget(self.keep_connection_source)
        self.merge_button = QPushButton("Unir caminhos")
        self.merge_button.setCheckable(True)
        self.merge_button.setToolTip(
            "Selecione pelo menos duas origens. Depois escolha um bloco existente ou crie um destino novo.")
        self.merge_button.clicked.connect(self._merge_button_clicked)
        toolrow.addWidget(self.merge_button)
        toolrow.addStretch(1)
        viewrow = QHBoxLayout()
        viewrow.setSpacing(7)
        gesture_hint = QLabel("Conexão em sequência: origem → destinos. Marque Manter origem para ramificar.")
        gesture_hint.setObjectName("sectionHint")
        viewrow.addWidget(gesture_hint)
        viewrow.addStretch(1)
        zoom_out = QPushButton("-")
        zoom_out.setToolTip("Diminuir zoom")
        zoom_out.clicked.connect(lambda: self.view.zoom(1 / 1.15))
        zoom_in = QPushButton("+")
        zoom_in.setToolTip("Aumentar zoom")
        zoom_in.clicked.connect(lambda: self.view.zoom(1.15))
        fit = QPushButton("Ajustar à tela")
        fit.clicked.connect(lambda: self.view.fit_diagram())
        viewrow.addWidget(zoom_out)
        viewrow.addWidget(zoom_in)
        viewrow.addWidget(fit)
        toolbar_layout.addLayout(viewrow)
        left_layout.addWidget(toolbar)

        self.view = DiagramView(self.callbacks["build"])
        self.view.nodeClicked.connect(self._node_clicked)
        self.view.nodeMoved.connect(self._node_moved)
        self.view.edgeClicked.connect(self._edge_clicked)
        left_layout.addWidget(self.view, 1)
        splitter.addWidget(left)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(370)
        panel.setMaximumWidth(450)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_root = QWidget()
        forms = QVBoxLayout(form_root)
        forms.setContentsMargins(5, 5, 5, 8)
        forms.setSpacing(8)

        self.meta_group = QGroupBox("Fluxograma")
        meta_form = QFormLayout(self.meta_group)
        self.meta_title = QLineEdit()
        self.meta_eyebrow = QLineEdit()
        self.meta_description = CommitTextEdit()
        self.meta_description.setMaximumHeight(76)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Escuro", "dark")
        self.theme_combo.addItem("Claro", "light")
        meta_form.addRow("Título", self.meta_title)
        meta_form.addRow("Linha auxiliar", self.meta_eyebrow)
        meta_form.addRow("Descrição", self.meta_description)
        meta_form.addRow("Tema", self.theme_combo)
        forms.addWidget(self.meta_group)

        self.defaults_group = QGroupBox("Padrões visuais")
        defaults_form = QFormLayout(self.defaults_group)
        self.default_shape_combo = QComboBox()
        self.default_shape_combo.addItem("Retângulo", "box")
        self.default_shape_combo.addItem("Cápsula", "stadium")
        self.default_shape_combo.addItem("Decisão", "diamond")
        self.default_style_combo = QComboBox()
        for label, value in (("Normal", "normal"), ("Alternativa", "alt"),
                             ("Manual", "manual"), ("Encerrada", "bad")):
            self.default_style_combo.addItem(label, value)
        self.default_edge_combo = QComboBox()
        self.default_edge_combo.addItem("Linha contínua", False)
        self.default_edge_combo.addItem("Tracejada", True)
        defaults_hint = QLabel("Define o visual das próximas etapas e setas. O botão aplica o padrão ao fluxo inteiro.")
        defaults_hint.setObjectName("sectionHint")
        defaults_hint.setWordWrap(True)
        defaults_form.addRow(defaults_hint)
        defaults_form.addRow("Forma de novas etapas", self.default_shape_combo)
        defaults_form.addRow("Estilo de novas etapas", self.default_style_combo)
        defaults_form.addRow("Padrão das novas setas", self.default_edge_combo)
        self.apply_defaults_button = QPushButton("Aplicar a todas as etapas e setas")
        self.apply_defaults_button.setObjectName("accent")
        self.apply_defaults_button.clicked.connect(self.apply_defaults)
        defaults_form.addRow(self.apply_defaults_button)
        forms.addWidget(self.defaults_group)

        self.node_group = QGroupBox("Etapa selecionada")
        node_form = QFormLayout(self.node_group)
        self.node_title = QLineEdit()
        self.node_sub = CommitTextEdit()
        self.node_sub.setMaximumHeight(72)
        self.node_tag = QLineEdit()
        self.shape_combo = QComboBox()
        self.shape_combo.addItem("Retângulo", "box")
        self.shape_combo.addItem("Cápsula", "stadium")
        self.shape_combo.addItem("Decisão", "diamond")
        self.style_combo = QComboBox()
        for label, value in (("Normal", "normal"), ("Alternativa", "alt"),
                             ("Manual", "manual"), ("Encerrada", "bad")):
            self.style_combo.addItem(label, value)
        node_form.addRow("Nome", self.node_title)
        node_form.addRow("Detalhe", self.node_sub)
        node_form.addRow("Etiqueta", self.node_tag)
        node_form.addRow("Forma", self.shape_combo)
        node_form.addRow("Estilo", self.style_combo)
        self.delete_node_button = QPushButton("Excluir etapa")
        self.delete_node_button.setObjectName("danger")
        self.delete_node_button.clicked.connect(self.delete_selected_node)
        node_form.addRow(self.delete_node_button)
        forms.addWidget(self.node_group)

        self.edge_group = QGroupBox("Setas")
        edge_layout = QVBoxLayout(self.edge_group)
        edge_hint = QLabel("Clique numa seta do desenho ou escolha-a na lista para editar pontas e traçado.")
        edge_hint.setObjectName("sectionHint")
        edge_hint.setWordWrap(True)
        edge_layout.addWidget(edge_hint)
        self.edge_list = QListWidget()
        self.edge_list.setMaximumHeight(150)
        self.edge_list.currentRowChanged.connect(self._edge_selected)
        edge_layout.addWidget(self.edge_list)
        edge_form = QFormLayout()
        self.edge_label = QLineEdit()
        self.edge_label.setPlaceholderText("Rótulo da seta (opcional)")
        edge_form.addRow("Rótulo", self.edge_label)
        self.edge_out_combo = QComboBox()
        self.edge_into_combo = QComboBox()
        for combo in (self.edge_out_combo, self.edge_into_combo):
            combo.addItem("Automático", None)
            for label, value in (("Superior", "top"), ("Inferior", "bottom"),
                                 ("Esquerda", "left"), ("Direita", "right")):
                combo.addItem(label, value)
        self.edge_dashed_combo = QComboBox()
        self.edge_dashed_combo.addItem("Contínua", False)
        self.edge_dashed_combo.addItem("Tracejada", True)
        edge_form.addRow("Origem", self.edge_out_combo)
        edge_form.addRow("Destino", self.edge_into_combo)
        edge_form.addRow("Traçado", self.edge_dashed_combo)
        edge_layout.addLayout(edge_form)
        edge_actions = QHBoxLayout()
        self.invert_edge_button = QPushButton("Inverter direção")
        self.invert_edge_button.clicked.connect(self.invert_selected_edge)
        edge_actions.addWidget(self.invert_edge_button)
        self.delete_edge_button = QPushButton("Excluir seta")
        self.delete_edge_button.setObjectName("danger")
        self.delete_edge_button.clicked.connect(self.delete_selected_edge)
        edge_actions.addWidget(self.delete_edge_button)
        edge_layout.addLayout(edge_actions)
        forms.addWidget(self.edge_group)

        self.legend_group = QGroupBox("Legenda")
        legend_layout = QVBoxLayout(self.legend_group)
        legend_hint = QLabel("Descreva o significado das cores ou formas usadas no diagrama.")
        legend_hint.setObjectName("sectionHint")
        legend_hint.setWordWrap(True)
        legend_layout.addWidget(legend_hint)
        self.legend_list = QListWidget()
        self.legend_list.setMaximumHeight(160)
        self.legend_list.currentRowChanged.connect(self._legend_selected)
        legend_layout.addWidget(self.legend_list)
        legend_form = QFormLayout()
        self.legend_style_combo = QComboBox()
        for label, value in (("Etapa normal", "normal"), ("Etapa alternativa", "alt"),
                             ("Análise manual", "manual"), ("Encerrada", "bad"),
                             ("Moldura", "frame")):
            self.legend_style_combo.addItem(label, value)
        self.legend_text = QLineEdit()
        self.legend_text.setPlaceholderText("Ex.: Etapa automática")
        legend_form.addRow("Símbolo", self.legend_style_combo)
        legend_form.addRow("Significado", self.legend_text)
        legend_layout.addLayout(legend_form)
        legend_buttons = QHBoxLayout()
        self.add_legend_button = QPushButton("Adicionar item")
        self.add_legend_button.setObjectName("accent")
        self.update_legend_button = QPushButton("Atualizar")
        self.remove_legend_button = QPushButton("Remover")
        self.add_legend_button.clicked.connect(self.add_legend)
        self.update_legend_button.clicked.connect(self.update_legend)
        self.remove_legend_button.clicked.connect(self.remove_legend)
        legend_buttons.addWidget(self.add_legend_button)
        legend_buttons.addWidget(self.update_legend_button)
        legend_buttons.addWidget(self.remove_legend_button)
        legend_layout.addLayout(legend_buttons)
        forms.addWidget(self.legend_group)
        forms.addStretch(1)

        scroll.setWidget(form_root)
        panel_layout.addWidget(scroll)
        splitter.addWidget(panel)
        splitter.setSizes([1010, 430])
        outer.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Arraste o fundo para mover a tela · arraste etapas para reposicionar · role para zoom", 7000)
        for sequence, handler in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo),
                                  ("Ctrl+Shift+Z", self.redo), ("Ctrl+S", self.save),
                                  ("Ctrl+O", self.open_flow), ("Ctrl+N", self.new_flow),
                                  ("Ctrl+Shift+S", self.save_as), ("Esc", self.cancel_active_modes)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(handler)

        self.meta_title.textEdited.connect(lambda value: self._meta_changed("title", value))
        self.meta_eyebrow.textEdited.connect(lambda value: self._meta_changed("eyebrow", value))
        self.meta_title.editingFinished.connect(self._finish_edit_session)
        self.meta_eyebrow.editingFinished.connect(self._finish_edit_session)
        self.meta_description.textChanged.connect(
            lambda: self._meta_changed("description", self.meta_description.toPlainText()))
        self.meta_description.editingFinished.connect(self._finish_edit_session)
        self.theme_combo.currentIndexChanged.connect(lambda _: self._theme_changed())
        self.default_shape_combo.currentIndexChanged.connect(lambda _: self._default_changed("default_shape", self.default_shape_combo.currentData()))
        self.default_style_combo.currentIndexChanged.connect(lambda _: self._default_changed("default_style", self.default_style_combo.currentData()))
        self.default_edge_combo.currentIndexChanged.connect(lambda _: self._default_changed("default_edge_dashed", self.default_edge_combo.currentData()))
        self.node_title.textEdited.connect(lambda value: self._node_changed("title", value))
        self.node_title.editingFinished.connect(self._finish_edit_session)
        self.node_sub.textChanged.connect(lambda: self._node_changed("sub", self.node_sub.toPlainText()))
        self.node_sub.editingFinished.connect(self._finish_edit_session)
        self.node_tag.textEdited.connect(lambda value: self._node_changed("tag", value))
        self.node_tag.editingFinished.connect(self._finish_edit_session)
        self.shape_combo.currentIndexChanged.connect(lambda _: self._node_changed("shape", self.shape_combo.currentData()))
        self.style_combo.currentIndexChanged.connect(lambda _: self._node_changed("style", self.style_combo.currentData()))
        self.edge_label.textEdited.connect(self._edge_label_changed)
        self.edge_label.editingFinished.connect(self._finish_edit_session)
        self.edge_out_combo.currentIndexChanged.connect(lambda _: self._edge_option_changed("out", self.edge_out_combo.currentData()))
        self.edge_into_combo.currentIndexChanged.connect(lambda _: self._edge_option_changed("into", self.edge_into_combo.currentData()))
        self.edge_dashed_combo.currentIndexChanged.connect(lambda _: self._edge_option_changed("dashed", self.edge_dashed_combo.currentData()))

    def _set_form_values(self) -> None:
        self._loading_form = True
        meta = self.spec.setdefault("meta", {})
        self.meta_title.setText(meta.get("title", ""))
        self.meta_eyebrow.setText(meta.get("eyebrow", ""))
        self.meta_description.setPlainText(meta.get("description", ""))
        index = self.theme_combo.findData(meta.get("theme", "dark"))
        self.theme_combo.setCurrentIndex(max(0, index))
        self.default_shape_combo.setCurrentIndex(max(0, self.default_shape_combo.findData(
            meta.get("default_shape", "box"))))
        self.default_style_combo.setCurrentIndex(max(0, self.default_style_combo.findData(
            meta.get("default_style", "normal"))))
        self.default_edge_combo.setCurrentIndex(max(0, self.default_edge_combo.findData(
            meta.get("default_edge_dashed", False))))
        self._refresh_edge_list()
        self._refresh_legend_list()
        self._set_node_fields()
        self._set_edge_field()
        self._loading_form = False
        self._update_header()

    def _update_header(self) -> None:
        meta = self.spec.get("meta", {})
        self.diagram_title.setText(meta.get("title") or "Fluxograma sem título")
        self.diagram_description.setText(meta.get("description", ""))
        if hasattr(self, "path_label"):
            if self.path is None:
                self.path_label.setText("Novo fluxo · ainda não salvo")
                self.path_label.setToolTip("Salve para adicionar este fluxo à pasta Meus fluxos")
            elif self.is_example:
                self.path_label.setText(f"Exemplo · {self.path.name}")
                self.path_label.setToolTip(f"Modelo incluído: {self.path}")
            else:
                self.path_label.setText(self.path.name)
                self.path_label.setToolTip(str(self.path))

    @staticmethod
    def _same_path(first: Path | None, second: Path | None) -> bool:
        if first is None or second is None:
            return False
        try:
            return first.resolve() == second.resolve()
        except OSError:
            return str(first).casefold() == str(second).casefold()

    @staticmethod
    def _flows_directory() -> Path:
        return Path.home() / "Documents" / "Fluxo Studio"

    def _confirm_switch(self) -> bool:
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Alterações não salvas")
        box.setText("Salvar as alterações antes de continuar?")
        save_button = box.addButton("Salvar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == cancel_button:
            return False
        if clicked == save_button:
            return self.save()
        return True

    def _load_flow(self, path: Path, is_example: bool = False) -> None:
        try:
            new_spec = self.callbacks["load_spec"](path)
            self.callbacks["validate"](new_spec)
        except Exception as exc:
            QMessageBox.critical(self, "Não foi possível abrir o fluxo", str(exc))
            return
        self.cancel_active_modes()
        self.path = path
        self.is_example = is_example or self._same_path(path, self.example_path)
        self.spec = new_spec
        self.spec.setdefault("meta", {})
        self.spec.setdefault("nodes", [])
        self.spec.setdefault("edges", [])
        self.spec.setdefault("frames", [])
        self.spec.setdefault("legend", [])
        self.selected_node = None
        self.selected_edge = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._history_checkpoint = copy.deepcopy(self.spec)
        self._saved_snapshot = copy.deepcopy(self.spec)
        self.dirty = False
        self._finish_edit_session()
        self._set_form_values()
        self._refresh_graph()
        self._sync_dirty_state()
        self._sync_history_buttons()
        QTimer.singleShot(80, self.view.fit_width)
        self.statusBar().showMessage(f"Fluxo aberto: {path}", 4500)

    def new_flow(self) -> None:
        if not self._confirm_switch():
            return
        self.cancel_active_modes()
        self.path = None
        self.is_example = False
        self.spec = self.callbacks["blank_spec"]()
        self.selected_node = None
        self.selected_edge = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._history_checkpoint = copy.deepcopy(self.spec)
        self._saved_snapshot = None
        self.dirty = True
        self._finish_edit_session()
        self._set_form_values()
        self._refresh_graph()
        self._sync_dirty_state()
        self._sync_history_buttons()
        QTimer.singleShot(80, self.view.fit_width)
        self.statusBar().showMessage("Fluxo em branco criado. Adicione etapas e conecte-as.", 5000)

    def open_flow(self) -> None:
        initial_dir = self.path.parent if self.path else self._flows_directory()
        filename, _ = QFileDialog.getOpenFileName(self, "Abrir fluxograma", str(initial_dir),
                                                  "Fluxogramas (*.json);;Todos os arquivos (*.*)")
        if filename and self._confirm_switch():
            self._load_flow(Path(filename))

    def open_example(self) -> None:
        if not self.example_path or not self.example_path.exists():
            QMessageBox.information(self, "Exemplo indisponível", "O arquivo de exemplo não foi encontrado.")
            return
        if not self._confirm_switch():
            return
        self._load_flow(self.example_path, is_example=True)

    def save_as(self) -> bool:
        flow_dir = self._flows_directory()
        flow_dir.mkdir(parents=True, exist_ok=True)
        default_name = (self.path.stem if self.path and not self.is_example else "Meu fluxo") + ".json"
        default_path = flow_dir / default_name
        filename, _ = QFileDialog.getSaveFileName(self, "Salvar fluxograma como", str(default_path),
                                                  "Fluxogramas (*.json)")
        if not filename:
            return False
        target = Path(filename)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        return self._save_to(target)

    def _save_to(self, target: Path) -> bool:
        try:
            self.callbacks["validate"](self.spec)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.callbacks["save_spec"](self.spec, target)
        except Exception as exc:
            QMessageBox.critical(self, "Não foi possível salvar", str(exc))
            return False
        self.path = target
        self.is_example = False
        self._finish_edit_session()
        self._saved_snapshot = copy.deepcopy(self.spec)
        self._sync_dirty_state()
        self._update_header()
        self.statusBar().showMessage(f"Salvo em {target}", 4500)
        return True

    def _refresh_graph(self) -> None:
        self._update_header()
        self.view.set_diagram(self.spec, self.selected_node, self.selected_edge)

    def _refresh_inspector(self) -> None:
        self._loading_form = True
        self._set_node_fields()
        self._refresh_edge_list()
        self._set_edge_field()
        self._refresh_legend_list()
        self._loading_form = False

    def _set_node_fields(self) -> None:
        node = next((n for n in self.spec["nodes"] if n.get("id") == self.selected_node), None)
        self.node_group.setVisible(node is not None)
        if node is None:
            self.node_title.clear()
            self.node_sub.clear()
            self.node_tag.clear()
            return
        self.node_title.setText(node.get("title", ""))
        self.node_sub.setPlainText(node.get("sub", ""))
        self.node_tag.setText(node.get("tag", ""))
        self.shape_combo.setCurrentIndex(max(0, self.shape_combo.findData(node.get("shape", "box"))))
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(node.get("style", "normal"))))

    def _refresh_edge_list(self) -> None:
        self.edge_list.blockSignals(True)
        self.edge_list.clear()
        for edge in self.spec["edges"]:
            src = edge.get("src", "?")
            dst = edge.get("dst", "?")
            label = edge.get("label")
            self.edge_list.addItem(f"{src}  →  {dst}" + (f"   ·   {label}" if label else ""))
        if self.selected_edge is not None and self.selected_edge < self.edge_list.count():
            self.edge_list.setCurrentRow(self.selected_edge)
        elif self.edge_list.count():
            self.selected_edge = None
        self.edge_list.blockSignals(False)
        self.edge_group.setVisible(self.edge_list.count() > 0 or bool(self.spec["nodes"]))

    def _set_edge_field(self) -> None:
        edge = None
        if self.selected_edge is not None and self.selected_edge < len(self.spec["edges"]):
            edge = self.spec["edges"][self.selected_edge]
        self.edge_label.setEnabled(edge is not None)
        self.delete_edge_button.setEnabled(edge is not None)
        self.invert_edge_button.setEnabled(edge is not None)
        self.edge_out_combo.setEnabled(edge is not None)
        self.edge_into_combo.setEnabled(edge is not None)
        self.edge_dashed_combo.setEnabled(edge is not None)
        self.edge_label.setText(edge.get("label", "") if edge else "")
        self.edge_out_combo.setCurrentIndex(max(0, self.edge_out_combo.findData(edge.get("out") if edge else None)))
        self.edge_into_combo.setCurrentIndex(max(0, self.edge_into_combo.findData(edge.get("into") if edge else None)))
        self.edge_dashed_combo.setCurrentIndex(max(0, self.edge_dashed_combo.findData(
            edge.get("dashed", False) if edge else False)))

    def _refresh_legend_list(self) -> None:
        selected_row = self.legend_list.currentRow()
        self.legend_list.blockSignals(True)
        self.legend_list.clear()
        for style, label in self.spec.get("legend", []):
            friendly = self._legend_style_name(style)
            item = QListWidgetItem(self._legend_icon(style), f"{friendly}   ·   {label}")
            item.setToolTip(f"{friendly}: {label}")
            self.legend_list.addItem(item)
        if 0 <= selected_row < self.legend_list.count():
            self.legend_list.setCurrentRow(selected_row)
        self.legend_list.blockSignals(False)
        self._legend_selected(self.legend_list.currentRow())

    @staticmethod
    def _legend_style_name(style: str) -> str:
        return {"normal": "Etapa normal", "alt": "Etapa alternativa",
                "manual": "Análise manual", "bad": "Encerrada", "frame": "Moldura"}.get(style, style)

    def _legend_icon(self, style: str) -> QIcon:
        palette = (LIGHT if self.spec.get("meta", {}).get("theme") == "light" else DARK)
        fills = {"alt": palette["alt_fill"], "bad": palette["bad_fill"],
                 "manual": palette["manual_fill"]}
        strokes = {"alt": palette["alt_border"], "bad": palette["bad_border"],
                   "manual": palette["manual_border"]}
        image = QPixmap(28, 22)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if style == "frame":
            pen = QPen(QColor(palette["frame"]), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(3, 4, 22, 14), 4, 4)
        else:
            painter.setPen(QPen(QColor(strokes.get(style, palette["border"])), 1.2))
            painter.setBrush(QColor(fills.get(style, palette["panel"])))
            painter.drawRoundedRect(QRectF(3, 4, 22, 14), 5, 5)
        painter.end()
        return QIcon(image)

    def _record_action(self) -> None:
        self._finish_edit_session()
        self.undo_stack.append(copy.deepcopy(self.spec))
        del self.undo_stack[:-100]
        self.redo_stack.clear()
        self._history_checkpoint = copy.deepcopy(self.spec)
        self._sync_history_buttons()

    def _record_text_edit(self, key: tuple) -> None:
        if self._edit_session == key:
            return
        self._finish_edit_session()
        self.undo_stack.append(copy.deepcopy(self._history_checkpoint))
        del self.undo_stack[:-100]
        self.redo_stack.clear()
        self._edit_session = key
        self._sync_history_buttons()

    def _finish_edit_session(self) -> None:
        self._edit_session = None
        self._history_checkpoint = copy.deepcopy(self.spec)

    def _sync_history_buttons(self) -> None:
        if hasattr(self, "undo_button"):
            self.undo_button.setEnabled(bool(self.undo_stack))
            self.redo_button.setEnabled(bool(self.redo_stack))

    def _sync_dirty_state(self) -> None:
        self.dirty = self.spec != self._saved_snapshot
        self.status_label.setText("Alterações não salvas" if self.dirty else "Salvo")
        self.status_label.setObjectName("statusDirty" if self.dirty else "statusSaved")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        prefix = "● " if self.dirty else ""
        name = self.path.name if self.path else "Novo fluxo"
        self.setWindowTitle(f"{prefix}Fluxo Studio · {name}")

    def _meta_changed(self, key: str, value: str) -> None:
        if self._loading_form:
            return
        self._record_text_edit(("meta", key))
        self.spec.setdefault("meta", {})[key] = value
        self._changed(redraw=True)

    def _theme_changed(self) -> None:
        if self._loading_form:
            return
        self._record_action()
        self.spec.setdefault("meta", {})["theme"] = self.theme_combo.currentData()
        self._refresh_legend_list()
        self._changed(redraw=True)

    def _default_changed(self, key: str, value: Any) -> None:
        if self._loading_form:
            return
        self._record_action()
        self.spec.setdefault("meta", {})[key] = value
        self._changed()

    def _node_changed(self, key: str, value: Any) -> None:
        if self._loading_form or not self.selected_node:
            return
        node = next((n for n in self.spec["nodes"] if n.get("id") == self.selected_node), None)
        if node is None:
            return
        if key in ("title", "sub", "tag"):
            self._record_text_edit(("node", self.selected_node, key))
        else:
            self._record_action()
        if key in ("sub", "tag") and not value:
            node.pop(key, None)
        else:
            node[key] = value
        self._changed(redraw=True)

    def _edge_label_changed(self, value: str) -> None:
        if self._loading_form or self.selected_edge is None or self.selected_edge >= len(self.spec["edges"]):
            return
        self._record_text_edit(("edge", self.selected_edge, "label"))
        edge = self.spec["edges"][self.selected_edge]
        if value:
            edge["label"] = value
        else:
            edge.pop("label", None)
        self._changed(redraw=True)
        item = self.edge_list.item(self.selected_edge)
        if item is not None:
            item.setText(f"{edge['src']}  →  {edge['dst']}" + (f"   ·   {value}" if value else ""))

    def _edge_option_changed(self, key: str, value: Any) -> None:
        if self._loading_form or self.selected_edge is None or self.selected_edge >= len(self.spec["edges"]):
            return
        self._record_action()
        edge = self.spec["edges"][self.selected_edge]
        if value is None or (key == "dashed" and value is False):
            edge.pop(key, None)
        else:
            edge[key] = value
        self._changed(redraw=True)

    def _changed(self, redraw: bool = False, refresh_edges: bool = False) -> None:
        self._history_checkpoint = copy.deepcopy(self.spec)
        self._sync_dirty_state()
        if refresh_edges:
            self._loading_form = True
            self._refresh_edge_list()
            self._set_edge_field()
            self._loading_form = False
        if redraw:
            self._refresh_graph()

    def _node_clicked(self, node_id: str) -> None:
        if self.merge_source_mode:
            if node_id in self.merge_sources:
                self.merge_sources.remove(node_id)
            else:
                self.merge_sources.add(node_id)
            self.selected_node = None
            self.selected_edge = None
            self.view.select_nodes(self.merge_sources)
            self.merge_button.setText(
                f"Selecionar destino ({len(self.merge_sources)})" if len(self.merge_sources) >= 2
                else f"Selecionar origens ({len(self.merge_sources)})")
            self.statusBar().showMessage(
                f"{len(self.merge_sources)} origem(ns) selecionada(s). Selecione mais blocos; com duas ou mais, "
                "clique em 'Selecionar destino' para escolher onde os caminhos se encontram.")
            return
        if self.merge_destination_mode:
            if node_id in self.merge_sources:
                self.statusBar().showMessage("O destino precisa ser diferente dos blocos de origem.", 3500)
                return
            self._connect_merge_to_existing_node(node_id)
            return
        if self.connect_mode:
            if self.connect_source is None:
                self.connect_source = node_id
                self.selected_node = node_id
                self.selected_edge = None
                self.view.select_node(node_id)
                self._refresh_inspector()
                self.statusBar().showMessage(
                    f"Origem: {node_id}. Clique nos destinos em sequência; pressione Esc para encerrar.")
                return
            src = self.connect_source
            if src == node_id:
                self.statusBar().showMessage("Escolha um destino diferente da origem.", 3500)
                return
            label = self.connection_label_combo.currentData()
            duplicate = any(edge.get("src") == src and edge.get("dst") == node_id
                            and edge.get("label", "") == label for edge in self.spec["edges"])
            if duplicate:
                self.statusBar().showMessage("Essa conexão já existe com o mesmo rótulo.", 3500)
                return
            self._record_action()
            edge = {"src": src, "dst": node_id}
            if label:
                edge["label"] = label
            if self.spec.get("meta", {}).get("default_edge_dashed"):
                edge["dashed"] = True
            self.spec["edges"].append(edge)
            source_spec = next((item for item in self.spec["nodes"] if item.get("id") == src), {})
            decision_output = source_spec.get("shape") == "diamond" and label in ("Sim", "Não")
            keep_source = self.keep_connection_source.isChecked() or decision_output
            next_source = src if keep_source else node_id
            if decision_output and label == "Sim":
                self.connection_label_combo.setCurrentIndex(self.connection_label_combo.findData("Não"))
            elif label:
                self.connection_label_combo.setCurrentIndex(0)
            self.connect_source = next_source
            self.selected_node = next_source
            self.selected_edge = None
            self._changed(redraw=True)
            self._refresh_inspector()
            self.connect_button.setText("Finalizar conexões")
            if decision_output and label == "Sim":
                next_hint = "Saída ajustada para Não; selecione o destino dessa ramificação."
            elif keep_source:
                next_hint = "Selecione outro destino para esta origem."
            else:
                next_hint = f"Próxima origem: {node_id}. Selecione o próximo destino."
            self.statusBar().showMessage(f"Conexão criada: {src} → {node_id}. {next_hint} Pressione Esc ou finalize.", 5000)
            return
        self.selected_node = node_id
        self.selected_edge = None
        self.view.select_node(node_id)
        self._refresh_inspector()

    def _node_moved(self, node_id: str, x: float, y: float) -> None:
        node = next((n for n in self.spec["nodes"] if n.get("id") == node_id), None)
        if node is None:
            return
        self._record_action()
        for key in ("below", "above", "right_of", "left_of", "cx", "cy", "x", "y",
                    "gap", "dx", "dy"):
            node.pop(key, None)
        node["x"], node["y"] = round(x, 1), round(y, 1)
        self.selected_node = node_id
        self._changed(redraw=True)
        self._refresh_inspector()

    def _edge_selected(self, row: int) -> None:
        if self._loading_form:
            return
        self.selected_edge = row if row >= 0 else None
        if self.selected_edge is not None:
            self.selected_node = None
            self.view.select_node(None)
        self._loading_form = True
        self._set_edge_field()
        self._set_node_fields()
        self._loading_form = False

    def _edge_clicked(self, edge_index: int) -> None:
        if edge_index < 0 or edge_index >= len(self.spec["edges"]):
            return
        self.selected_edge = edge_index
        self.selected_node = None
        self.view.select_node(None)
        self._refresh_graph()
        self._refresh_inspector()
        self.edge_list.setCurrentRow(edge_index)

    def toggle_connect_mode(self, enabled: bool) -> None:
        if enabled and (self.merge_source_mode or self.merge_destination_mode):
            self._cancel_merge_mode()
        self.connect_mode = enabled
        self.connect_source = None
        if enabled and self.selected_node and self.selected_edge is None:
            self.connect_source = self.selected_node
        self.view.viewport().setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.connect_button.setText("Finalizar conexões" if enabled else "Conectar etapas")
        if enabled and self.connect_source:
            label = self.connection_label_combo.currentData()
            suffix = f" com rótulo '{label}'." if label else "."
            self.statusBar().showMessage(
                f"Origem: {self.connect_source}. Clique no destino; depois continue conectando" + suffix, 5000)
        else:
            self.statusBar().showMessage("Clique numa origem e depois selecione os destinos em sequência." if enabled
                                         else "Modo de conexão encerrado", 5000)

    def cancel_active_modes(self) -> None:
        if self.connect_mode:
            self.connect_button.blockSignals(True)
            self.connect_button.setChecked(False)
            self.connect_button.blockSignals(False)
            self.toggle_connect_mode(False)
        if self.merge_source_mode or self.merge_destination_mode:
            self._cancel_merge_mode()

    def _merge_button_clicked(self, checked: bool) -> None:
        if checked:
            if self.merge_destination_mode:
                return
            if self.connect_mode:
                self.connect_button.blockSignals(True)
                self.connect_button.setChecked(False)
                self.connect_button.blockSignals(False)
                self.connect_button.setText("Conectar etapas")
                self.connect_mode = False
                self.connect_source = None
            self.merge_source_mode = True
            self.merge_sources.clear()
            self.selected_node = None
            self.selected_edge = None
            self.view.select_nodes(set())
            self._refresh_inspector()
            self.merge_button.setText("Selecionar origens (0)")
            self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.statusBar().showMessage(
                "Clique em pelo menos dois blocos de origem. Depois escolha um destino comum.", 7000)
            return

        if self.merge_destination_mode:
            self._cancel_merge_mode()
            self.statusBar().showMessage("Junção cancelada.", 3000)
            return
        if not self.merge_source_mode:
            return
        if len(self.merge_sources) < 2:
            self._cancel_merge_mode()
            self.statusBar().showMessage("A junção precisa de pelo menos dois blocos de origem.", 4000)
            return
        self.merge_source_mode = False
        self.merge_destination_mode = True
        self.merge_button.blockSignals(True)
        self.merge_button.setChecked(True)
        self.merge_button.setText("Cancelar união")
        self.merge_button.blockSignals(False)
        self.statusBar().showMessage(
            "Clique no bloco que receberá os caminhos ou em '+ Nova etapa' para criar um destino novo. Esc cancela.", 7000)

    def _cancel_merge_mode(self) -> None:
        self.merge_source_mode = False
        self.merge_destination_mode = False
        self.merge_sources.clear()
        if hasattr(self, "merge_button"):
            self.merge_button.blockSignals(True)
            self.merge_button.setChecked(False)
            self.merge_button.setText("Unir caminhos")
            self.merge_button.blockSignals(False)
        if hasattr(self, "view"):
            self.view.select_nodes(set())
            self.view.viewport().unsetCursor()

    def _connect_merge_to_existing_node(self, target_id: str) -> None:
        sources = sorted(self.merge_sources)
        missing = [source_id for source_id in sources
                   if not any(edge.get("src") == source_id and edge.get("dst") == target_id
                              for edge in self.spec["edges"])]
        if not missing:
            self._cancel_merge_mode()
            self.statusBar().showMessage("Todos os caminhos selecionados já chegam a esse bloco.", 4000)
            return
        self._record_action()
        for source_id in missing:
            edge = {"src": source_id, "dst": target_id}
            if self.spec.get("meta", {}).get("default_edge_dashed"):
                edge["dashed"] = True
            self.spec["edges"].append(edge)
        self._cancel_merge_mode()
        self.selected_node = target_id
        self.selected_edge = None
        self._changed(redraw=True)
        self._refresh_inspector()
        self.statusBar().showMessage(f"{len(missing)} caminho(s) conectado(s) ao bloco '{target_id}'.", 5000)

    def _create_merge_node(self) -> None:
        sources = sorted(self.merge_sources)
        source_items = [self.view._node_items[node_id] for node_id in sources
                        if node_id in self.view._node_items]
        if len(sources) < 2 or len(source_items) != len(sources):
            self._cancel_merge_mode()
            return

        self._record_action()
        existing_ids = {node.get("id") for node in self.spec["nodes"]}
        count = 1
        while f"uniao_{count}" in existing_ids:
            count += 1
        node_id = f"uniao_{count}"
        width, height = 250.0, 78.0
        center_x = sum(item.pos().x() + item.node.w / 2 for item in source_items) / len(source_items)
        top_y = max(item.pos().y() + item.node.h for item in source_items) + 80
        proposed = QRectF(center_x - width / 2, top_y, width, height)
        occupied = [QRectF(item.pos().x() - 22, item.pos().y() - 22,
                           item.node.w + 44, item.node.h + 44)
                    for item in self.view._node_items.values()]
        while any(proposed.intersects(rect) for rect in occupied):
            proposed.translate(0, height + 34)

        node = {"id": node_id, "title": "Caminho unificado",
                "sub": "Continuação do fluxo", "shape": "box", "style": "normal",
                "cx": round(center_x, 1), "y": round(proposed.top(), 1)}
        self.spec["nodes"].append(node)
        for source_id in sources:
            edge = {"src": source_id, "dst": node_id}
            if self.spec.get("meta", {}).get("default_edge_dashed"):
                edge["dashed"] = True
            self.spec["edges"].append(edge)

        self._cancel_merge_mode()
        self.selected_node = node_id
        self.selected_edge = None
        self._changed(redraw=True)
        self._refresh_inspector()
        self.view.ensureVisible(self.view._node_items[node_id], 70, 70)
        self.statusBar().showMessage(
            f"{len(sources)} caminhos unidos em '{node['title']}'. Edite o bloco para definir a próxima etapa.", 6500)

    def add_node(self) -> None:
        if self.merge_destination_mode:
            self._create_merge_node()
            return
        self._add_graph_node("Nova etapa", "", "box", "etapa")

    def add_decision(self) -> None:
        self._add_graph_node("Nova decisão", "Defina a condição", "diamond", "decisao")

    def _add_graph_node(self, title: str, sub: str, shape: str, id_prefix: str) -> None:
        self._record_action()
        ids = {node.get("id") for node in self.spec["nodes"]}
        count = 1
        while f"{id_prefix}_{count}" in ids:
            count += 1
        node: dict[str, Any] = {"id": f"{id_prefix}_{count}", "title": title, "sub": sub}
        node["shape"] = shape if shape == "diamond" else self.spec.get("meta", {}).get("default_shape", "box")
        node["style"] = self.spec.get("meta", {}).get("default_style", "normal")
        if self.spec["nodes"]:
            anchor = next((item for item in self.spec["nodes"]
                           if item.get("id") == self.selected_node), self.spec["nodes"][-1])
            node.update(below=anchor["id"], gap=65 if shape == "diamond" else 55)
        else:
            node.update(cx=400, y=100)
        self.spec["nodes"].append(node)
        self.selected_node = node["id"]
        self.selected_edge = None
        self._changed(redraw=True)
        self._refresh_inspector()
        message = ("Decisão criada. Selecione Sim ou Não em Saída e conecte cada resultado."
                   if shape == "diamond" else "Etapa criada. Arraste-a no diagrama para escolher a posição.")
        self.statusBar().showMessage(message, 5000)

    def delete_selected_node(self) -> None:
        if not self.selected_node:
            return
        node_id = self.selected_node
        answer = QMessageBox.question(self, "Excluir etapa",
            f"Excluir '{node_id}' e as setas ligadas a ela?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._record_action()
        dependents = [n for n in self.spec["nodes"] if any(n.get(key) == node_id
                      for key in ("below", "above", "right_of", "left_of"))]
        for child in dependents:
            for key in ("below", "above", "right_of", "left_of"):
                if child.get(key) == node_id:
                    child.pop(key, None)
            child.setdefault("cx", 400 + len(self.spec["nodes"]) * 20)
            child.setdefault("y", 100 + len(self.spec["nodes"]) * 20)
        self.spec["nodes"] = [n for n in self.spec["nodes"] if n.get("id") != node_id]
        self.spec["edges"] = [e for e in self.spec["edges"] if node_id not in (e.get("src"), e.get("dst"))]
        for frame in self.spec["frames"]:
            frame["around"] = [item for item in frame.get("around", []) if item != node_id]
        self.spec["frames"] = [f for f in self.spec["frames"] if f.get("around")]
        self.selected_node = None
        self.selected_edge = None
        self._changed(redraw=True)
        self._refresh_inspector()

    def delete_selected_edge(self) -> None:
        if self.selected_edge is None or self.selected_edge >= len(self.spec["edges"]):
            return
        self._record_action()
        self.spec["edges"].pop(self.selected_edge)
        self.selected_edge = None
        self._changed(redraw=True)
        self._refresh_inspector()

    def invert_selected_edge(self) -> None:
        if self.selected_edge is None or self.selected_edge >= len(self.spec["edges"]):
            return
        self._record_action()
        edge = self.spec["edges"][self.selected_edge]
        edge["src"], edge["dst"] = edge["dst"], edge["src"]
        edge["out"], edge["into"] = edge.get("into"), edge.get("out")
        if edge["out"] is None:
            edge.pop("out", None)
        if edge["into"] is None:
            edge.pop("into", None)
        if isinstance(edge.get("via"), list):
            edge["via"] = list(reversed(edge["via"]))
        self._changed(redraw=True)
        self._refresh_inspector()

    def add_legend(self) -> None:
        text = self.legend_text.text().strip()
        if not text:
            self.legend_text.setFocus()
            return
        self._record_action()
        self.spec.setdefault("legend", []).append([self.legend_style_combo.currentData(), text])
        self._changed(redraw=True)
        self._refresh_inspector()

    def _legend_selected(self, row: int) -> None:
        valid = 0 <= row < len(self.spec.get("legend", []))
        self.legend_text.setEnabled(valid)
        self.legend_style_combo.setEnabled(valid)
        self.update_legend_button.setEnabled(valid)
        self.remove_legend_button.setEnabled(valid)
        if valid:
            style, label = self.spec["legend"][row]
            self.legend_style_combo.setCurrentIndex(max(0, self.legend_style_combo.findData(style)))
            self.legend_text.setText(label)
        elif hasattr(self, "legend_text"):
            self.legend_text.clear()

    def update_legend(self) -> None:
        row = self.legend_list.currentRow()
        text = self.legend_text.text().strip()
        if row < 0 or row >= len(self.spec.get("legend", [])) or not text:
            return
        self._record_action()
        self.spec["legend"][row] = [self.legend_style_combo.currentData(), text]
        self._changed(redraw=True)
        self._refresh_inspector()

    def remove_legend(self) -> None:
        row = self.legend_list.currentRow()
        if row < 0:
            return
        self._record_action()
        self.spec["legend"].pop(row)
        self._changed(redraw=True)
        self._refresh_inspector()

    def apply_defaults(self) -> None:
        self._record_action()
        meta = self.spec.setdefault("meta", {})
        shape = self.default_shape_combo.currentData()
        style = self.default_style_combo.currentData()
        dashed = bool(self.default_edge_combo.currentData())
        meta["default_shape"] = shape
        meta["default_style"] = style
        meta["default_edge_dashed"] = dashed
        for node in self.spec["nodes"]:
            node["shape"] = shape
            node["style"] = style
        for edge in self.spec["edges"]:
            if dashed:
                edge["dashed"] = True
            else:
                edge.pop("dashed", None)
        self._changed(redraw=True)
        self._refresh_inspector()

    def _restore_history(self, snapshot: dict) -> None:
        self.spec = copy.deepcopy(snapshot)
        node_ids = {node.get("id") for node in self.spec.get("nodes", [])}
        if self.selected_node not in node_ids:
            self.selected_node = None
        if self.selected_edge is not None and self.selected_edge >= len(self.spec.get("edges", [])):
            self.selected_edge = None
        if self.selected_edge is not None:
            self.selected_node = None
        self._finish_edit_session()
        self._set_form_values()
        self._refresh_graph()
        self._sync_dirty_state()
        self._sync_history_buttons()

    def undo(self) -> None:
        self._finish_edit_session()
        if not self.undo_stack:
            self.statusBar().showMessage("Nada para desfazer", 2500)
            return
        self.redo_stack.append(copy.deepcopy(self.spec))
        previous = self.undo_stack.pop()
        self._restore_history(previous)
        self.statusBar().showMessage("Última alteração desfeita · Ctrl+Z", 2500)

    def redo(self) -> None:
        self._finish_edit_session()
        if not self.redo_stack:
            self.statusBar().showMessage("Nada para refazer", 2500)
            return
        self.undo_stack.append(copy.deepcopy(self.spec))
        next_state = self.redo_stack.pop()
        self._restore_history(next_state)
        self.statusBar().showMessage("Alteração refeita · Ctrl+Y", 2500)

    def save(self) -> bool:
        if self.path is None or self.is_example:
            return self.save_as()
        return self._save_to(self.path)

    def export_diagram(self, suffix: str) -> None:
        default = (self.path.with_suffix(f".{suffix}") if self.path
                   else self._flows_directory() / f"Meu fluxo.{suffix}")
        filename, _ = QFileDialog.getSaveFileName(self, f"Exportar {suffix.upper()}", str(default),
            f"{suffix.upper()} (*.{suffix})")
        if not filename:
            return
        try:
            self.callbacks["validate"](self.spec)
            self.callbacks["render"](self.spec, Path(filename))
        except Exception as exc:
            QMessageBox.critical(self, "Falha ao exportar", str(exc))
            return
        self.statusBar().showMessage(f"Arquivo gerado: {filename}", 5000)

    def closeEvent(self, event) -> None:
        if not self.dirty:
            event.accept()
            return
        box = QMessageBox(self)
        box.setWindowTitle("Alterações não salvas")
        box.setText("Deseja salvar as alterações antes de sair?")
        save_button = box.addButton("Salvar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == cancel_button:
            event.ignore()
        elif clicked == save_button and not self.save():
            event.ignore()
        else:
            event.accept()


def launch_gui(path: Path, *, load_spec: Callable, save_spec: Callable,
               blank_spec: Callable, validate: Callable, build: Callable,
               render: Callable, example_path: Path | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    if not QFontDatabase.families() and os.name == "nt":
        font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for font_name in ("segoeui.ttf", "arial.ttf"):
            font_path = font_dir / font_name
            if font_path.exists() and QFontDatabase.addApplicationFont(str(font_path)) >= 0:
                break
    app.setFont(QFont("Segoe UI"))
    callbacks = {"load_spec": load_spec, "save_spec": save_spec,
                 "blank_spec": blank_spec, "validate": validate,
                 "build": build, "render": render, "example_path": example_path}
    try:
        window = FlowEditorWindow(path, callbacks)
    except Exception as exc:
        QMessageBox.critical(None, "Não foi possível abrir o fluxograma", str(exc))
        return 1
    window.show()
    return app.exec()

