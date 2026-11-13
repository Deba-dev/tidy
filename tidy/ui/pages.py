"""The six pages: Overview, Junk, Space map, Large files, Duplicates and Settings."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox,
                               QProgressBar, QScrollArea, QSpinBox, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import junk, knowledge, scanner, winapi
from ..knowledge import CHOICE, KEEP, SAFE
from . import theme
from .common import (CheckTree, ENTRY, button, card, hbox, label, pill)
from .window_modes import MODES

NODE = Qt.ItemDataRole.UserRole + 6


class ElideLabel(QLabel):
    """One line that shortens long paths in the middle instead of stretching the window."""
    def __init__(self, text="", name=None):
        super().__init__()
        self.full = text
        if name:
            self.setObjectName(name)
        self.setMinimumWidth(50)

    def set(self, text):
        self.full = text or ""
        self.setToolTip(self.full)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        self.setText(QFontMetrics(self.font()).elidedText(self.full, Qt.TextElideMode.ElideMiddle, self.width()))


class Page(QWidget):
    def __init__(self, title, subtitle):
        super().__init__()
        self.setObjectName("page")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(28, 24, 20, 12)
        self.lay.setSpacing(10)
        self.title = label(title, "h1")
        self.subtitle = label(subtitle, "muted")
        self.lay.addWidget(self.title)
        self.lay.addWidget(self.subtitle)


class Legend(QWidget):
    """The three colours, explained once, on the Overview page."""
    ROWS = ((SAFE, "Junk Windows and apps make again by themselves. Deleting it never loses anything of yours."),
            (CHOICE, "Your own files: photos, videos, downloads, games. Only you know if you still need them."),
            (KEEP, "Windows and installed programs. Tidy never lets you tick these, so nothing important breaks."))

    def __init__(self):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for i, (safety, text) in enumerate(self.ROWS):
            grid.addWidget(_PillOnly(safety), i, 0)
            grid.addWidget(label(text, "muted"), i, 1)
        grid.setColumnStretch(1, 1)


class _PillOnly(QWidget):
    def __init__(self, safety):
        super().__init__()
        self.safety = safety
        self.setFixedSize(130, 26)

    def paintEvent(self, event):
        pill(QPainter(self), self.rect().adjusted(-4, 0, 0, 0), self.safety)


# ---------------------------------------------------------------- Overview
class OverviewPage(Page):
    scan_requested = Signal(list)
    cancel_requested = Signal()
    go = Signal(int)
    tick_safe = Signal()

    def __init__(self, settings):
        super().__init__("Free up space without guessing",
                         "Tidy looks through your PC and tells you, in plain words, what every big thing is and "
                         "whether it is safe to delete. Nothing is deleted until you review it and say yes.")
        self.s = settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("page")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 8, 8, 8)
        self.body.setSpacing(14)
        scroll.setWidget(body)
        self.lay.addWidget(scroll, 1)

        # what the colours mean
        legend = card()
        ll = QVBoxLayout(legend)
        ll.setContentsMargins(18, 14, 18, 14)
        ll.addWidget(label("What the colours mean", "h2"))
        ll.addWidget(Legend())
        self.body.addWidget(legend)

        # drives and the scan button
        self.drive_card = card()
        dl = QVBoxLayout(self.drive_card)
        dl.setContentsMargins(18, 14, 18, 16)
        dl.setSpacing(10)
        dl.addWidget(label("Drives to scan", "h2"))
        self.drive_rows = QVBoxLayout()
        self.drive_rows.setSpacing(8)
        dl.addLayout(self.drive_rows)
        self.scan_btn = button("Scan my PC", "primary", self._scan)
        self.scan_btn.setMinimumHeight(38)
        self.cancel_btn = button("Stop", None, self.cancel_requested.emit)
        self.phase = label("", "h2")
        self.detail = ElideLabel("", "faint")
        self.bar = QProgressBar()
        self.bar.setFixedHeight(8)
        self.bar.setTextVisible(False)
        dl.addWidget(hbox(self.scan_btn, self.cancel_btn, None))
        dl.addWidget(self.phase)
        dl.addWidget(self.bar)
        dl.addWidget(self.detail)
        self.body.addWidget(self.drive_card)

        # results
        self.results = QWidget()
        rl = QGridLayout(self.results)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(14)
        self.safe_card, self.safe_num, self.safe_text = self._summary(
            SAFE, "Safe to delete", [("Tick all safe junk", "primary", self.tick_safe.emit),
                                     ("See junk", None, lambda: self.go.emit(1))])
        self.choice_card, self.choice_num, self.choice_text = self._summary(
            CHOICE, "Worth a look", [("Large files", None, lambda: self.go.emit(3)),
                                     ("Duplicates", None, lambda: self.go.emit(4))])
        rl.addWidget(self.safe_card, 0, 0)
        rl.addWidget(self.choice_card, 0, 1)
        self.where = card()
        wl = QVBoxLayout(self.where)
        wl.setContentsMargins(18, 14, 18, 14)
        wl.addWidget(label("Where your space goes", "h2"))
        self.where_rows = QGridLayout()
        self.where_rows.setHorizontalSpacing(14)
        self.where_rows.setVerticalSpacing(4)
        wl.addLayout(self.where_rows)
        wl.addWidget(hbox(button("Open the Space map", None, lambda: self.go.emit(2)), None))
        rl.addWidget(self.where, 1, 0, 1, 2)
        self.footnote = label("", "faint")
        rl.addWidget(self.footnote, 2, 0, 1, 2)
        self.body.addWidget(self.results)
        self.body.addStretch(1)
        self.results.hide()
        self.checks = []
        self.refresh_drives()
        self.set_scanning(False)

    def _summary(self, safety, title, buttons):
        c = card()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(6)
        lay.addWidget(_PillOnly(safety))
        lay.addWidget(label(title, "h2"))
        num = label("", "bigNumber")
        text = label("", "muted")
        lay.addWidget(num)
        lay.addWidget(text)
        lay.addStretch(1)
        lay.addWidget(hbox(*[button(t, n, s) for t, n, s in buttons], None))
        return c, num, text

    def refresh_drives(self, drives=None):
        drives = drives if drives is not None else winapi.drives()
        chosen = set(self.s.get("drives") or [])
        old = {c.property("root"): c.isChecked() for c in self.checks}
        while self.drive_rows.count():
            w = self.drive_rows.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.checks = []
        for d in drives:
            cb = QCheckBox("%s  %s" % (d.letter, d.label))
            cb.setProperty("root", d.root)
            cb.setChecked(old.get(d.root, d.root in chosen if chosen else d.kind == "Local disk"))
            bar = QProgressBar()
            bar.setFixedHeight(8)
            bar.setTextVisible(False)
            bar.setRange(0, 1000)
            bar.setValue(int(1000 * d.used / d.total) if d.total else 0)
            info = label("%s free of %s  ·  %s" % (theme.size_text(d.free), theme.size_text(d.total), d.kind),
                         "faint", wrap=False)
            row = QWidget()
            rl = QGridLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setHorizontalSpacing(14)
            rl.addWidget(cb, 0, 0)
            rl.addWidget(bar, 0, 1)
            rl.addWidget(info, 0, 2)
            rl.setColumnMinimumWidth(0, 170)
            rl.setColumnStretch(1, 1)
            self.drive_rows.addWidget(row)
            self.checks.append(cb)

    def _scan(self):
        roots = [c.property("root") for c in self.checks if c.isChecked()]
        if not roots:
            QMessageBox.information(self, "Tidy", "Tick at least one drive to scan.")
            return
        self.s.set("drives", roots)
        self.scan_requested.emit(roots)

    def set_scanning(self, on):
        self.scan_btn.setVisible(not on)
        self.cancel_btn.setVisible(on)
        for w in (self.phase, self.bar, self.detail):
            w.setVisible(on)
        for c in self.checks:
            c.setEnabled(not on)
        if on:
            self.phase.setText("Starting...")
            self.bar.setRange(0, 0)
            self.detail.set("")

    def progress(self, phase, detail, fraction):
        self.phase.setText(phase + "...")
        self.detail.set(detail)
        if fraction < 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(fraction * 1000))

    def load(self, state):
        self.set_scanning(False)
        self.scan_btn.setText("Scan again")
        self.refresh_drives(state.drives)
        self.results.show()
        safe = sum(e.size for g in state.junk for e in g.entries if e.info.safety == SAFE and not e.locked)
        locked = sum(e.size for g in state.junk for e in g.entries if e.locked)
        self.safe_num.setText(theme.size_text(safe))
        self.safe_text.setText("Junk Tidy is sure about: caches, temporary files, crash reports and update "
                               "leftovers." + ("  %s more needs administrator rights." % theme.size_text(locked)
                                               if locked else ""))
        large = [x for x in (state.scan.large if state.scan else [])
                 if knowledge.explain(x[1], False).safety == CHOICE]
        extra = sum(g.extra for g in state.dups)
        self.choice_num.setText(theme.size_text(sum(x[0] for x in large) + extra))
        self.choice_text.setText("%d large files and %d sets of duplicate copies. These are your own files, so "
                                 "only you can decide." % (len(large), len(state.dups)))
        self._where(state)
        sc = state.scan
        if sc:
            note = "Looked at %s files in %d seconds." % (format(sc.files, ","), sc.seconds)
            if sc.cancelled:
                note += " The scan was stopped early, so some folders are missing."
            if sc.denied:
                note += " %s folders were locked by Windows (restart Tidy as administrator to see them)." % \
                    format(sc.denied, ",")
            self.footnote.setText(note)

    def _where(self, state):
        while self.where_rows.count():
            w = self.where_rows.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        if not state.scan:
            return
        rows = []
        for root in state.scan.roots:
            for d in root.dirs:
                rows.append((d.size, os.path.join(root.name, d.name)))
        rows.sort(reverse=True)
        for i, (size, path) in enumerate(rows[:7]):
            info = knowledge.explain(path, True)
            self.where_rows.addWidget(label(path, wrap=False), i, 0)
            self.where_rows.addWidget(label(theme.size_text(size), wrap=False), i, 1)
            self.where_rows.addWidget(_PillOnly(info.safety), i, 2)
            self.where_rows.addWidget(label(info.what, "muted", wrap=False), i, 3)
        self.where_rows.setColumnStretch(3, 1)


# ---------------------------------------------------------------- Junk
class JunkPage(Page):
    admin_requested = Signal()

    def __init__(self, selection):
        super().__init__("Junk", "Things Tidy recognises. Green ones are always safe to delete; open a group to "
                                 "pick single items.")
        self.selection = selection
        self.tree = CheckTree(selection, ["Item", "Size", "Safety", "Where"])
        self.tree.setColumnWidth(0, 330)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 150)
        self.admin_note = card()
        al = QVBoxLayout(self.admin_note)
        al.setContentsMargins(14, 10, 14, 10)
        self.admin_text = label("", "muted")
        row = QHBoxLayout()
        row.addWidget(self.admin_text, 1)
        row.addWidget(button("Restart as administrator", None, self.admin_requested.emit))
        al.addLayout(row)
        self.lay.addWidget(hbox(button("Tick all safe junk", "primary", self.tick_safe),
                                button("Untick all", None, self.untick), None))
        self.lay.addWidget(self.admin_note)
        self.lay.addWidget(self.tree, 1)
        self.admin_note.hide()
        self.empty = label("Run a scan from the Overview page to see junk here.", "muted")
        self.lay.addWidget(self.empty)

    def load(self, state):
        self.tree.clear()
        locked = 0
        for g in state.junk:
            top = self.tree.add_group(g.title, g.what, g.safety, theme.size_text(g.size),
                                      "%d place%s" % (len(g.entries), "" if len(g.entries) == 1 else "s"))
            for e in g.entries:
                where = e.locked + " - restart Tidy as administrator" if e.locked else (e.path or "All drives")
                self.tree.add_entry(top, e, [e.info.title if e.kind != "path" or g.id != "installers" else e.name,
                                             theme.size_text(e.size), "", where])
                locked += bool(e.locked)
            self.tree.finish_group(top)
        self.tree.refresh_checks()
        self.empty.setVisible(not state.junk)
        self.empty.setText("No junk found. Nice and tidy!" if state.scan is not None else
                           "Run a scan from the Overview page to see junk here.")
        self.admin_note.setVisible(bool(locked) and not winapi.is_admin())
        self.admin_text.setText("%d item%s can only be cleaned with administrator rights (Windows protects them)."
                                % (locked, "" if locked == 1 else "s"))

    def tick_safe(self):
        for item, e in self.tree.entries():
            if e.info.safety == SAFE and not e.locked:
                self.selection.add(e)

    def untick(self):
        for _, e in self.tree.entries():
            self.selection.remove(e.key)


# ---------------------------------------------------------------- Space map
class SpaceMapPage(Page):
    def __init__(self, selection):
        super().__init__("Space map", "Every folder on the scanned drives, biggest first. Click one to see what it "
                                      "is; open it to look inside.")
        self.tree = CheckTree(selection, ["Name", "Size", "Safety", "What it is"])
        self.tree.setColumnWidth(0, 340)
        self.tree.setColumnWidth(1, 110)
        self.tree.setColumnWidth(2, 150)
        self.tree.itemExpanded.connect(self._expand)
        self.lay.addWidget(self.tree, 1)
        self.state = None

    def load(self, state):
        self.state = state
        self.tree.clear()
        if not state.scan:
            return
        for root in state.scan.roots:
            drive = next((d for d in state.drives if knowledge.norm(d.root) == knowledge.norm(root.name)), None)
            name = root.name if drive is None else "%s  %s" % (drive.letter, drive.label)
            e = junk.Entry(root.name, "path", root.size, knowledge.explain(root.name, True), root.files)
            item = self.tree.add_entry(None, e, [name, theme.size_text(root.size), "", "The whole drive"],
                                       bar=(drive.used / drive.total) if drive and drive.total else None)
            item.setData(0, NODE, root)
            self._placeholder(item, root)
            item.setExpanded(True)

    def _placeholder(self, item, node):
        if node.dirs or node.own > 0:
            QTreeWidgetItem(item, ["Loading..."])

    def _expand(self, item):
        node = item.data(0, NODE)
        if node is None or item.childCount() != 1 or item.child(0).data(0, ENTRY) is not None:
            return
        item.takeChild(0)
        path = node.path
        rows = [(d.size, True, d.name, d) for d in node.dirs if not d.gone]
        files, (rest_n, rest_size) = scanner.list_folder(path)
        rows += [(size, False, name, mtime) for name, size, mtime in files]
        rows.sort(key=lambda r: -r[0])
        parent_size = max(1, node.size)
        self.tree.setUpdatesEnabled(False)
        for size, is_dir, name, extra in rows[:500]:
            full = os.path.join(path, name)
            e = junk.entry_for(full, size, is_dir, extra.files if is_dir else 0)
            what = e.info.title if e.info.title.lower() != name.lower() else e.info.what
            child = self.tree.add_entry(item, e, [name, theme.size_text(size), "", what], bar=size / parent_size)
            if is_dir:
                child.setData(0, NODE, extra)
                self._placeholder(child, extra)
                if extra.denied:
                    child.setToolTip(0, "Windows didn't let Tidy look inside part of this folder.")
        more = len(rows) - 500
        if rest_n or more > 0:
            n = rest_n + max(0, more)
            rest = rest_size + sum(r[0] for r in rows[500:])
            QTreeWidgetItem(item, ["%s more small items" % format(n, ","), theme.size_text(rest), "", ""])
        self.tree.setUpdatesEnabled(True)
        self.tree.refresh_checks()


# ---------------------------------------------------------------- Large files
class LargePage(Page):
    def __init__(self, selection, settings):
        super().__init__("Large files", "")
        self.s = settings
        self.tree = CheckTree(selection, ["Name", "Size", "Safety", "Kind", "Folder", "Changed"])
        self.tree.setRootIsDecorated(False)
        for col, w in enumerate((290, 90, 150, 150, 300)):
            self.tree.setColumnWidth(col, w)
        self.filter = QComboBox()
        self.filter.addItems(["Show all", "Only files I can delete", "Only files Tidy keeps"])
        self.filter.currentIndexChanged.connect(lambda _: self.load(self.state) if self.state else None)
        self.lay.addWidget(hbox(label("Show", "muted", wrap=False), self.filter, None))
        self.lay.addWidget(self.tree, 1)
        self.state = None

    def load(self, state):
        self.state = state
        self.subtitle.setText("Every file bigger than %d MB, biggest first. Videos, game files and disk images are "
                              "the usual suspects." % int(self.s.get("large_mb")))
        self.tree.clear()
        if not state.scan:
            return
        mode = self.filter.currentIndex()
        for size, path, mtime in state.scan.large:
            e = junk.entry_for(path, size, False)
            if (mode == 1 and e.info.safety == KEEP) or (mode == 2 and e.info.safety != KEEP):
                continue
            self.tree.add_entry(None, e, [os.path.basename(path), theme.size_text(size), "", e.info.title,
                                          os.path.dirname(path), theme.age_text(mtime)])
        self.tree.refresh_checks()


# ---------------------------------------------------------------- Duplicates
class DupesPage(Page):
    def __init__(self, selection):
        super().__init__("Duplicate files", "Files with exactly the same contents in more than one place (only "
                                            "among your own files). Keeping one copy is enough; Tidy suggests the "
                                            "oldest.")
        self.selection = selection
        self.tree = DupTree(selection, ["Name", "Size", "Safety", "Folder", "Changed"])
        for col, w in enumerate((300, 90, 150, 360)):
            self.tree.setColumnWidth(col, w)
        self.lay.addWidget(hbox(button("Tick extra copies (keep the oldest)", "primary", self.tick_extra),
                                button("Untick all", None, self.untick), None))
        self.lay.addWidget(self.tree, 1)
        self.empty = label("", "muted")
        self.lay.addWidget(self.empty)

    def load(self, state):
        self.tree.clear()
        for g in state.dups:
            name = os.path.basename(g.paths[0])
            top = self.tree.add_group("%d copies of %s" % (len(g.paths), name),
                                      "The same file is stored %d times. Deleting the extra copies frees %s." % (
                                          len(g.paths), theme.size_text(g.extra)), CHOICE,
                                      theme.size_text(g.extra), "%s each" % theme.size_text(g.size))
            for i, path in enumerate(g.paths):
                e = junk.entry_for(path, g.size, False)
                e.note = ("Tidy suggests keeping this copy: it is the oldest, so probably the original." if i == 0
                          else "An identical copy of %s." % g.paths[0])
                try:
                    mtime = os.stat(path).st_mtime
                except OSError:
                    mtime = 0
                item = self.tree.add_entry(top, e, [os.path.basename(path) + ("   (keep)" if i == 0 else ""),
                                                    theme.size_text(g.size), "", os.path.dirname(path),
                                                    theme.age_text(mtime)])
                item.setData(1, Qt.ItemDataRole.UserRole + 7, i)
            self.tree.finish_group(top)
        self.tree.refresh_checks()
        self.empty.setVisible(not state.dups)
        self.empty.setText("No duplicate files found among your own files." if state.scan else
                           "Run a scan from the Overview page first.")

    def tick_extra(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(1, top.childCount()):
                e = top.child(j).data(0, ENTRY)
                if e and e.info.safety != KEEP:
                    self.selection.add(e)

    def untick(self):
        for _, e in self.tree.entries():
            self.selection.remove(e.key)


class DupTree(CheckTree):
    def group_toggled(self, group, on):
        """Ticking a set ticks the extra copies only; the suggested one stays."""
        for i in range(group.childCount()):
            entry = group.child(i).data(0, ENTRY)
            if entry is None or not self.can_tick(entry):
                continue
            if on and i > 0:
                self.selection.add(entry)
            elif not on:
                self.selection.remove(entry.key)

    def allow(self, item, entry):
        """Never every copy: at least one stays."""
        parent = item.parent()
        if parent is None:
            return True
        others = [parent.child(i).data(0, ENTRY) for i in range(parent.childCount()) if parent.child(i) is not item]
        if all(o is not None and self.selection.has(o.key) for o in others):
            QMessageBox.information(self, "Tidy", "Keep at least one copy. Untick another copy first if you'd "
                                    "rather keep this one.")
            return False
        return True


# ---------------------------------------------------------------- Settings
class SettingsPage(Page):
    theme_changed = Signal(str)
    mode_changed = Signal(str)
    tray_changed = Signal()

    def __init__(self, settings):
        super().__init__("Settings", "")
        self.s = settings
        box = card()
        form = QFormLayout(box)
        form.setContentsMargins(20, 16, 20, 16)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(24)
        self.theme = QComboBox()
        self.theme.addItems(["Same as Windows", "Light", "Dark"])
        self.theme.setCurrentIndex(["system", "light", "dark"].index(settings.get("theme")))
        self.theme.currentIndexChanged.connect(self._theme)
        self.mode = QComboBox()
        for text, value in MODES:
            self.mode.addItem(text, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.get("window_mode"))))
        self.mode.currentIndexChanged.connect(lambda _: self.mode_changed.emit(self.mode.currentData()))
        self.close_tray = QCheckBox("The close button hides Tidy in the tray instead of quitting")
        self.close_tray.setChecked(bool(settings.get("close_to_tray")))
        self.esc_tray = QCheckBox("Esc hides Tidy in the tray (asks first)")
        self.esc_tray.setChecked(bool(settings.get("esc_to_tray")))
        for cb, key in ((self.close_tray, "close_to_tray"), (self.esc_tray, "esc_to_tray")):
            cb.toggled.connect(lambda on, k=key: (self.s.set(k, on), self.tray_changed.emit()))
        self.temp = self._spin("temp_hours", 1, 24 * 30, " hours")
        self.installers = self._spin("installer_days", 1, 3650, " days")
        self.large = self._spin("large_mb", 10, 100000, " MB")
        form.addRow(label("Look", "h2"))
        form.addRow("Theme", self.theme)
        form.addRow("Window", self.mode)
        form.addRow("", self.close_tray)
        form.addRow("", self.esc_tray)
        form.addRow(label("Scanning", "h2"))
        form.addRow("Leave temporary files younger than", self.temp)
        form.addRow("Suggest downloaded installers older than", self.installers)
        form.addRow("Large files start at", self.large)
        form.addRow("", label("These apply to the next scan.", "faint"))
        form.addRow(label("History", "h2"))
        from ..settings import log_dir
        form.addRow("", hbox(button("Open the deletion log", None, lambda: os.startfile(log_dir())), None))
        form.addRow("", label("Tidy writes down everything it deletes (and what it skipped) so you can always "
                              "check later.", "faint"))
        self.lay.addWidget(box)
        self.lay.addStretch(1)

    def _spin(self, key, lo, hi, suffix):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSuffix(suffix)
        sp.setValue(int(self.s.get(key)))
        sp.valueChanged.connect(lambda v: self.s.set(key, v))
        return sp

    def _theme(self, i):
        value = ["system", "light", "dark"][i]
        self.s.set("theme", value)
        self.theme_changed.emit(value)


__all__ = ["OverviewPage", "JunkPage", "SpaceMapPage", "LargePage", "DupesPage", "SettingsPage", "ElideLabel",
           "QFrame"]
