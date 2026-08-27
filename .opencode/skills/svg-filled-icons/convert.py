"""Convert Lucide stroke icons (embedded originals) to filled outline paths."""
import math
import os
import re
import xml.etree.ElementTree as ET

from shapely.geometry import LineString
from svgpathtools import parse_path

SVG_NS = "http://www.w3.org/2000/svg"
STROKE_WIDTH = 2.0

ICONS = {
    "arrow-left": '<path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/>',
    "axis-x": '<path d="M3 12h18"/><path d="m8 7-5 5 5 5"/><path d="m16 7 5 5-5 5"/>',
    "axis-y": '<path d="M12 3v18"/><path d="m7 8 5-5 5 5"/><path d="m7 16 5 5 5-5"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "file-down": (
        '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 '
        '3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/>'
        '<path d="M14 2v5a1 1 0 0 0 1 1h5"/>'
        '<path d="M12 18v-6"/><path d="m9 15 3 3 3-3"/>'
    ),
    "file-up": (
        '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 '
        '3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/>'
        '<path d="M14 2v5a1 1 0 0 0 1 1h5"/>'
        '<path d="M12 12v6"/><path d="m15 15-3-3-3 3"/>'
    ),
    "file-digit": (
        '<path d="M4 12V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.706.706l3.588 3.588A2.4 2.4 '
        '0 0 1 20 8v12a2 2 0 0 1-2 2"/>'
        '<path d="M14 2v5a1 1 0 0 0 1 1h5"/>'
        '<path d="M10 16h2v6"/><path d="M10 22h4"/>'
        '<rect x="2" y="16" width="4" height="6" rx="2"/>'
    ),
    "file-type-corner": (
        '<path d="M12 22h6a2 2 0 0 0 2-2V8a2.4 2.4 0 0 0-.706-1.706l-3.588-3.588A2.4 '
        '2.4 0 0 0 14 2H6a2 2 0 0 0-2 2v6"/>'
        '<path d="M14 2v5a1 1 0 0 0 1 1h5"/>'
        '<path d="M3 16v-1.5a.5.5 0 0 1 .5-.5h7a.5.5 0 0 1 .5.5V16"/>'
        '<path d="M6 22h2"/><path d="M7 14v8"/>'
    ),
    "folder-open": (
        '<path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 '
        '0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2'
        'a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>'
    ),
    "rotate-ccw": (
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
        '<path d="M3 3v5h5"/>'
    ),
    "save": (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/>'
        '<path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>'
    ),
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "settings": (
        '<path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06'
        'a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 '
        '1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06'
        'a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65'
        ' 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65'
        ' 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1'
        ' 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 '
        '0 0 0 19.4 9c.11.31.29.6.51.85.22.25.5.44.82.55.32.11.66.15 1 .1H21a2 2 0 0 1 '
        '0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>'
    ),
    "table": (
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<path d="M3 10h18"/><path d="M9 4v16"/>'
    ),
    "gavel": (
        '<path d="m14 13-8.381 8.38a1 1 0 0 1-3.001-3l8.384-8.381"/>'
        '<path d="m16 16 6-6"/>'
        '<path d="m21.5 10.5-8-8"/>'
        '<path d="m8 8 6-6"/>'
        '<path d="m8.5 7.5 8 8"/>'
    ),
}

BASE = os.path.dirname(os.path.abspath(__file__))
ORIG_DIR = os.path.join(BASE, "orig")
OUT_DIR = os.path.join(BASE, "out")


def split_subpaths(d: str) -> list[str]:
    """Split a path data string into per-M subpath strings."""
    parts = re.split(r"(?=[Mm])", d.strip())
    return [p for p in parts if p]


def sample_d(d: str, scale: float) -> list[tuple[float, float]]:
    pts: list[complex] = []
    path = parse_path(d)
    for seg in path:
        try:
            length = seg.length()
        except Exception:
            length = 1.0
        n = max(2, int(math.ceil(length * scale)))
        for i in range(n):
            p = seg.point(i / n)
            pts.append(complex(p.real, p.imag))
    pts.append(path[-1].point(1))
    deduped: list[complex] = []
    for q in pts:
        if not deduped or abs(q - deduped[-1]) > 1e-7:
            deduped.append(q)
    return [(q.real, q.imag) for q in deduped]


