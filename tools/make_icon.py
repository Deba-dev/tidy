"""Writes assets/icon.ico (and a 256 px PNG) from the icon drawn in tidy/ui/icon.py."""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from PySide6.QtGui import QGuiApplication  # noqa: E402

from tidy.ui.icon import pixmap, write_ico  # noqa: E402

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    os.makedirs(os.path.join(HERE, "assets"), exist_ok=True)
    write_ico(os.path.join(HERE, "assets", "icon.ico"))
    pixmap(256).save(os.path.join(HERE, "assets", "icon.png"))
    print("assets/icon.ico written")
