"""The Memory page: what uses RAM right now, explained, plus closing apps and freeing memory the honest way."""
from PySide6.QtCore import QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QCheckBox, QMessageBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .. import memory, winapi
from ..knowledge import CHOICE, KEEP, SAFE
from . import theme
from .common import BAR, SAFETY, PillDelegate, SizeDelegate, button, card, hbox, label
from .pages import Page

APP = Qt.ItemDataRole.UserRole + 20
SORT = Qt.ItemDataRole.UserRole + 21
LEVEL_TEXT = {SAFE: "Plenty left", CHOICE: "Getting full", KEEP: "Very full"}
PILL_TEXT = {SAFE: "Safe to close", CHOICE: "Your choice", KEEP: "Keep running"}


class Job(QThread):
    """Runs one function off the window's thread."""
    result = Signal(object)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.result.emit(self.fn(*self.args))
        except Exception as e:                      # never take the window down
            self.result.emit(e)


class Gauge(QWidget):
    def __init__(self):
        super().__init__()
        self.share, self.level = 0.0, SAFE
        self.setFixedHeight(14)

    def set(self, share, level):
        self.share, self.level = share, level
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect())
        p.setBrush(theme.color("bar_bg"))
        p.drawRoundedRect(r, 7, 7)
        p.setBrush(theme.color(self.level))
        p.drawRoundedRect(QRectF(0, 0, max(14.0, r.width() * min(1.0, self.share)), r.height()), 7, 7)


