"""The Speed up page: Game Boost, a checkup with one-click fixes, startup apps, graphics card per game, and what
Tidy deliberately won't do. Every change here can be undone here."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                               QMessageBox, QScrollArea, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import optimize, winapi
from ..knowledge import CHOICE, KEEP, SAFE
from . import theme
from .common import SAFETY, PillDelegate, button, card, hbox, label, pill
from .memory_page import Job
from .pages import Page

STATUS_PILL = {optimize.GOOD: (SAFE, "Good"), optimize.IMPROVE: (CHOICE, "Can improve"),
               optimize.INFO: ("info", "Optional")}
STARTUP_PILL = {SAFE: "Safe to turn off", CHOICE: "Your choice", KEEP: "Keep on"}
PREF_TEXT = {0: "Windows decides", 1: "Power saving", 2: "Fast graphics card"}
ITEM = Qt.ItemDataRole.UserRole + 30


class Pill(QWidget):
    def __init__(self, key, text, width=124):
        super().__init__()
        self.key, self.text = key, text
        self.setFixedSize(width, 26)

    def paintEvent(self, event):
        pill(QPainter(self), self.rect().adjusted(-4, 0, 0, 0), self.key, text=self.text)


def section(title, subtitle=""):
    c = card()
    lay = QVBoxLayout(c)
    lay.setContentsMargins(20, 16, 20, 18)
    lay.setSpacing(10)
    lay.addWidget(label(title, "h2"))
    if subtitle:
        lay.addWidget(label(subtitle, "muted"))
    return c, lay


class SpeedPage(Page):
    go = Signal(int)
    admin_requested = Signal()

    def __init__(self, settings):
        super().__init__("Speed up", "Changes that really help games and everyday use, and nothing risky. Every "
                                     "change Tidy makes here can be undone here.")
        self.s = settings
        self.jobs = []
        self.data = None
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("page")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 6, 10, 10)
        self.body.setSpacing(14)
        scroll.setWidget(body)
        self.lay.addWidget(scroll, 1)

        # Game Boost
        boost, bl = section("Game Boost", "One click before you play: best-performance power, closes the apps you "
                                          "tick below, and hands back unused memory. Stop it when you're done to "
                                          "put your power setting back. Closed apps stay closed until you open "
                                          "them.")
        self.boost_state = label("", "muted")
        self.boost_btn = button("Start Game Boost", "primary", self.toggle_boost)
        self.boost_btn.setMinimumHeight(38)
        bl.addWidget(hbox(self.boost_btn, 10, self.boost_state, None))
        bl.addWidget(label("Close these while I play (only apps you can safely close are listed):", "muted"))
        self.boost_list = QListWidget()
        self.boost_list.setMinimumHeight(150)
        self.boost_list.setMaximumHeight(210)
        self.boost_list.itemChanged.connect(self._boost_ticks)
        bl.addWidget(self.boost_list)
        self.body.addWidget(boost)

        # Checkup
        check, cl = section("Checkup", "Each setting with how it is now, what it does, and a one-click fix.")
        self.check_rows = QVBoxLayout()
        self.check_rows.setSpacing(0)
        cl.addLayout(self.check_rows)
        self.undo_all_btn = button("Undo every change Tidy made", None, self.undo_all)
        cl.addWidget(hbox(None, self.undo_all_btn))
        self.body.addWidget(check)

        # Startup apps
        start, sl = section("Startup apps", "Apps that open by themselves when Windows starts. Each one makes "
                                            "startup slower and uses memory in the background. Untick to stop it "
                                            "starting; it still opens normally when you click it.")
        self.start_info = label("", "muted", wrap=False)
        sl.addWidget(hbox(self.start_info, None, button("Turn off all green ones", None, self.startup_off_safe)))
        self.start_tree = QTreeWidget()
        self.start_tree.setHeaderLabels(["Starts with Windows", "Safety", "From", "What it is"])
        self.start_tree.setRootIsDecorated(False)
        self.start_tree.setItemDelegateForColumn(1, PillDelegate(self.start_tree))
        for col, w in enumerate((260, 150, 190)):
            self.start_tree.setColumnWidth(col, w)
        self.start_tree.setMinimumHeight(320)
        self.start_tree.itemChanged.connect(self._startup_changed)
        sl.addWidget(self.start_tree)
        self.body.addWidget(start)

        # graphics card per game
        self.gpu_card, gl = section("Graphics card for games", "Your PC has two graphics chips: a power-saving one "
                                    "built into the processor and a fast one. Sometimes Windows starts a game on the "
                                    "slow one. Tick a game to always give it the fast one (the same setting as "
                                    "Settings > System > Display > Graphics).")
        self.gpu_tree = QTreeWidget()
        self.gpu_tree.setHeaderLabels(["Game", "Store", "Uses now", "Program"])
        self.gpu_tree.setRootIsDecorated(False)
        for col, w in enumerate((260, 100, 170)):
            self.gpu_tree.setColumnWidth(col, w)
        self.gpu_tree.setMinimumHeight(220)
        self.gpu_tree.itemChanged.connect(self._gpu_changed)
        gl.addWidget(hbox(button("Use the fast card for every game", None, self.gpu_all),
                          button("Add a game...", None, self.add_game), None))
        gl.addWidget(self.gpu_tree)
        self.body.addWidget(self.gpu_card)

        # what Tidy won't do
        wont, wl = section("What Tidy won't do, and why", "Many 'PC boosters' do these. They sound good but give "
                                                         "little or nothing, and some break your PC later.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for i, (title, why) in enumerate(optimize.WONT_DO):
            t = label(title, wrap=False)
            f = t.font()
            f.setBold(True)
            t.setFont(f)
            grid.addWidget(t, i, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(label(why, "muted"), i, 1)
        grid.setColumnStretch(1, 1)
        wl.addLayout(grid)
        self.body.addWidget(wont)
        self.body.addStretch(1)
        self._sync = False

    # ---------------------------------------------------------------- loading
    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def _run(self, fn, done, *args):
        job = Job(fn, *args)
        job.result.connect(done)
        job.finished.connect(lambda: self.jobs.remove(job) if job in self.jobs else None)
        self.jobs.append(job)
        job.start()

    def refresh(self):
        if any(j.fn is _load for j in self.jobs):
            return
        self._run(_load, self._show, self.s)

    def _show(self, data):
        if isinstance(data, Exception):
            return
        self.data = data
        self._show_checks(data["checks"])
        self._show_startup(data["startup"])
        self._show_games(data["games"], data["two_gpus"])
        self._show_boost(data["boost"])

    # ---------------------------------------------------------------- checkup
    def _show_checks(self, checks):
        while self.check_rows.count():
            w = self.check_rows.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for c in checks:
            self.check_rows.addWidget(self._check_row(c))
        changes = optimize.Changes(self.s).all()
        self.undo_all_btn.setVisible(bool(changes))

    def _check_row(self, c):
        row = QFrame()
        lay = QGridLayout(row)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setHorizontalSpacing(14)
        lay.setVerticalSpacing(2)
        key, text = STATUS_PILL[c.status]
        lay.addWidget(Pill(key, text), 0, 0, Qt.AlignmentFlag.AlignTop)
        title = label(c.title, wrap=False)
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(hbox(title, 8, label(c.summary, "muted", wrap=False), None), 0, 1)
        lay.addWidget(label(c.what, "muted"), 1, 1)
        buttons = []
        if c.action:
            buttons.append(button(c.action, "primary", lambda _=False, cid=c.id, goto=c.goto: self.fix(cid, goto)))
        for text, url in c.links:
            buttons.append(button(text, None, lambda _=False, u=url: winapi.open_uri(u)))
        if c.undo:
            buttons.append(button("Undo", "link", lambda _=False, cid=c.id: self.undo(cid)))
        if buttons:
            lay.addWidget(hbox(*buttons), 0, 2, 2, 1, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        lay.setColumnStretch(1, 1)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: %s;" % theme.current["border"])
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(row)
        wl.addWidget(line)
        return wrap

    def fix(self, cid, goto=""):
        if goto == "junk":
            self.go.emit(1)
            return
        if cid == "power" and optimize.on_battery():
            QMessageBox.information(self, "Tidy", "You're on battery. Best performance drains it faster; plug in "
                                    "the charger when you play.")
        if not optimize.apply(cid, self.s):
            QMessageBox.warning(self, "Tidy", "Windows didn't accept that change.")
        self.refresh()

    def undo(self, cid):
        optimize.undo(cid, self.s)
        self.refresh()

    def undo_all(self):
        if QMessageBox.question(self, "Tidy", "Put back every setting Tidy changed (power, Game Mode, recording, "
                                "mouse, effects, startup apps and graphics card choices)?") != \
                QMessageBox.StandardButton.Yes:
            return
        if self.s.get("boost_on"):
            optimize.stop_boost(self.s)
        optimize.undo_all(self.s)
        self.refresh()

    # ---------------------------------------------------------------- startup apps
    def _show_startup(self, items):
        self._sync = True
        self.start_tree.clear()
        on = 0
        for it in items:
            row = QTreeWidgetItem(self.start_tree, [it.title, STARTUP_PILL[it.safety], it.source, it.what])
            row.setData(0, ITEM, it)
            row.setData(1, SAFETY, it.safety)
            row.setFlags((row.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsAutoTristate)
            row.setCheckState(0, Qt.CheckState.Checked if it.enabled else Qt.CheckState.Unchecked)
            tip = it.advice + ("\n\n" + it.command if it.command else "")
            if it.locked:
                row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                tip = it.locked + " (restart Tidy as administrator to change it). " + tip
                row.setForeground(0, theme.color("muted"))
            for col in range(4):
                row.setToolTip(col, tip)
            on += it.enabled
        self.start_info.setText("%d of %d start with Windows." % (on, len(items)))
        self._sync = False

    def _startup_changed(self, row, col):
        if self._sync or col != 0:
            return
        it = row.data(0, ITEM)
        want = row.checkState(0) == Qt.CheckState.Checked
        if it.safety == KEEP and not want:
            self._sync = True
            row.setCheckState(0, Qt.CheckState.Checked)
            self._sync = False
            QMessageBox.information(self, "Tidy", "%s\n\n%s" % (it.title, it.advice))
            return
        try:
            optimize.set_startup(it, want, self.s)
        except OSError:
            self._sync = True
            row.setCheckState(0, Qt.CheckState.Checked if it.enabled else Qt.CheckState.Unchecked)
            self._sync = False
            QMessageBox.warning(self, "Tidy", "Windows didn't allow that change. Restart Tidy as administrator.")
            return
        items = [self.start_tree.topLevelItem(i).data(0, ITEM) for i in range(self.start_tree.topLevelItemCount())]
        self.start_info.setText("%d of %d start with Windows." % (sum(i.enabled for i in items), len(items)))

    def startup_off_safe(self):
        for i in range(self.start_tree.topLevelItemCount()):
            row = self.start_tree.topLevelItem(i)
            it = row.data(0, ITEM)
            if it.safety == SAFE and it.enabled and not it.locked:
                row.setCheckState(0, Qt.CheckState.Unchecked)

    # ---------------------------------------------------------------- graphics card per game
    def _show_games(self, games, two):
        self.gpu_card.setVisible(two)
        self._sync = True
        self.gpu_tree.clear()
        for g in games:
            row = QTreeWidgetItem(self.gpu_tree, [g.name, g.store, PREF_TEXT.get(g.preference, "Windows decides"),
                                                  g.exe])
            row.setData(0, ITEM, g)
            row.setFlags((row.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsAutoTristate)
            row.setCheckState(0, Qt.CheckState.Checked if g.preference == 2 else Qt.CheckState.Unchecked)
            row.setToolTip(3, g.exe)
        self._sync = False

    def _gpu_changed(self, row, col):
        if self._sync or col != 0:
            return
        g = row.data(0, ITEM)
        fast = row.checkState(0) == Qt.CheckState.Checked
        ch = optimize.Changes(self.s)
        tid = "gpu:" + g.exe.lower()
        if fast:
            optimize.set_gpu_preference(g.exe, 2, self.s)
        elif ch.has(tid):
            ch.undo(tid)                     # back to what it was before Tidy touched it
        else:
            optimize.set_gpu_preference(g.exe, 0, self.s)
        g.preference = optimize.gpu_preference(g.exe)
        self._sync = True
        row.setText(2, PREF_TEXT.get(g.preference, "Windows decides"))
        row.setCheckState(0, Qt.CheckState.Checked if g.preference == 2 else Qt.CheckState.Unchecked)
        self._sync = False

    def gpu_all(self):
        for i in range(self.gpu_tree.topLevelItemCount()):
            self.gpu_tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked)

    def add_game(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the game's program", "", "Programs (*.exe)")
        if not path:
            return
        path = os.path.normpath(path)
        optimize.set_gpu_preference(path, 2, self.s)
        extra = list(self.s.get("extra_games") or [])
        if path not in extra:
            extra.append(path)
            self.s.set("extra_games", extra)
        self.refresh()

    # ---------------------------------------------------------------- Game Boost
    def _show_boost(self, apps):
        on = bool(self.s.get("boost_on"))
        self.boost_btn.setText("Stop Game Boost" if on else "Start Game Boost")
        if not self.boost_state.text() or not on:
            self.boost_state.setText("On: power is set for best performance." if on else "Off")
        chosen = self.s.get("boost_close")
        self._sync = True
        self.boost_list.clear()
        for a in apps:
            item = QListWidgetItem("%s  ·  %s%s" % (a.title, theme.size_text(a.memory),
                                                    "" if a.windows else "  ·  in the background"))
            item.setData(ITEM, a.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            ticked = a.name in chosen if chosen is not None else a.safety == SAFE
            item.setCheckState(Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked)
            item.setToolTip(a.advice)
            self.boost_list.addItem(item)
        self._sync = False

    def _boost_ticks(self, _item):
        if self._sync:
            return
        names = [self.boost_list.item(i).data(ITEM) for i in range(self.boost_list.count())
                 if self.boost_list.item(i).checkState() == Qt.CheckState.Checked]
        self.s.set("boost_close", names)

    def toggle_boost(self):
        if self.s.get("boost_on"):
            optimize.stop_boost(self.s)
            self.boost_state.setText("Off. Your power setting is back to how it was.")
            self.refresh()
            return
        names = [self.boost_list.item(i).data(ITEM) for i in range(self.boost_list.count())
                 if self.boost_list.item(i).checkState() == Qt.CheckState.Checked]
        self.boost_btn.setEnabled(False)
        self.boost_state.setText("Boosting...")
        self._run(optimize.start_boost, self._boosted, self.s, names)

    def _boosted(self, result):
        self.boost_btn.setEnabled(True)
        if isinstance(result, Exception):
            self.boost_state.setText("Something went wrong: %s" % result)
        else:
            parts = ["On: best-performance power"]
            if result["closed"]:
                parts.append("closed %d app%s" % (len(result["closed"]), "" if len(result["closed"]) == 1 else "s"))
            if result["freed"] > 0:
                parts.append("%s more memory free" % theme.size_text(result["freed"]))
            text = ", ".join(parts) + "."
            if result["left"]:
                text += " Still open (may be asking to save): " + ", ".join(result["left"]) + "."
            self.boost_state.setText(text)
        self.refresh()

    def stop(self):
        for j in list(self.jobs):
            j.wait(3000)


def _load(settings):
    games = optimize.find_games()
    known = {g.exe.lower() for g in games}
    for exe in settings.get("extra_games") or []:
        if os.path.isfile(exe) and exe.lower() not in known:
            games.append(optimize.Game(os.path.splitext(os.path.basename(exe))[0], exe, "Added by you",
                                       optimize.gpu_preference(exe)))
    return {"checks": optimize.checks(settings), "startup": optimize.startup_items(), "games": games,
            "two_gpus": optimize.two_gpus(), "boost": optimize.boost_candidates()}


__all__ = ["SpeedPage", "QHBoxLayout"]
