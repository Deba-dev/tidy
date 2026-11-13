"""Starts Tidy."""
import sys

from PySide6.QtWidgets import QApplication

from tidy.settings import Settings, setup_logging
from tidy.ui import theme
from tidy.ui.icon import icon
from tidy.version import NAME, VERSION


def main():
    log = setup_logging()
    log.info("Tidy %s starting", VERSION)
    app = QApplication(sys.argv)
    app.setApplicationName(NAME)
    app.setOrganizationName("ZunimiLabs")
    app.setStyle("Fusion")
    app.setWindowIcon(icon())
    settings = Settings()
    theme.apply(app, settings.get("theme"))
    from tidy.ui.main_window import MainWindow
    win = MainWindow(settings)
    if "--selftest" in sys.argv:        # the release build checks the packaged app starts and can look around
        from tidy import junk
        groups = junk.find()
        log.info("selftest: window built, %d junk groups found (nothing deleted)", len(groups))
        return 0
    win.modes.show()
    if "--scan" in sys.argv:            # start scanning right away (used after "Restart as administrator")
        win.overview._scan()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
