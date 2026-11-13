"""Pieces every page shares: what is ticked, the safety pill, the size bar, checkable trees and the detail panel."""
import os
import time

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                               QVBoxLayout, QWidget)

from .. import deleter, knowledge, winapi
from ..knowledge import KEEP, LABEL
from . import theme

ENTRY = Qt.ItemDataRole.UserRole + 1        # the junk.Entry behind a row
SAFETY = Qt.ItemDataRole.UserRole + 2       # "safe" / "choice" / "keep" for the pill
BAR = Qt.ItemDataRole.UserRole + 3          # 0..1 share of the parent folder
DETAIL = Qt.ItemDataRole.UserRole + 4       # (title, what, safety) for rows that are not entries (group headers)
LOCKED = Qt.ItemDataRole.UserRole + 5       # pill drawn dim: can't be ticked right now


class Selection(QObject):
    """Everything ticked on any page, keyed by path, so the same file ticked twice counts once."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.items = {}
        self._timer = QTimer(self, singleShot=True, interval=0, timeout=self.changed.emit)

    def add(self, entry):
        self.items[entry.key] = entry
        self._timer.start()

    def remove(self, key):
        if self.items.pop(key, None) is not None:
            self._timer.start()

    def has(self, key):
        return key in self.items

    def clear(self):
        if self.items:
            self.items.clear()
            self._timer.start()

    def entries(self):
        """What will really be deleted: things inside a ticked folder ride along with it."""
        return deleter.remove_nested(list(self.items.values()))

    def total(self):
        return sum(e.size for e in self.entries())


# ---------------------------------------------------------------- painting
def pill(p, rect, safety, dim=False, text=None):
    """A rounded safety label, e.g. a green "Safe to delete"."""
    text = text or LABEL.get(safety, "")
    f = QFont(p.font())
    f.setPointSizeF(8.6)
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    w = p.fontMetrics().horizontalAdvance(text) + 30
    h = 20
    r = QRectF(rect.x() + 4, rect.center().y() - h / 2 + 0.5, min(w, rect.width() - 6), h)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    bg = theme.color(safety + "_bg")
    fg = theme.color(safety)
    if dim:
        bg.setAlphaF(0.45)
        fg.setAlphaF(0.55)
    p.setBrush(bg)
    p.drawRoundedRect(r, h / 2, h / 2)
    dot = QRectF(r.x() + 8, r.center().y() - 3, 6, 6)
    p.setBrush(fg)
    p.drawEllipse(dot)
    p.setPen(fg)
    p.drawText(r.adjusted(18, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class PillDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        safety = index.data(SAFETY)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if safety:
            opt.text = ""
        style = opt.widget.style() if opt.widget else None
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)
        if safety:
            p.save()
            pill(p, option.rect, safety, bool(index.data(LOCKED)), index.data(Qt.ItemDataRole.DisplayRole) or None)
            p.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(max(s.width(), 120), max(s.height(), 30))


class SizeDelegate(QStyledItemDelegate):
    """The size, right-aligned, with a thin bar under it showing its share of the folder above."""
    def paint(self, p, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        share = index.data(BAR)
        if share is None:
            return super().paint(p, option, index)
        text = opt.text
        opt.text = ""
        opt.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)
        p.save()
        r = option.rect.adjusted(6, 3, -8, -3)
        p.setPen(theme.color("text"))
        p.drawText(QRectF(r.x(), r.y(), r.width(), r.height() - 7), Qt.AlignmentFlag.AlignRight |
                   Qt.AlignmentFlag.AlignVCenter, text)
        bar = QRectF(r.x(), r.bottom() - 4, r.width(), 4)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color("bar_bg"))
        p.drawRoundedRect(bar, 2, 2)
        if share > 0:
            p.setBrush(theme.color("bar") if share < 0.25 else theme.color("accent"))
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(3.0, bar.width() * min(1.0, share)), 4), 2, 2)
        p.restore()


# ---------------------------------------------------------------- trees with tick boxes
class CheckTree(QTreeWidget):
    """A tree whose rows carry Entries. Ticking a row adds it to the shared Selection; KEEP rows have no box."""
    current_changed = Signal(object)        # the row's entry, a (title, what, safety) tuple, or None

    def __init__(self, selection, headers, pill_col=2, size_col=1):
        super().__init__()
        self.selection = selection
        self._sync = False
        self.setHeaderLabels(headers)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setRootIsDecorated(True)
        self.setAnimated(False)
        self.setIndentation(18)
        self.setItemDelegateForColumn(pill_col, PillDelegate(self))
        self.setItemDelegateForColumn(size_col, SizeDelegate(self))
        self.header().setStretchLastSection(True)
        self.header().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.pill_col, self.size_col = pill_col, size_col
        self.itemChanged.connect(self._changed)
        self.currentItemChanged.connect(lambda cur, _: self.current_changed.emit(self.detail_of(cur)))
        selection.changed.connect(self.refresh_checks)

    @staticmethod
    def detail_of(item):
        if item is None:
            return None
        return item.data(0, ENTRY) or item.data(0, DETAIL)

    def add_entry(self, parent, entry, texts, bar=None):
        """A row for an entry. texts: one string per column (the pill column's text is ignored)."""
        item = QTreeWidgetItem(parent if parent is not None else self, [str(t) for t in texts])
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsAutoTristate)   # a folder's box is its own, not its rows'
        item.setData(0, ENTRY, entry)
        item.setData(self.pill_col, SAFETY, entry.info.safety)
        item.setData(self.pill_col, Qt.ItemDataRole.DisplayRole, "")
        item.setTextAlignment(self.size_col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if bar is not None:
            item.setData(self.size_col, BAR, bar)
        self.set_checkable(item, entry)
        return item

    @staticmethod
    def can_tick(entry):
        return entry.info.safety != KEEP and not entry.locked

    def set_checkable(self, item, entry):
        flags = item.flags()
        if not self.can_tick(entry):
            item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(0, Qt.ItemDataRole.CheckStateRole, None)
            item.setData(self.pill_col, LOCKED, bool(entry.locked))
            why = entry.locked or "Tidy keeps this: " + entry.info.advice
            for c in range(self.columnCount()):
                item.setToolTip(c, why)
            if entry.info.safety == KEEP:
                item.setForeground(0, theme.color("muted"))
        else:
            item.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if self.selection.has(entry.key) else
                               Qt.CheckState.Unchecked)

    def add_group(self, title, what, safety, size_text, extra=""):
        """A header row whose box ticks every row under it that can be ticked."""
        item = QTreeWidgetItem(self, [title, size_text, "", extra])
        f = item.font(0)
        f.setWeight(QFont.Weight.DemiBold)
        item.setFont(0, f)
        item.setData(0, DETAIL, (title, what, safety))
        item.setData(self.pill_col, SAFETY, safety)
        item.setData(self.pill_col, Qt.ItemDataRole.DisplayRole, "")
        item.setTextAlignment(self.size_col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setFlags((item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsAutoTristate)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        return item

    def finish_group(self, item):
        """A group whose rows can't be ticked loses its own box too."""
        if not any(item.child(i).flags() & Qt.ItemFlag.ItemIsUserCheckable for i in range(item.childCount())):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(0, Qt.ItemDataRole.CheckStateRole, None)

    def _changed(self, item, column):
        if self._sync or column != 0:
            return
        entry = item.data(0, ENTRY)
        if entry is None:
            if item.data(0, DETAIL) is not None:
                self.group_toggled(item, item.checkState(0) != Qt.CheckState.Unchecked)
                self.refresh_checks()
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            if self.allow(item, entry):
                self.selection.add(entry)
            else:
                self._sync = True
                item.setCheckState(0, Qt.CheckState.Unchecked)
                self._sync = False
        else:
            self.selection.remove(entry.key)

    def group_toggled(self, group, on):
        for i in range(group.childCount()):
            entry = group.child(i).data(0, ENTRY)
            if entry is None or not self.can_tick(entry):
                continue
            if on:
                self.selection.add(entry)
            else:
                self.selection.remove(entry.key)

    def allow(self, item, entry):
        return True

    def refresh_checks(self):
        """Shows the shared selection: ticked rows, rows inside a ticked folder (ticked and fixed), group boxes."""
        self._sync = True
        folders = {k for k, e in self.selection.items.items() if e.kind == "path"}
        groups = []
        it = QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            it += 1
            entry = item.data(0, ENTRY)
            if entry is None:
                if item.data(0, DETAIL) is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    groups.append(item)
                continue
            if not self.can_tick(entry):
                continue
            covered = folders and entry.kind != "recyclebin" and _inside_any(entry.key, folders)
            flags = item.flags()
            if covered:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setToolTip(0, "Included: the folder it is in is ticked.")
                want = Qt.CheckState.Checked
            else:
                if not flags & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip(0, "")
                want = Qt.CheckState.Checked if self.selection.has(entry.key) else Qt.CheckState.Unchecked
            if item.checkState(0) != want:
                item.setCheckState(0, want)
        for g in groups:
            states = [g.child(i).checkState(0) for i in range(g.childCount())
                      if g.child(i).data(0, ENTRY) is not None and self.can_tick(g.child(i).data(0, ENTRY))]
            on = sum(1 for x in states if x == Qt.CheckState.Checked)
            want = (Qt.CheckState.Unchecked if on == 0 else
                    Qt.CheckState.Checked if on == len(states) else Qt.CheckState.PartiallyChecked)
            if g.checkState(0) != want:
                g.setCheckState(0, want)
        self._sync = False

    def entries(self):
        it = QTreeWidgetItemIterator(self)
        while it.value():
            entry = it.value().data(0, ENTRY)
            if entry is not None:
                yield it.value(), entry
            it += 1


def _inside_any(key, folders):
    """True when a ticked folder holds this path."""
    p = key
    while True:
        parent = os.path.dirname(p)
        if parent == p or not parent:
            return False
        if parent in folders:
            return True
        p = parent


# ---------------------------------------------------------------- detail panel
def label(text="", name=None, wrap=True):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


class PillLabel(QWidget):
    def __init__(self):
        super().__init__()
        self.safety = None
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, safety):
        self.safety = safety
        self.setVisible(bool(safety))
        self.update()

    def paintEvent(self, event):
        if self.safety:
            p = QPainter(self)
            pill(p, self.rect().adjusted(-4, 0, 0, 0), self.safety)


class DetailPanel(QFrame):
    """The right-hand "About this" panel: what the selected thing is, and whether it can go."""
    def __init__(self):
        super().__init__()
        self.setObjectName("detail")
        self.setFixedWidth(320)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(8)
        self.kicker = label("ABOUT THIS ITEM", "faint")
        self.title = label("", "h2")
        self.pill = PillLabel()
        self.facts = label("", "faint")
        self.what_h = label("What is it?", "muted")
        self.what = label()
        self.adv_h = label("Can I delete it?", "muted")
        self.advice = label()
        self.path = label("", "faint")
        self.path.setTextFormat(Qt.TextFormat.PlainText)
        self.action = QPushButton()
        self.action.setObjectName("primary")
        self.reveal = QPushButton("Show in File Explorer")
        self.action.clicked.connect(self._action)
        self.reveal.clicked.connect(lambda: self.current_path and winapi.reveal(self.current_path))
        for w in (self.kicker, self.title, self.pill, self.facts, self.what_h, self.what, self.adv_h, self.advice,
                  self.path):
            lay.addWidget(w)
        lay.addSpacing(6)
        lay.addWidget(self.action)
        lay.addWidget(self.reveal)
        lay.addStretch(1)
        self.empty = label("Click any item to see what it is and whether it is safe to delete.", "muted")
        lay.addWidget(self.empty)
        self.current_path = ""
        self.uri = ""
        self.show_item(None)

    def _action(self):
        if self.uri:
            winapi.open_uri(self.uri)

    def show_item(self, item):
        widgets = (self.kicker, self.title, self.pill, self.facts, self.what_h, self.what, self.adv_h, self.advice,
                   self.path, self.action, self.reveal)
        for w in widgets:
            w.setVisible(item is not None)
        self.empty.setVisible(item is None)
        self.current_path = ""
        self.uri = ""
        if item is None:
            return
        if isinstance(item, tuple):             # a group header, or a running app (with its own advice)
            title, what, safety = item[:3]
            self.title.setText(title)
            self.pill.set(safety)
            self.what.setText(what)
            self.advice.setText({"safe": "Everything in this group is safe to delete. Tick the group to select it "
                                         "all, or open it to pick.",
                                 "choice": "Look at each item: only you know if you still need it.",
                                 "keep": "Tidy keeps these."}.get(safety, "") if len(item) < 4 else item[3])
            self.what_h.setText("What is it?")
            for w in (self.facts, self.path, self.action, self.reveal):
                w.hide()
            return
        e = item
        info = e.info
        if e.kind == "path" and info.title.lower() != e.name.lower():
            self.title.setText(e.name)
            self.what_h.setText("What is it?  (" + info.title + ")")
        else:
            self.title.setText(e.name if e.kind == "path" else info.title)
            self.what_h.setText("What is it?")
        self.pill.set(info.safety)
        facts = [theme.size_text(e.size)]
        if e.count:
            facts.append("%s files" % format(e.count, ","))
        if e.kind == "contents":
            facts.append("the folder stays, its contents go")
        if e.older_than:
            facts.append("only files older than %d hours" % round((time.time() - e.older_than) / 3600))
        if e.path and os.path.lexists(e.path):
            try:
                facts.append("changed " + theme.age_text(os.lstat(e.path).st_mtime))
            except OSError:
                pass
        self.facts.setText("  ·  ".join(facts))
        self.what.setText(info.what + ("\n\n" + e.note if e.note else ""))
        advice = info.advice
        if e.locked:
            advice = e.locked + ". " + advice
        self.advice.setText(advice)
        self.path.setText(e.path)
        self.path.setVisible(bool(e.path))
        self.current_path = e.path
        self.reveal.setVisible(bool(e.path) and os.path.lexists(e.path))
        if info.action:
            self.action.setText(info.action[0])
            self.uri = info.action[1]
        else:
            self.action.hide()


def card():
    f = QFrame()
    f.setObjectName("card")
    return f


def hbox(*widgets, spacing=8, margins=(0, 0, 0, 0)):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for x in widgets:
        if x is None:
            lay.addStretch(1)
        elif isinstance(x, int):
            lay.addSpacing(x)
        else:
            lay.addWidget(x)
    return w


def button(text, name=None, slot=None):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if slot:
        b.clicked.connect(slot)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


__all__ = ["Selection", "CheckTree", "DetailPanel", "ENTRY", "SAFETY", "BAR", "DETAIL", "pill", "label", "card",
           "hbox", "button", "knowledge"]
