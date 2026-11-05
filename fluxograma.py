"""Small, dependency-light flowchart renderer used by :mod:`main`.

The editor stores diagrams as JSON.  This module lays out the nodes, routes
their connectors, and writes SVG or PDF files.  Coordinates use a top-left
origin, which makes the JSON positions and SVG output easy to reason about.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import math
from pathlib import Path
import re
import textwrap
from typing import Any, Iterable


DARK = {
    "background": "#101722",
    "panel": "#172333",
    "text": "#edf3f8",
    "muted": "#a8b7c8",
    "border": "#3d526a",
    "accent": "#65d6bd",
    "alt_fill": "#173b40",
    "alt_border": "#55b9a8",
    "bad_fill": "#432631",
    "bad_border": "#d87983",
    "manual_fill": "#403720",
    "manual_border": "#d7b968",
    "frame": "#6e859c",
}

LIGHT = {
    "background": "#f4f7fa",
    "panel": "#ffffff",
    "text": "#172333",
    "muted": "#536579",
    "border": "#a9b8c7",
    "accent": "#087e72",
    "alt_fill": "#e0f3ef",
    "alt_border": "#168c7e",
    "bad_fill": "#fbe9e9",
    "bad_border": "#bd4a54",
    "manual_fill": "#fff4d8",
    "manual_border": "#aa7d1d",
    "frame": "#788b9d",
}


@dataclass
class Node:
    id: str
    title: str
    sub: str = ""
    x: float = 0
    y: float = 0
    w: float = 240
    h: float = 78
    shape: str = "box"
    style: str = "normal"
    tag: str = ""

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.h


class Flowchart:
    """Build and render a flowchart.

    The public methods intentionally match the API consumed by ``main.py``.
    Node positions are stored in diagram units and may be referenced in
    coordinate expressions such as ``"source.right + 20"``.
    """

    def __init__(self, title: str = "", eyebrow: str = "", description: str = "",
                 theme: dict[str, str] | None = None):
        self.title = title
        self.eyebrow = eyebrow
        self.description = description
        self.theme = dict(theme or DARK)
        self.nodes: dict[str, Node] = {}
        self.edges: list[dict[str, Any]] = []
        self.frames: list[dict[str, Any]] = []
        self.legend_items: list[tuple[str, str]] = []

    def node(self, node_id: str, title: str, sub: str = "", **options: Any) -> Node:
        if node_id in self.nodes:
            raise ValueError(f"nó repetido: {node_id}")

        w = float(options.get("w", self._default_width(title, sub)))
        h = float(options.get("h", self._default_height(title, sub, w)))
        node = Node(node_id, str(title), str(sub or ""), w=w, h=h,
                    shape=options.get("shape", "box"),
                    style=options.get("style", "normal"),
                    tag=str(options.get("tag", "")))

        # Relations set the initial position. Explicit x/cx/y/cy values then
        # override the corresponding axis, allowing the editor's absolute
        # coordinate options to work alongside a relation.
        relation = next((key for key in ("below", "above", "right_of", "left_of")
                         if options.get(key) is not None), None)
        if relation:
            ref_id = options[relation]
            if ref_id not in self.nodes:
                raise ValueError(f"nó de referência '{ref_id}' ainda não foi posicionado")
            ref = self.nodes[ref_id]
            gap = float(options.get("gap", 44))
            if relation == "below":
                node.x, node.y = ref.cx - node.w / 2, ref.bottom + gap
            elif relation == "above":
                node.x, node.y = ref.cx - node.w / 2, ref.top - gap - node.h
            elif relation == "right_of":
                node.x, node.y = ref.right + gap, ref.cy - node.h / 2
            else:
                node.x, node.y = ref.left - gap - node.w, ref.cy - node.h / 2
        elif self.nodes:
            previous = next(reversed(self.nodes.values()))
            node.x, node.y = previous.x, previous.bottom + float(options.get("gap", 44))

        node.x += float(options.get("dx", 0) or 0)
        node.y += float(options.get("dy", 0) or 0)
        if options.get("x") is not None:
            node.x = float(options["x"])
        if options.get("cx") is not None:
            node.x = float(options["cx"]) - node.w / 2
        if options.get("y") is not None:
            node.y = float(options["y"])
        if options.get("cy") is not None:
            node.y = float(options["cy"]) - node.h / 2

        self.nodes[node_id] = node
        return node

    def edge(self, src: str, dst: str, **options: Any) -> dict[str, Any]:
        if src not in self.nodes or dst not in self.nodes:
            raise ValueError(f"seta aponta para nó inexistente: {src} → {dst}")
        edge = {"src": src, "dst": dst, **options}
        self.edges.append(edge)
        return edge

    def frame(self, label: str, around: Iterable[str], pad: tuple[float, float] = (25, 24),
              label_dy: float = 24) -> dict[str, Any]:
        ids = list(around)
        missing = [node_id for node_id in ids if node_id not in self.nodes]
        if missing:
            raise ValueError(f"moldura referencia nó inexistente: {', '.join(missing)}")
        if not ids:
            raise ValueError("moldura precisa conter pelo menos um nó")
        item = {"label": label, "around": ids, "pad": tuple(pad), "label_dy": label_dy}
        self.frames.append(item)
        return item

    def legend(self, *items: tuple[str, str]) -> None:
        self.legend_items.extend((str(style), str(label)) for style, label in items)

    @staticmethod
    def _default_width(title: str, sub: str) -> float:
        longest = max((len(line) for line in (title, sub) if line), default=20)
        return float(max(220, min(330, longest * 7.2 + 42)))

    @classmethod
    def _default_height(cls, title: str, sub: str, width: float) -> float:
        title_lines = cls._wrap(title, max(12, int((width - 36) / 8.0)))
        sub_lines = cls._wrap(sub, max(16, int((width - 36) / 7.0))) if sub else []
        return float(max(64, 26 + len(title_lines) * 18 + len(sub_lines) * 15))

    @staticmethod
    def _wrap(value: str, columns: int) -> list[str]:
        if not value:
            return []
        lines: list[str] = []
        for paragraph in str(value).splitlines() or [str(value)]:
            lines.extend(textwrap.wrap(paragraph, width=max(1, columns),
                                       break_long_words=True, break_on_hyphens=False) or [""])
        return lines

    def _node_style(self, style: str) -> tuple[str, str]:
        if style == "alt":
            return self.theme["alt_fill"], self.theme["alt_border"]
        if style == "bad":
            return self.theme["bad_fill"], self.theme["bad_border"]
        if style == "manual":
            return self.theme["manual_fill"], self.theme["manual_border"]
        return self.theme["panel"], self.theme["border"]

    def _anchor(self, node: Node, value: Any, toward: tuple[float, float]) -> tuple[float, float]:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return float(value[0]), float(value[1])
        if isinstance(value, str):
            return {
                "top": (node.cx, node.top),
                "bottom": (node.cx, node.bottom),
                "left": (node.left, node.cy),
                "right": (node.right, node.cy),
            }[value]
        dx, dy = toward[0] - node.cx, toward[1] - node.cy
        if abs(dx) > abs(dy) * 1.1:
            return (node.right, node.cy) if dx >= 0 else (node.left, node.cy)
        return (node.cx, node.bottom) if dy >= 0 else (node.cx, node.top)

    @staticmethod
    def _clean_points(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
        clean: list[tuple[float, float]] = []
        for point in points:
            p = (float(point[0]), float(point[1]))
            if not clean or math.dist(clean[-1], p) > 0.01:
                clean.append(p)
        return clean

    def _edge_route(self, edge: dict[str, Any]) -> list[tuple[float, float]]:
        src, dst = self.nodes[edge["src"]], self.nodes[edge["dst"]]
        if src is dst:
            start = self._anchor(src, edge.get("out", "right"), (src.right + 40, src.cy))
            end = self._anchor(src, edge.get("into", "top"), (src.cx, src.top - 40))
            return self._clean_points([start, (src.right + 34, src.cy),
                                       (src.right + 34, src.top - 28), end])

        start = self._anchor(src, edge.get("out"), (dst.cx, dst.cy))
        end = self._anchor(dst, edge.get("into"), (src.cx, src.cy))
        via = edge.get("via")
        if via:
            points = [start, *[(float(p[0]), float(p[1])) for p in via], end]
            return self._clean_points(points)

        dx, dy = end[0] - start[0], end[1] - start[1]
        if abs(dx) < 1 or abs(dy) < 1:
            return [start, end]
        if abs(dx) > abs(dy):
            mid_x = start[0] + dx * 0.5
            return self._clean_points([start, (mid_x, start[1]), (mid_x, end[1]), end])
        mid_y = start[1] + dy * 0.5
        return self._clean_points([start, (start[0], mid_y), (end[0], mid_y), end])

    @staticmethod
    def _point_on_route(route: list[tuple[float, float]], fraction: float) -> tuple[float, float]:
        lengths = [math.dist(a, b) for a, b in zip(route, route[1:])]
        total = sum(lengths)
        if total <= 0:
            return route[0]
        target = total * fraction
        for (a, b), length in zip(zip(route, route[1:]), lengths):
            if target <= length:
                t = target / length if length else 0
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            target -= length
        return route[-1]

    def _frame_bounds(self, frame: dict[str, Any]) -> tuple[float, float, float, float]:
        nodes = [self.nodes[node_id] for node_id in frame["around"]]
        px, py = frame.get("pad", (25, 24))
        left = min(node.left for node in nodes) - float(px)
        top = min(node.top for node in nodes) - float(py)
        right = max(node.right for node in nodes) + float(px)
        bottom = max(node.bottom for node in nodes) + float(py)
        return left, top, right - left, bottom - top

    def _layout(self) -> dict[str, Any]:
        if self.nodes:
            left = min(n.left for n in self.nodes.values())
            top = min(n.top for n in self.nodes.values())
            right = max(n.right for n in self.nodes.values())
            bottom = max(n.bottom for n in self.nodes.values())
            for frame in self.frames:
                x, y, w, h = self._frame_bounds(frame)
                left, top = min(left, x), min(top, y)
                right, bottom = max(right, x + w), max(bottom, y + h)
            graph_w, graph_h = max(1, right - left), max(1, bottom - top)
        else:
            left = top = 0
            graph_w, graph_h = 500, 160

        margin = 46.0
        desc_lines = self._wrap(self.description, 88) if self.description else []
        header_h = (16 + (30 if self.title else 0) + len(desc_lines) * 16 + 18
                    if (self.eyebrow or self.title or self.description) else 0)
        min_header_w = 620 if (self.title or self.description) else 0
        legend_text_w = max((len(label) * 7.2 for _, label in self.legend_items), default=0)
        graph_area_w = max(graph_w, min_header_w, min(legend_text_w + 90, 720))
        content_w = graph_area_w + 2 * margin
        content_h = margin + header_h + graph_h
        if self.legend_items:
            panel_w = min(content_w - 2 * margin, 760)
            usable_w = panel_w - 28
            row, x = 0, 0.0
            for _, label in self.legend_items:
                card_w = min(usable_w, max(112, len(label) * 6.5 + 50))
                if x and x + card_w > usable_w:
                    row += 1
                    x = 0
                x += card_w + 8
            panel_h = 49 + (row + 1) * 37
            content_h += 30 + panel_h
        content_h += margin
        graph_x = margin + (graph_area_w - graph_w) / 2 - left
        graph_y = margin + header_h - top
        return {"margin": margin, "header_h": header_h, "desc_lines": desc_lines,
                "graph_left": graph_x, "graph_top": graph_y, "graph_w": graph_w,
                "graph_h": graph_h, "content_w": content_w, "content_h": content_h,
                "legend_top": margin + header_h + graph_h + 30,
                "legend_left": margin + (graph_area_w - min(graph_area_w, 520)) / 2}

    @staticmethod
    def _svg_text(text: str) -> str:
        return html.escape(str(text), quote=True)

    def _svg(self, path: Path, layout: dict[str, Any]) -> None:
        scale_x, scale_y = layout["graph_left"], layout["graph_top"]
        width, height = layout["content_w"], layout["content_h"]
        c = self.theme
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}px" '
               f'height="{height:.0f}px" viewBox="0 0 {width:.2f} {height:.2f}">',
               '<style>text{font-family:Inter,"Segoe UI",Arial,sans-serif}</style>',
               f'<rect width="100%" height="100%" fill="{c["background"]}"/>']

        def p(x: float, y: float) -> tuple[float, float]:
            return x + scale_x, y + scale_y

        # Header
        yy = layout["margin"]
        if self.eyebrow:
            out.append(f'<text x="{layout["margin"]:.1f}" y="{yy+11:.1f}" fill="{c["accent"]}" '
                       'font-size="11" font-weight="700" letter-spacing="1.5">'
                       f'{self._svg_text(self.eyebrow.upper())}</text>')
            yy += 23
        if self.title:
            out.append(f'<text x="{layout["margin"]:.1f}" y="{yy+14:.1f}" fill="{c["text"]}" '
                       'font-size="25" font-weight="700">'
                       f'{self._svg_text(self.title)}</text>')
            yy += 28
        for line in layout["desc_lines"]:
            out.append(f'<text x="{layout["margin"]:.1f}" y="{yy+13:.1f}" fill="{c["muted"]}" '
                       'font-size="12">' + self._svg_text(line) + '</text>')
            yy += 16

        # Group frames sit behind arrows and nodes.
        for frame in self.frames:
            x, y, w, h = self._frame_bounds(frame)
            x, y = p(x, y)
            label_y = y + float(frame.get("label_dy", 24))
            out.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
                       f'rx="12" fill="none" stroke="{c["frame"]}" stroke-width="1.5" '
                       'stroke-dasharray="7 6"/>')
            out.append(f'<text x="{x+15:.2f}" y="{label_y:.2f}" fill="{c["muted"]}" '
                       f'font-size="12" font-weight="600">{self._svg_text(frame["label"])}</text>')

        routes: list[tuple[dict[str, Any], list[tuple[float, float]]]] = []
        arrow_heads: list[list[tuple[float, float]]] = []
        for edge in self.edges:
            route = self._edge_route(edge)
            routes.append((edge, route))
            points = [p(x, y) for x, y in route]
            d = " ".join(("M" if i == 0 else "L") + f" {x:.2f} {y:.2f}" for i, (x, y) in enumerate(points))
            dash = ' stroke-dasharray="6 5"' if edge.get("dashed") else ""
            out.append(f'<path d="{d}" fill="none" stroke="{c["muted"]}" stroke-width="1.8" '
                       f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
            if len(points) > 1:
                (x1, y1), (x2, y2) = points[-2], points[-1]
                angle = math.atan2(y2 - y1, x2 - x1)
                tip_x, tip_y = x2 - 1.5 * math.cos(angle), y2 - 1.5 * math.sin(angle)
                size, wing = 14, 6
                bx, by = tip_x - size * math.cos(angle), tip_y - size * math.sin(angle)
                arrow_heads.append([(tip_x, tip_y),
                    (bx + wing * math.sin(angle), by - wing * math.cos(angle)),
                    (bx - wing * math.sin(angle), by + wing * math.cos(angle))])

        # Nodes and their labels.
        for node in self.nodes.values():
            x, y = p(node.x, node.y)
            fill, stroke = self._node_style(node.style)
            if node.shape == "diamond":
                points = [(x + node.w / 2, y), (x + node.w, y + node.h / 2),
                          (x + node.w / 2, y + node.h), (x, y + node.h / 2)]
                out.append('<polygon points="' + " ".join(f"{a:.2f},{b:.2f}" for a, b in points) +
                           f'" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
            else:
                rx = node.h / 2 if node.shape == "stadium" else 12
                out.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{node.w:.2f}" height="{node.h:.2f}" '
                           f'rx="{rx:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')

            title_lines = self._wrap(node.title, max(12, int((node.w - 34) / 8.2)))
            sub_lines = self._wrap(node.sub, max(14, int((node.w - 34) / 7.1))) if node.sub else []
            tag_h = 16 if node.tag else 0
            total_text_h = len(title_lines) * 17 + len(sub_lines) * 14 + tag_h
            baseline = y + (node.h - total_text_h) / 2 + 13
            for line in title_lines:
                out.append(f'<text x="{x+node.w/2:.2f}" y="{baseline:.2f}" text-anchor="middle" '
                           f'fill="{c["text"]}" font-size="13.5" font-weight="650">'
                           f'{self._svg_text(line)}</text>')
                baseline += 17
            for line in sub_lines:
                out.append(f'<text x="{x+node.w/2:.2f}" y="{baseline:.2f}" text-anchor="middle" '
                           f'fill="{c["muted"]}" font-size="10.5">{self._svg_text(line)}</text>')
                baseline += 14
            if node.tag:
                tag_width = min(node.w - 28, max(54, len(node.tag) * 6.0 + 20))
                tx = x + (node.w - tag_width) / 2
                ty = y + node.h - 21
                out.append(f'<rect x="{tx:.2f}" y="{ty:.2f}" width="{tag_width:.2f}" height="15" '
                           f'rx="7.5" fill="{c["accent"]}" fill-opacity="0.18"/>')
                out.append(f'<text x="{x+node.w/2:.2f}" y="{ty+11:.2f}" text-anchor="middle" '
                           f'fill="{c["accent"]}" font-size="9" font-weight="700">'
                           f'{self._svg_text(node.tag)}</text>')

        for tri in arrow_heads:
            out.append('<polygon points="' + " ".join(f"{x:.2f},{y:.2f}" for x, y in tri) +
                       f'" fill="{c["accent"]}" stroke="{c["background"]}" stroke-width="1.2"/>')

        # Labels are above the connectors, with a small background to keep them readable.
        for edge, route in routes:
            label = edge.get("label")
            if not label:
                continue
            fraction = {"start": 0.2, "mid": 0.5, "end": 0.6}.get(edge.get("near", "mid"), 0.5)
            lx, ly = self._point_on_route(route, fraction)
            if edge.get("at") is not None:
                lx, ly = edge["at"]
            lx += float(edge.get("dx", 0) or 0)
            ly += float(edge.get("dy", 0) or 0)
            lx, ly = p(lx, ly)
            anchor = edge.get("anchor", "middle")
            width = max(36, len(str(label)) * 6.4 + 16)
            rx = lx - width / 2 if anchor == "middle" else (lx if anchor == "start" else lx - width)
            out.append(f'<rect x="{rx:.2f}" y="{ly-12:.2f}" width="{width:.2f}" height="20" '
                       f'rx="7" fill="{c["background"]}"/>')
            text_anchor = {"start": "start", "middle": "middle", "end": "end"}.get(anchor, "middle")
            out.append(f'<text x="{lx:.2f}" y="{ly+2:.2f}" text-anchor="{text_anchor}" '
                       f'fill="{c["text"]}" font-size="10.5" font-weight="600">'
                       f'{self._svg_text(label)}</text>')

        # Legend, below the flow.
        if self.legend_items:
            panel_w = min(layout["content_w"] - 2 * layout["margin"], 760)
            panel_x = (layout["content_w"] - panel_w) / 2
            panel_y = layout["legend_top"]
            inset, gap, row_h = 14.0, 8.0, 30.0
            usable_w = panel_w - 2 * inset
            cards = []
            row = 0
            x = panel_x + inset
            for style, label in self.legend_items:
                card_w = min(usable_w, max(112, len(label) * 6.5 + 50))
                if x + card_w > panel_x + panel_w - inset:
                    row += 1
                    x = panel_x + inset
                cards.append((x, panel_y + 39 + row * (row_h + 7), card_w, style, label))
                x += card_w + gap
            panel_h = 49 + (row + 1) * (row_h + 7)
            out.append(f'<rect x="{panel_x:.1f}" y="{panel_y:.1f}" width="{panel_w:.1f}" '
                       f'height="{panel_h:.1f}" rx="13" fill="{c["panel"]}" '
                       f'stroke="{c["border"]}" stroke-width="1"/>')
            out.append(f'<text x="{panel_x+inset:.1f}" y="{panel_y+22:.1f}" fill="{c["muted"]}" '
                       'font-size="10" font-weight="700" letter-spacing="1.1">LEGENDA DO FLUXO</text>')
            for x, y, card_w, style, label in cards:
                fill, stroke = self._node_style(style if style != "frame" else "normal")
                out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{card_w:.1f}" height="{row_h:.1f}" '
                           f'rx="8" fill="{c["background"]}" stroke="{c["border"]}" stroke-width=".8"/>')
                if style == "frame":
                    out.append(f'<rect x="{x+9:.1f}" y="{y+9:.1f}" width="20" height="12" rx="3" '
                               f'fill="none" stroke="{c["frame"]}" stroke-dasharray="4 3"/>')
                else:
                    out.append(f'<rect x="{x+9:.1f}" y="{y+9:.1f}" width="20" height="12" rx="4" '
                               f'fill="{fill}" stroke="{stroke}"/>')
                out.append(f'<text x="{x+37:.1f}" y="{y+19:.1f}" fill="{c["text"]}" '
                           f'font-size="10.5">{self._svg_text(label)}</text>')
        out.append('</svg>')
        path.write_text("\n".join(out), encoding="utf-8")

    @staticmethod
    def _pdf_safe(text: Any) -> str:
        value = str(text)
        try:
            value.encode("cp1252")
            return value
        except UnicodeEncodeError:
            return value.encode("cp1252", errors="replace").decode("cp1252")

    def _pdf(self, path: Path, layout: dict[str, Any], page: str = "auto") -> None:
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A0, A1, A2, A3, A4, A5, LETTER, LEGAL, landscape, portrait
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise RuntimeError("Para exportar PDF, instale a dependência reportlab: py -m pip install reportlab") from exc

        sizes = {"A0": A0, "A1": A1, "A2": A2, "A3": A3, "A4": A4, "A5": A5,
                 "LETTER": LETTER, "LEGAL": LEGAL}
        key = str(page or "auto").upper().replace(" ", "")
        if key == "AUTO":
            # Diagram units are close to SVG pixels; the 0.72 conversion keeps
            # the default output comfortably readable at normal print sizes.
            scale = 0.72
            page_w, page_h = layout["content_w"] * scale, layout["content_h"] * scale
            offset_x = offset_y = 0
        else:
            landscape_page = key.startswith("LANDSCAPE")
            key = key.replace("LANDSCAPE", "").replace("-", "")
            if key not in sizes:
                raise ValueError(f"tamanho de página desconhecido: {page}")
            page_w, page_h = sizes[key]
            if landscape_page:
                page_w, page_h = landscape((page_w, page_h))
            else:
                page_w, page_h = portrait((page_w, page_h))
            scale = min((page_w - 54) / layout["content_w"],
                        (page_h - 54) / layout["content_h"])
            offset_x = (page_w - layout["content_w"] * scale) / 2
            offset_y = (page_h - layout["content_h"] * scale) / 2

        pdf = canvas.Canvas(str(path), pagesize=(page_w, page_h), pageCompression=1)
        pdf.setTitle(self._pdf_safe(self.title or "Fluxograma"))
        pdf.translate(offset_x, page_h - offset_y)
        pdf.scale(scale, -scale)
        c = self.theme

        def color(value: str):
            return colors.HexColor(value)

        def text(value: Any, x: float, y: float, size: float, fill: str,
                 bold: bool = False, align: str = "left") -> None:
            pdf.saveState()
            pdf.translate(x, y)
            pdf.scale(1, -1)  # compensate for the top-down page transform
            pdf.setFillColor(color(fill))
            pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            value = self._pdf_safe(value)
            if align == "middle":
                pdf.drawCentredString(0, 0, value)
            elif align == "end":
                pdf.drawRightString(0, 0, value)
            else:
                pdf.drawString(0, 0, value)
            pdf.restoreState()

        def polyline(points: list[tuple[float, float]], stroke: str, width: float = 1.5,
                     dashed: bool = False) -> None:
            if len(points) < 2:
                return
            pdf.saveState()
            pdf.setStrokeColor(color(stroke))
            pdf.setLineWidth(width)
            pdf.setLineCap(1)
            pdf.setLineJoin(1)
            pdf.setDash(5, 4) if dashed else pdf.setDash()
            pth = pdf.beginPath()
            pth.moveTo(*points[0])
            for point in points[1:]:
                pth.lineTo(*point)
            pdf.drawPath(pth, stroke=1, fill=0)
            pdf.restoreState()

        def polygon(points: list[tuple[float, float]], fill: str, stroke: str | None = None,
                    width: float = 1.5) -> None:
            pth = pdf.beginPath()
            pth.moveTo(*points[0])
            for point in points[1:]:
                pth.lineTo(*point)
            pth.close()
            pdf.setFillColor(color(fill))
            if stroke:
                pdf.setStrokeColor(color(stroke))
                pdf.setLineWidth(width)
            pdf.drawPath(pth, stroke=1 if stroke else 0, fill=1)

        pdf.setFillColor(color(c["background"]))
        pdf.rect(0, 0, layout["content_w"], layout["content_h"], stroke=0, fill=1)

        # Header
        yy = layout["margin"]
        if self.eyebrow:
            text(self.eyebrow.upper(), layout["margin"], yy + 11, 9, c["accent"], True)
            yy += 23
        if self.title:
            text(self.title, layout["margin"], yy + 14, 21, c["text"], True)
            yy += 28
        for line in layout["desc_lines"]:
            text(line, layout["margin"], yy + 13, 10, c["muted"])
            yy += 16

        gx, gy = layout["graph_left"], layout["graph_top"]
        def point(x: float, y: float) -> tuple[float, float]:
            return x + gx, y + gy

        # Frames
        for frame in self.frames:
            x, y, w, h = self._frame_bounds(frame)
            pdf.saveState()
            pdf.setStrokeColor(color(c["frame"]))
            pdf.setLineWidth(1.2)
            pdf.setDash(6, 5)
            pdf.roundRect(x + gx, y + gy, w, h, 12, stroke=1, fill=0)
            pdf.restoreState()
            text(frame["label"], x + gx + 15, y + gy + float(frame.get("label_dy", 24)),
                 10, c["muted"], True)

        routes: list[tuple[dict[str, Any], list[tuple[float, float]]]] = []
        arrow_heads: list[list[tuple[float, float]]] = []
        for edge in self.edges:
            route = self._edge_route(edge)
            routes.append((edge, route))
            points = [point(x, y) for x, y in route]
            polyline(points, c["muted"], 1.5, bool(edge.get("dashed")))
            if len(points) > 1:
                (x1, y1), (x2, y2) = points[-2], points[-1]
                angle = math.atan2(y2 - y1, x2 - x1)
                tip_x, tip_y = x2 - 1.5 * math.cos(angle), y2 - 1.5 * math.sin(angle)
                size, wing = 14, 6
                bx, by = tip_x - size * math.cos(angle), tip_y - size * math.sin(angle)
                arrow_heads.append([(tip_x, tip_y),
                    (bx + wing * math.sin(angle), by - wing * math.cos(angle)),
                    (bx - wing * math.sin(angle), by + wing * math.cos(angle))])

        # Nodes
        for node in self.nodes.values():
            x, y = point(node.x, node.y)
            fill, stroke = self._node_style(node.style)
            if node.shape == "diamond":
                polygon([(x + node.w / 2, y), (x + node.w, y + node.h / 2),
                         (x + node.w / 2, y + node.h), (x, y + node.h / 2)], fill, stroke)
            else:
                pdf.setFillColor(color(fill))
                pdf.setStrokeColor(color(stroke))
                pdf.setLineWidth(1.5)
                radius = node.h / 2 if node.shape == "stadium" else 11
                pdf.roundRect(x, y, node.w, node.h, radius, stroke=1, fill=1)

            title_lines = self._wrap(node.title, max(12, int((node.w - 34) / 8.2)))
            sub_lines = self._wrap(node.sub, max(14, int((node.w - 34) / 7.1))) if node.sub else []
            tag_h = 16 if node.tag else 0
            total = len(title_lines) * 17 + len(sub_lines) * 14 + tag_h
            baseline = y + (node.h - total) / 2 + 13
            for line in title_lines:
                text(line, x + node.w / 2, baseline, 11.5, c["text"], True, "middle")
                baseline += 17
            for line in sub_lines:
                text(line, x + node.w / 2, baseline, 9, c["muted"], False, "middle")
                baseline += 14
            if node.tag:
                tag_width = min(node.w - 28, max(54, len(node.tag) * 6 + 20))
                tx, ty = x + (node.w - tag_width) / 2, y + node.h - 21
                pdf.saveState()
                pdf.setFillColor(color(c["accent"]))
                pdf.setFillAlpha(0.18)
                pdf.roundRect(tx, ty, tag_width, 15, 7, stroke=0, fill=1)
                pdf.restoreState()
                text(node.tag, x + node.w / 2, ty + 11, 7.5, c["accent"], True, "middle")

        for points in arrow_heads:
            polygon(points, c["accent"], c["background"], 1.0)

        # Edge labels
        for edge, route in routes:
            label = edge.get("label")
            if not label:
                continue
            fraction = {"start": 0.2, "mid": 0.5, "end": 0.6}.get(edge.get("near", "mid"), 0.5)
            lx, ly = self._point_on_route(route, fraction)
            if edge.get("at") is not None:
                lx, ly = edge["at"]
            lx += float(edge.get("dx", 0) or 0)
            ly += float(edge.get("dy", 0) or 0)
            lx, ly = point(lx, ly)
            anchor = edge.get("anchor", "middle")
            label_width = max(36, len(str(label)) * 6 + 16)
            left = lx - label_width / 2 if anchor == "middle" else (lx if anchor == "start" else lx - label_width)
            pdf.setFillColor(color(c["background"]))
            pdf.roundRect(left, ly - 12, label_width, 19, 6, stroke=0, fill=1)
            align = anchor if anchor in ("start", "middle", "end") else "middle"
            text(label, lx, ly + 2, 8.5, c["text"], True, align)

        # Legend
        if self.legend_items:
            panel_w = min(layout["content_w"] - 2 * layout["margin"], 760)
            panel_x = (layout["content_w"] - panel_w) / 2
            panel_y = layout["legend_top"]
            inset, gap, row_h = 14.0, 8.0, 30.0
            usable_w = panel_w - 2 * inset
            cards = []
            row = 0
            x = panel_x + inset
            for style, label in self.legend_items:
                card_w = min(usable_w, max(112, len(label) * 6.5 + 50))
                if x + card_w > panel_x + panel_w - inset:
                    row += 1
                    x = panel_x + inset
                cards.append((x, panel_y + 39 + row * (row_h + 7), card_w, style, label))
                x += card_w + gap
            panel_h = 49 + (row + 1) * (row_h + 7)
            pdf.setFillColor(color(c["panel"]))
            pdf.setStrokeColor(color(c["border"]))
            pdf.setLineWidth(1)
            pdf.roundRect(panel_x, panel_y, panel_w, panel_h, 13, stroke=1, fill=1)
            text("LEGENDA DO FLUXO", panel_x + inset, panel_y + 22, 8.5, c["muted"], True)
            for x, y, card_w, style, label in cards:
                fill, stroke = self._node_style(style if style != "frame" else "normal")
                pdf.setFillColor(color(c["background"]))
                pdf.setStrokeColor(color(c["border"]))
                pdf.setLineWidth(0.8)
                pdf.roundRect(x, y, card_w, row_h, 8, stroke=1, fill=1)
                if style == "frame":
                    pdf.saveState()
                    pdf.setStrokeColor(color(c["frame"]))
                    pdf.setLineWidth(1)
                    pdf.setDash(4, 3)
                    pdf.roundRect(x + 9, y + 9, 20, 12, 3, stroke=1, fill=0)
                    pdf.restoreState()
                else:
                    pdf.setFillColor(color(fill))
                    pdf.setStrokeColor(color(stroke))
                    pdf.roundRect(x + 9, y + 9, 20, 12, 4, stroke=1, fill=1)
                text(label, x + 37, y + 19, 8.5, c["text"])

        pdf.showPage()
        pdf.save()

    def save(self, path: str, page: str = "auto") -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        layout = self._layout()
        if output.suffix.lower() == ".pdf":
            self._pdf(output, layout, page)
        else:
            self._svg(output, layout)