def stroke_poly(pts: list[tuple[float, float]]):
    return LineString(pts).buffer(
        STROKE_WIDTH / 2, cap_style="round", join_style="round", quad_segs=32
    )


def rounded_rect_ring(x: float, y: float, w: float, h: float, rx: float) -> list[tuple[float, float]]:
    rx = max(0.0, min(rx, w / 2.0, h / 2.0))
    if rx == 0:
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    else:
        pts = []
        corners = [
            (x + rx, y + rx, math.pi, 1.5 * math.pi),
            (x + w - rx, y + rx, 1.5 * math.pi, 2.0 * math.pi),
            (x + w - rx, y + h - rx, 0.0, 0.5 * math.pi),
            (x + rx, y + h - rx, 0.5 * math.pi, math.pi),
        ]
        steps = max(8, int(rx * 12))
        for cx, cy, a0, a1 in corners:
            for i in range(steps + 1):
                a = a0 + (a1 - a0) * i / steps
                pts.append((cx + rx * math.cos(a), cy + rx * math.sin(a)))
    deduped = [pts[0]]
    for q in pts[1:]:
        if abs(q[0] - deduped[-1][0]) > 1e-9 or abs(q[1] - deduped[-1][1]) > 1e-9:
            deduped.append(q)
    # Close the loop explicitly so shapely buffers an annulus, not a capped
    # horseshoe whose self-overlap breaks evenodd rendering.
    deduped.append(deduped[0])
    return deduped


def circle_ring(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    steps = max(48, int(r * 32))
    return [
        (cx + r * math.cos(2 * math.pi * i / steps), cy + r * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


def fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def to_subpath_ds(geom) -> list[str]:
    simplified = geom.simplify(0.05, preserve_topology=True)
    polys = [simplified] if simplified.geom_type == "Polygon" else list(simplified.geoms)
    parts: list[str] = []
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            cs = list(ring.coords)
            if len(cs) > 1 and abs(cs[0][0] - cs[-1][0]) < 1e-9 and abs(cs[0][1] - cs[-1][1]) < 1e-9:
                cs = cs[:-1]
            seg = f"M{fmt(cs[0][0])} {fmt(cs[0][1])}"
            for x, y in cs[1:]:
                seg += f"L{fmt(x)} {fmt(y)}"
            seg += "Z"
            parts.append(seg)
    return parts


def convert_element(el) -> list[str]:
    """Return filled-outline path d strings (one list item per source element)."""
    tag = el.tag.split("}")[-1]
    if tag == "path":
        subs = [sample_d(s, scale=8) for s in split_subpaths(el.get("d"))]
    elif tag == "rect":
        subs = [
            rounded_rect_ring(
                float(el.get("x")),
                float(el.get("y")),
                float(el.get("width")),
                float(el.get("height")),
                float(el.get("rx") or 0),
            )
        ]
    elif tag == "circle":
        subs = [circle_ring(float(el.get("cx")), float(el.get("cy")), float(el.get("r")))]
    else:
        return []

    ds: list[str] = []
    for pts in subs:
        geom = stroke_poly(pts)
        # All rings of one buffered shape must share one path element so
        # evenodd keeps interior holes (e.g. the gear's center circle).
        ds.append("".join(to_subpath_ds(geom)))
    return ds


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(ORIG_DIR, exist_ok=True)
    for name, body in ICONS.items():
        with open(os.path.join(ORIG_DIR, f"{name}.svg"), "w", encoding="utf-8") as f:
            f.write(
                f'<svg xmlns="{SVG_NS}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">\n  {body}\n</svg>\n'
            )
        svg = f'<svg xmlns="{SVG_NS}" viewBox="0 0 24 24">{body}</svg>'
        root = ET.fromstring(svg)
        ds: list[str] = []
        for el in root.iter():
            if el.tag.split("}")[-1] in ("path", "rect", "circle"):
                ds.extend(convert_element(el))
        paths = "\n".join(f'  <path fill-rule="evenodd" d="{d}"/>' for d in ds)
        out = (
            f'<svg xmlns="{SVG_NS}" viewBox="0 0 24 24" fill="currentColor">\n{paths}\n</svg>\n'
        )
        with open(os.path.join(OUT_DIR, f"{name}.svg"), "w", encoding="utf-8") as f:
            f.write(out)
        print(f"{name}: {len(out)} bytes, {len(ds)} paths")


if __name__ == "__main__":
    main()
