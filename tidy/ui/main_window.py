"""The main window: sidebar, pages, the "About this item" panel and the selection bar at the bottom."""
import logging

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QStackedWidget, QStyledItemDelegate, QVBoxLayout, QWidget)

from .. import winapi
from ..knowledge import CHOICE, SAFE
from ..version import NAME, VERSION
from . import theme
from .common import DetailPanel, Selection, button, hbox, label
from .dialogs import ProgressDialog, ResultDialog, ReviewDialog
from .icon import icon
from .pages import DupesPage, JunkPage, LargePage, OverviewPage, SettingsPage, SpaceMapPage
from .window_modes import WindowModes
from .workers import DeleteWorker, ScanWorker, State, apply_report

log = logging.getLogger("tidy")
BADGE = Qt.ItemDataRole.UserRole + 10
PAGES = ("Overview", "Junk", "Space map", "Large files", "Duplicates", "Settings")


class NavDelegate(QStyledItemDelegate):
    """Sidebar rows with a small size badge on the right."""
    def paint(self, p, option, index):
        super().paint(p, option, index)
        badge = index.data(BADGE)
        if badge:
            p.save()
            p.setPen(theme.color("faint"))
            r = QRectF(option.rect).adjusted(0, 0, -22, 0)
            p.drawText(r, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, badge)
            p.restore()

    def sizeHint(self, option, index):
        return QSize(180, 40)


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.s = settings
        self.state = State()
        self.selection = Selection()
        self.scan_worker = None
        self.delete_worker = None
        self.setWindowTitle(NAME)
        self.setWindowIcon(icon())
        self.setMinimumSize(1080, 680)
        self.resize(1320, 840)

        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 16, 0)
        middle.setSpacing(0)
        self.stack = QStackedWidget()
        self.overview = OverviewPage(settings)
        self.junk = JunkPage(self.selection)
        self.space = SpaceMapPage(self.selection)
        self.large = LargePage(self.selection, settings)
        self.dupes = DupesPage(self.selection)
        self.settings_page = SettingsPage(settings)
        for page in (self.overview, self.junk, self.space, self.large, self.dupes, self.settings_page):
            self.stack.addWidget(page)
        self.detail = DetailPanel()
        detail_wrap = QWidget()
        dl = QVBoxLayout(detail_wrap)
        dl.setContentsMargins(0, 24, 0, 12)
        dl.addWidget(self.detail)
        self.detail_wrap = detail_wrap
        middle.addWidget(self.stack, 1)
        middle.addWidget(detail_wrap)
        right.addLayout(middle, 1)
        right.addWidget(self._selection_bar())
        outer.addLayout(right, 1)
        self.setCentralWidget(root)

        for page in (self.junk, self.space, self.large, self.dupes):
            page.tree.current_changed.connect(self.detail.show_item)
        self.overview.scan_requested.connect(self.start_scan)
        self.overview.cancel_requested.connect(self.cancel_scan)
        self.overview.go.connect(self.nav.setCurrentRow)
        self.overview.tick_safe.connect(self.tick_safe)
        self.junk.admin_requested.connect(self.restart_as_admin)
        self.settings_page.theme_changed.connect(self.set_theme)
        self.settings_page.mode_changed.connect(lambda m: self.modes.set_mode(m))
        self.settings_page.tray_changed.connect(lambda: self.modes.sync_tray())
        self.selection.changed.connect(self.update_selection_bar)
        self.nav.currentRowChanged.connect(self.show_page)
        self.modes = WindowModes(self, settings, NAME, busy=self.busy)
        self.nav.setCurrentRow(0)
        self.update_selection_bar()

    # ---------------------------------------------------------------- layout
    def _sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 22, 0, 16)
        lay.setSpacing(4)
        brand = QWidget()
        bl = QVBoxLayout(brand)
        bl.setContentsMargins(20, 0, 20, 14)
        bl.setSpacing(0)
        bl.addWidget(label(NAME, "brand"))
        bl.addWidget(label("Storage cleaner that explains", "brandSub"))
        lay.addWidget(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setItemDelegate(NavDelegate(self.nav))
        for name in PAGES:
            QListWidgetItem(name, self.nav)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.nav, 1)
        self.admin_label = label("", "faint")
        self.admin_label.setContentsMargins(20, 0, 20, 0)
        lay.addWidget(self.admin_label)
        self.admin_btn = button("Restart as administrator", "link", self.restart_as_admin)
        self.admin_btn.setContentsMargins(16, 0, 0, 0)
        lay.addWidget(hbox(self.admin_btn, None, margins=(16, 0, 0, 0)))
        version = label("Version " + VERSION, "faint")
        version.setContentsMargins(20, 6, 20, 0)
        lay.addWidget(version)
        admin = winapi.is_admin()
        self.admin_label.setText("Running as administrator" if admin else
                                 "Some Windows junk needs administrator rights.")
        self.admin_btn.setVisible(not admin)
        return side

    def _selection_bar(self):
        bar = QFrame()
        bar.setObjectName("selbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(28, 12, 20, 12)
        self.sel_text = label("", "h2", wrap=False)
        self.sel_mix = label("", "muted", wrap=False)
        self.clear_btn = button("Untick all", None, self.selection.clear)
        self.review_btn = button("Review and delete...", "primary", self.review)
        self.review_btn.setMinimumHeight(36)
        lay.addWidget(self.sel_text)
        lay.addSpacing(10)
        lay.addWidget(self.sel_mix)
        lay.addStretch(1)
        lay.addWidget(self.clear_btn)
        lay.addWidget(self.review_btn)
        return bar

    def show_page(self, i):
        self.stack.setCurrentIndex(i)
        self.detail_wrap.setVisible(i in (1, 2, 3, 4))
        page = self.stack.currentWidget()
        tree = getattr(page, "tree", None)
        self.detail.show_item(tree.detail_of(tree.currentItem()) if tree is not None else None)

    def update_selection_bar(self):
        entries = self.selection.entries()
        if not entries:
            self.sel_text.setText("Nothing ticked yet")
            self.sel_mix.setText("Tick items on any page, then review them here.")
        else:
            self.sel_text.setText("%d item%s ticked  ·  %s" % (len(entries), "" if len(entries) == 1 else "s",
                                                            theme.size_text(sum(e.size for e in entries))))
            safe = sum(1 for e in entries if e.info.safety == SAFE)
            mine = sum(1 for e in entries if e.info.safety == CHOICE)
            parts = []
            if safe:
                parts.append("%d safe" % safe)
            if mine:
                parts.append("%d your choice" % mine)
            self.sel_mix.setText("(" + ", ".join(parts) + ")")
        self.clear_btn.setEnabled(bool(entries))
        self.review_btn.setEnabled(bool(entries) and self.delete_worker is None)

    def update_badges(self):
        st = self.state
        junk_total = sum(e.size for g in st.junk for e in g.entries if not e.locked)
        badges = {1: junk_total, 3: sum(x[0] for x in st.scan.large) if st.scan else 0,
                  4: sum(g.extra for g in st.dups)}
        for i, size in badges.items():
            self.nav.item(i).setData(BADGE, theme.size_text(size) if size else "")
        self.nav.viewport().update()

    # ---------------------------------------------------------------- scanning
    def start_scan(self, roots):
        if self.scan_worker is not None:
            return
        self.selection.clear()
        self.overview.set_scanning(True)
        self.scan_worker = ScanWorker(roots, self.s)
        self.scan_worker.progress.connect(self.overview.progress)
        self.scan_worker.done.connect(self.scan_done)
        self.scan_worker.start()

    def cancel_scan(self):
        if self.scan_worker is not None:
            self.scan_worker.stop = True

    def scan_done(self, state):
        self.scan_worker.wait()
        self.scan_worker = None
        self.state = state
        self.reload()

    def reload(self):
        for page in (self.overview, self.junk, self.space, self.large, self.dupes):
            page.load(self.state)
        self.update_badges()
        self.update_selection_bar()

    def tick_safe(self):
        self.junk.tick_safe()
        self.nav.setCurrentRow(1)

    # ---------------------------------------------------------------- deleting
    def review(self):
        entries = self.selection.entries()
        if not entries or self.delete_worker is not None:
            return
        for g in self.state.dups:                   # however they were ticked, one copy always stays
            if all(self.selection.has(_key(p)) for p in g.paths):
                QMessageBox.warning(self, NAME, "Every copy of %s is ticked. Untick at least one copy so you "
                                    "keep the file." % g.paths[0])
                return
        dlg = ReviewDialog(self, entries, self.s)
        if dlg.exec() != ReviewDialog.DialogCode.Accepted:
            return
        permanent = dlg.is_permanent()
        self.delete_worker = DeleteWorker(entries, permanent)
        self.progress = ProgressDialog(self, permanent, lambda: setattr(self.delete_worker, "stop", True))
        self.delete_worker.progress.connect(self.progress.path.set)
        self.delete_worker.done.connect(self.delete_done)
        self.update_selection_bar()
        self.delete_worker.start()
        self.progress.show()

    def delete_done(self, report, sizes):
        self.delete_worker.wait()
        self.delete_worker = None
        self.progress.hide()
        self.progress.deleteLater()
        gone = apply_report(self.state, report, sizes)
        for entry, _ in report.finished:
            self.selection.remove(entry.key)
        for key in gone:
            self.selection.remove(key)
        self.reload()
        ResultDialog(self, report).exec()

    # ---------------------------------------------------------------- the rest
    def busy(self):
        if self.delete_worker is not None:
            return "Tidy is deleting files right now. Stopping in the middle leaves the job half done."
        if self.scan_worker is not None:
            return "A scan is running."
        return ""

    def restart_as_admin(self):
        if self.busy():
            QMessageBox.information(self, NAME, "Wait until Tidy has finished, then try again.")
            return
        if winapi.relaunch_as_admin(["--scan"] if self.state.scan is not None else []):
            self.modes.quitting = True
            QApplication.quit()

    def set_theme(self, choice):
        theme.apply(QApplication.instance(), choice)
        for w in self.findChildren(QWidget):
            w.update()

    def keyPressEvent(self, event):
        if self.modes.handle_key(event):
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.modes.close_event(event):
            return
        for w in (self.scan_worker, self.delete_worker):
            if w is not None:
                w.stop = True
                w.wait(5000)
        super().closeEvent(event)


def _key(path):
    from ..knowledge import norm
    return norm(path)
