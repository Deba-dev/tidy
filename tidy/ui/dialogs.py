"""Review before deleting, progress while deleting, and what happened afterwards."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFrame, QPlainTextEdit, QProgressBar, QRadioButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .. import winapi
from ..knowledge import CHOICE, LABEL, SAFE
from . import theme
from .common import button, hbox, label
from .pages import ElideLabel


class ReviewDialog(QDialog):
    """The last stop: what goes, where it goes (Recycle Bin or gone for good), and a tick for the person's own files."""
    def __init__(self, parent, entries, settings):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle("Review before deleting")
        self.setMinimumSize(720, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        total = sum(e.size for e in entries)
        lay.addWidget(label("Review before deleting", "h1"))
        lay.addWidget(label("You picked %d item%s, %s in all. Check the list, then choose how to delete." % (
            len(entries), "" if len(entries) == 1 else "s", theme.size_text(total)), "muted"))

        tree = QTreeWidget()
        tree.setHeaderLabels(["Item", "Size", "Where"])
        tree.setColumnWidth(0, 260)
        tree.setColumnWidth(1, 90)
        tree.setRootIsDecorated(True)
        for safety in (SAFE, CHOICE):
            mine = [e for e in entries if e.info.safety == safety]
            if not mine:
                continue
            top = QTreeWidgetItem(tree, ["%s  (%d)" % (LABEL[safety], len(mine)),
                                         theme.size_text(sum(e.size for e in mine)), ""])
            top.setForeground(0, theme.color(safety))
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            for e in sorted(mine, key=lambda e: -e.size):
                name = e.info.title if e.kind != "path" else e.name
                if e.kind == "contents":
                    name += "  (contents)"
                item = QTreeWidgetItem(top, [name, theme.size_text(e.size), e.path or "All drives"])
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setToolTip(2, e.path)
            top.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            top.setExpanded(safety == CHOICE or len(mine) <= 8)
        lay.addWidget(tree, 1)

        self.recycle = QRadioButton("Move to the Recycle Bin")
        self.permanent = QRadioButton("Delete permanently")
        group = QButtonGroup(self)
        group.addButton(self.recycle)
        group.addButton(self.permanent)
        (self.permanent if settings.get("delete_mode") == "permanent" else self.recycle).setChecked(True)
        lay.addWidget(self._option(self.recycle, "You can bring things back from the Recycle Bin if you change your "
                                   "mind. The space is only freed once the bin is emptied."))
        lay.addWidget(self._option(self.permanent, "Frees the space right away. This can't be undone."))
        notes = []
        if any(e.kind == "recyclebin" for e in entries):
            notes.append("The Recycle Bin itself is emptied for good either way.")
        usb = [e for e in entries if e.path and not winapi.recycle_bin_works(e.path)]
        if usb:
            notes.append("%d item%s on a USB drive or memory card: those have no Recycle Bin, so they are always "
                         "deleted for good." % (len(usb), " is" if len(usb) == 1 else "s are"))
        if notes:
            lay.addWidget(label("  ".join(notes), "faint"))
        self.confirm_mine = QCheckBox("I checked the amber items: they are mine and I don't need them any more.")
        has_choice = any(e.info.safety == CHOICE for e in entries)
        self.confirm_mine.setVisible(has_choice)
        lay.addWidget(self.confirm_mine)
        self.go = button("", "primary", self.accept)
        cancel = button("Cancel", None, self.reject)
        cancel.setDefault(True)
        cancel.setAutoDefault(True)
        self.go.setAutoDefault(False)
        lay.addWidget(hbox(None, cancel, self.go))
        for w in (self.recycle, self.permanent, self.confirm_mine):
            w.toggled.connect(self._update)
        self.has_choice = has_choice
        self._update()

    def _option(self, radio, text):
        box = QFrame()
        box.setObjectName("card")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        f = radio.font()
        f.setBold(True)
        radio.setFont(f)
        lay.addWidget(radio)
        hint = label(text, "muted")
        hint.setContentsMargins(26, 0, 0, 0)
        lay.addWidget(hint)
        return box

    def _update(self):
        if self.permanent.isChecked():
            self.go.setText("Delete permanently")
            self.go.setObjectName("danger")
        else:
            self.go.setText("Move to the Recycle Bin")
            self.go.setObjectName("primary")
        self.go.style().unpolish(self.go)
        self.go.style().polish(self.go)
        self.go.setEnabled(not self.has_choice or self.confirm_mine.isChecked())

    def is_permanent(self):
        return self.permanent.isChecked()

    def accept(self):
        self.s.set("delete_mode", "permanent" if self.is_permanent() else "recycle")
        super().accept()


class ProgressDialog(QDialog):
    def __init__(self, parent, permanent, stop):
        super().__init__(parent)
        self.setWindowTitle("Tidy")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.addWidget(label("Deleting permanently..." if permanent else "Moving to the Recycle Bin...", "h2"))
        self.path = ElideLabel("", "faint")
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        lay.addWidget(bar)
        lay.addWidget(self.path)
        self.stop_btn = button("Stop after this item", None, lambda: (stop(), self.stop_btn.setEnabled(False)))
        lay.addWidget(hbox(None, self.stop_btn))

    def reject(self):
        pass                                    # Esc must not hide the window while files are being deleted


class ResultDialog(QDialog):
    def __init__(self, parent, report):
        super().__init__(parent)
        self.setWindowTitle("Done")
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(8)
        size = theme.size_text(report.freed)
        if report.permanent:
            lay.addWidget(label("%s freed" % size, "bigNumber"))
        else:
            lay.addWidget(label("%s moved to the Recycle Bin" % size, "bigNumber"))
            lay.addWidget(label("You can still bring things back from there. Empty the Recycle Bin (it is on the "
                                "Junk page) when you're sure, to free the space.", "muted"))
        if report.cancelled:
            lay.addWidget(label("Stopped early, as you asked.", "muted"))
        if report.failed:
            lay.addWidget(label("%d item%s skipped. That usually means a program is using %s right now: close it "
                                "and try again, or leave it, it's harmless." % (
                                    len(report.failed), " was" if len(report.failed) == 1 else "s were",
                                    "it" if len(report.failed) == 1 else "them"), "muted"))
            details = QPlainTextEdit("\n".join("%s  -  %s" % (p, why) for p, why in report.failed))
            details.setReadOnly(True)
            details.setMinimumHeight(150)
            details.hide()
            toggle = button("Show what was skipped", "link")
            toggle.clicked.connect(lambda: (details.setVisible(not details.isVisible()),
                                            toggle.setText("Hide the list" if details.isVisible() else
                                                           "Show what was skipped")))
            lay.addWidget(toggle)
            lay.addWidget(details)
        ok = button("OK", "primary", self.accept)
        ok.setDefault(True)
        lay.addWidget(hbox(None, ok))
