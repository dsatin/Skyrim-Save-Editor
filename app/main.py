from __future__ import annotations

import sys
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from app.core.resources import resource_path
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Skyrim Save Lab")
    icon_path = resource_path("icons", "skyrim.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