class AppItem(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 1
        if col == 1:
            return (self.data(1, SORT) or 0) < (other.data(1, SORT) or 0)
        return self.text(col).lower() < other.text(col).lower()


class MemoryPage(Page):
    current_changed = Signal(object)

    def __init__(self):
        super().__init__("Memory", "What is using your memory (RAM) right now. Windows keeps spare memory busy as a "
                                   "cache on purpose, so a full bar is only a problem when the PC feels slow.")
        self.jobs = []
        self.apps = {}

        gauge_card = card()
        gl = QVBoxLayout(gauge_card)
        gl.setContentsMargins(18, 14, 18, 14)
        gl.setSpacing(8)
        self.big = label("", "bigNumber", wrap=False)
        self.level = label("", "h2", wrap=False)
        self.gauge = Gauge()
        self.facts = label("", "muted")
        gl.addWidget(hbox(self.big, 12, self.level, None))
        gl.addWidget(self.gauge)
        gl.addWidget(self.facts)
        self.trim_btn = button("Free up memory", "primary", self.trim)
        self.trim_btn.setToolTip("Asks every app to give back memory it isn't using right now. Apps take back what "
                                 "they need, so it helps most just before starting a game.")
        self.standby_btn = button("Clear standby cache", None, self.standby)
        self.result = label("", "muted")
        gl.addWidget(hbox(self.trim_btn, self.standby_btn, 10, self.result, None))
        gl.addWidget(label("Free up memory asks apps to hand back memory they aren't using; nothing closes and "
                           "nothing is lost. Clear standby cache drops files Windows kept in memory just in case "
                           "(administrator only). Both help for a while, not forever: the real fix for a full bar "
                           "is closing apps you don't need.", "faint"))
        self.lay.addWidget(gauge_card)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["App", "Memory", "Safety", "What it is"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegateForColumn(2, PillDelegate(self.tree))
        self.tree.setItemDelegateForColumn(1, SizeDelegate(self.tree))
        for col, w in enumerate((300, 110, 150)):
            self.tree.setColumnWidth(col, w)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.tree.currentItemChanged.connect(lambda cur, _: self.current_changed.emit(self._detail(cur)))
        self.tree.itemChanged.connect(lambda *_: self._update_bar())
        self.show_keep = QCheckBox("Show Windows' own processes too")
        self.show_keep.toggled.connect(lambda _: self._filter())
        self.lay.addWidget(hbox(label("Running apps, most memory first. Tick the ones you want to close.", "muted", wrap=False),
                                None, self.show_keep))
        self.lay.addWidget(self.tree, 1)
        self.sel = label("", "muted", wrap=False)
        self.close_btn = button("Close ticked apps", "primary", self.close_ticked)
        self.lay.addWidget(hbox(self.sel, None, self.close_btn))

        self.timer = QTimer(self, interval=3000, timeout=self.refresh)
        admin = winapi.is_admin()
        self.standby_btn.setEnabled(admin)
        if not admin:
            self.standby_btn.setToolTip("Needs administrator rights: use 'Restart as administrator' in the sidebar.")
        self._update_bar()

    # ---------------------------------------------------------------- refreshing
    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()

    def _run(self, fn, done, *args):
        job = Job(fn, *args)
        job.result.connect(done)
        job.finished.connect(lambda: self.jobs.remove(job) if job in self.jobs else None)
        self.jobs.append(job)
        job.start()
        return job

    def refresh(self):
        if any(isinstance(j, Job) and j.fn is _read for j in self.jobs):
            return
        self._run(_read, self._show)

    def _show(self, data):
        if isinstance(data, Exception):
            return
        st, apps = data
        self.big.setText("%s of %s in use" % (theme.size_text(st.used), theme.size_text(st.total)))
        self.level.setText(LEVEL_TEXT[st.level])
        self.level.setStyleSheet("color: %s;" % theme.current[st.level])
        self.gauge.set(st.percent / 100.0, st.level)
        facts = "%d%% used  ·  %s available" % (st.percent, theme.size_text(st.available))
        if st.commit_limit:
            facts += "  ·  %s of %s promised to apps (RAM plus page file)" % (
                theme.size_text(st.commit_used), theme.size_text(st.commit_limit))
        self.facts.setText(facts)
        self.tree.setSortingEnabled(False)
        self.tree.blockSignals(True)
        seen = set()
        biggest = max([a.memory for a in apps] + [1])
        for a in apps:
            seen.add(a.key)
            item = self.apps.get(a.key)
            if item is None:
                item = AppItem(self.tree)
                item.setFlags((item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsAutoTristate)
                if a.safety == KEEP:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setForeground(0, theme.color("muted"))
                    item.setToolTip(0, a.advice)
                else:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                self.apps[a.key] = item
            name = a.title + ("  (%d)" % a.count if a.count > 1 else "")
            item.setText(0, name)
            item.setText(1, theme.size_text(a.memory))
            item.setData(1, SORT, a.memory)
            item.setData(1, BAR, a.memory / biggest)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setData(2, SAFETY, a.safety)
            item.setText(2, PILL_TEXT[a.safety])
            item.setText(3, a.what)
            item.setData(0, APP, a)
        for key in [k for k in self.apps if k not in seen]:
            item = self.apps.pop(key)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self.tree.blockSignals(False)
        self.tree.setSortingEnabled(True)
        self._filter()
        self._update_bar()

    def _filter(self):
        show = self.show_keep.isChecked()
        for item in self.apps.values():
            a = item.data(0, APP)
            item.setHidden(a.safety == KEEP and not show)

    @staticmethod
    def _detail(item):
        if item is None:
            return None
        a = item.data(0, APP)
        what = a.what
        if a.count > 1:
            what += " It runs as %d processes using %s together." % (a.count, theme.size_text(a.memory))
        if a.path:
            what += "\n\n" + a.path
        return (a.title, what, a.safety, a.advice)

    def ticked(self):
        return [i.data(0, APP) for i in self.apps.values()
                if i.flags() & Qt.ItemFlag.ItemIsUserCheckable and i.checkState(0) == Qt.CheckState.Checked]

    def _update_bar(self):
        apps = self.ticked()
        if apps:
            self.sel.setText("%d app%s ticked  ·  %s" % (len(apps), "" if len(apps) == 1 else "s",
                                                       theme.size_text(sum(a.memory for a in apps))))
        else:
            self.sel.setText("Nothing ticked. Tick apps you don't need right now to close them.")
        self.close_btn.setEnabled(bool(apps))

    # ---------------------------------------------------------------- actions
    def close_ticked(self):
        apps = self.ticked()
        if not apps:
            return
        names = "\n".join("•  " + a.title for a in apps)
        if QMessageBox.question(self, "Close apps", "Close these apps?\n\n%s\n\nEach one is asked to close "
                                "normally, so it can ask you to save your work first." % names) != \
                QMessageBox.StandardButton.Yes:
            return
        self.close_btn.setEnabled(False)
        self.result.setText("Closing...")
        self._run(memory.close, lambda left: self._closed(apps, left), apps)

    def _closed(self, apps, left):
        if isinstance(left, Exception):
            left = []
        still = [a for a in apps if a.name in left]
        self.result.setText("")
        if still:
            names = "\n".join("•  " + a.title for a in still)
            box = QMessageBox(self)
            box.setWindowTitle("Some apps are still open")
            box.setText("These are still running:\n\n%s" % names)
            box.setInformativeText("They may be asking you to save something (check the taskbar), or they run "
                                   "without a window. Force close them? Anything unsaved in them is lost.")
            force = box.addButton("Force close", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("Leave them", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is force:
                self._run(memory.close, lambda _: self.refresh(), still, True)
        for item in self.apps.values():
            if item.data(0, APP) in apps and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Unchecked)
        self.refresh()

    def trim(self):
        self.trim_btn.setEnabled(False)
        self.result.setText("Asking apps to hand back memory...")
        self._run(memory.trim, self._trimmed)

    def _trimmed(self, freed):
        self.trim_btn.setEnabled(True)
        if isinstance(freed, Exception):
            self.result.setText("That didn't work this time.")
        else:
            self.result.setText("%s more available now." % theme.size_text(freed) if freed > 0 else
                                "Apps were already lean: nothing to hand back.")
        self.refresh()

    def standby(self):
        self.standby_btn.setEnabled(False)
        self.result.setText("Clearing the standby cache...")
        self._run(memory.clear_standby, self._cleared)

    def _cleared(self, freed):
        self.standby_btn.setEnabled(True)
        if isinstance(freed, Exception) or freed < 0:
            self.result.setText("Windows didn't allow it. It needs administrator rights.")
        else:
            self.result.setText("%s more available now." % theme.size_text(freed))
        self.refresh()

    def stop(self):
        self.timer.stop()
        for j in list(self.jobs):
            j.wait(3000)


def _read():
    return memory.status(), memory.apps()
