"""Render a single converted icon large + report geometry validity."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

BASE = os.path.dirname(os.path.abspath(__file__))
name = sys.argv[1]
size = int(sys.argv[2]) if len(sys.argv) > 2 else 512

with open(os.path.join(BASE, "out", name + ".svg"), "rb") as f:
    renderer = QSvgRenderer(QByteArray(f.read()))
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing, True)
renderer.render(p)
p.end()
img.save(os.path.join(BASE, name + "_big.png"))
print("saved", name, size)
