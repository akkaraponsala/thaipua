"""Render orig vs converted icons side by side into one contact sheet."""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

BASE = os.path.dirname(os.path.abspath(__file__))
ORIG_DIR = os.path.join(BASE, "orig")
OUT_DIR = os.path.join(BASE, "out")
CELL = 128
GAP = 12
SCALE_UP = 4


def render(svg_path: str) -> QImage:
    with open(svg_path, "rb") as f:
        data = f.read()
    renderer = QSvgRenderer(QByteArray(data))
    img = QImage(CELL * SCALE_UP, CELL * SCALE_UP, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return img.scaled(CELL, CELL, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def main() -> None:
    names = sorted(n[:-4] for n in os.listdir(OUT_DIR) if n.endswith(".svg"))
    rows = len(names)
    width = CELL * 2 + GAP * 3
    height = rows * (CELL + GAP) + GAP
    sheet = QImage(width, height, QImage.Format_ARGB32)
    sheet.fill(QColor("#ffffff"))
    painter = QPainter(sheet)
    for row, name in enumerate(names):
        y = GAP + row * (CELL + GAP)
        painter.drawImage(GAP, y, render(os.path.join(ORIG_DIR, name + ".svg")))
        painter.drawImage(GAP * 2 + CELL, y, render(os.path.join(OUT_DIR, name + ".svg")))
    painter.end()
    sheet.save(os.path.join(BASE, "sheet.png"))
    print("sheet saved:", width, "x", height)


if __name__ == "__main__":
    main()
