"""Tidy's icon, drawn in code: a green rounded square with a white sparkle (clean, and green means safe)."""
import math
import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap


def _sparkle(cx, cy, r, waist=0.22):
    path = QPainterPath()
    pts = []
    for i in range(8):
        ang = i * 3.14159265 / 4
        rad = r if i % 2 == 0 else r * waist
        pts.append(QPointF(cx + rad * math.sin(ang), cy - rad * math.cos(ang)))
    path.moveTo(pts[0])
    for i in range(1, 9):
        # gentle inward curves between the points
        a, b = pts[(i - 1) % 8], pts[i % 8]
        ctrl = QPointF((a.x() + b.x()) / 2 * 0.9 + cx * 0.1, (a.y() + b.y()) / 2 * 0.9 + cy * 0.1)
        path.quadTo(ctrl, b)
    path.closeSubpath()
    return path


def pixmap(size=256):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size
    rect = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0, QColor("#25b06a"))
    grad.setColorAt(1, QColor("#0f7a63"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, s * 0.22, s * 0.22)
    p.setBrush(QColor("#ffffff"))
    p.drawPath(_sparkle(s * 0.46, s * 0.54, s * 0.30))
    p.setBrush(QColor(255, 255, 255, 215))
    p.drawPath(_sparkle(s * 0.74, s * 0.27, s * 0.12))
    p.end()
    return pm


def icon():
    ic = QIcon()
    for s in (16, 20, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(pixmap(s))
    return ic


def write_ico(path, sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256)):
    """A Windows .ico with one PNG per size (for the installer and the .exe)."""
    blobs = []
    for s in sizes:
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap(s).save(buf, "PNG")
        blobs.append((s, bytes(data)))
    out = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    for s, blob in blobs:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    out += b"".join(b for _, b in blobs)
    with open(path, "wb") as f:
        f.write(out)
