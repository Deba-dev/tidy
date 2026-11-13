"""Scanning and deleting run on background threads so the window never freezes."""
import logging
import os
import time

from PySide6.QtCore import QThread, Signal

from .. import deleter, duplicates, junk, knowledge, leftovers, scanner, winapi

log = logging.getLogger("tidy")


class State:
    """Everything one scan found."""
    def __init__(self):
        self.junk = []              # [junk.Group]
        self.scan = None            # scanner.ScanResult
        self.dups = []              # [duplicates.DupGroup]
        self.leftovers = []         # [junk.Group] from leftovers.find()
        self.drives = []            # [winapi.Drive] at scan time
        self.finished_at = 0.0


class ScanWorker(QThread):
    progress = Signal(str, str, float)      # phase, detail line, 0..1 (or -1 when unknown)
    done = Signal(object)                   # State

    def __init__(self, roots, settings):
        super().__init__()
        self.roots = roots
        self.s = settings
        self.stop = False
        self.used = sum(d.used for d in winapi.drives() if d.root in roots) or 1

    def run(self):
        state = State()
        cancelled = lambda: self.stop  # noqa: E731
        try:
            self.progress.emit("Looking for junk", "", -1)
            state.junk = junk.find(int(self.s.get("temp_hours")), int(self.s.get("installer_days")), cancelled,
                                   lambda p: self.progress.emit("Looking for junk", p, -1))
            if not self.stop:
                state.leftovers = leftovers.find(cancelled, lambda p: self.progress.emit(
                    "Looking for leftovers of removed programs", p, -1))
            if not self.stop:
                def scan_progress(files, size, path):
                    self.progress.emit("Mapping your drives", "%s files  ·  %s" % (format(files, ","), path),
                                       min(0.99, size / self.used))
                state.scan = scanner.scan(self.roots, int(self.s.get("large_mb")) * 1024 * 1024, scan_progress,
                                          cancelled)
            if not self.stop and state.scan is not None:
                def dup_progress(done, total, path):
                    self.progress.emit("Finding duplicate files", path, done / total if total else -1)
                state.dups = duplicates.find(state.scan.dup_candidates, dup_progress, cancelled)
        except Exception:                                   # a scan must never take the app down
            log.exception("scan failed")
        state.drives = winapi.drives()
        state.finished_at = time.time()
        if self.stop and state.scan is not None:
            state.scan.cancelled = True
        self.done.emit(state)


class DeleteWorker(QThread):
    progress = Signal(str)
    done = Signal(object, dict)             # Report, {entry key: new size} for folders that were emptied

    def __init__(self, entries, permanent):
        super().__init__()
        self.entries = entries
        self.permanent = permanent
        self.stop = False

    def run(self):
        sizes = {}
        try:
            report = deleter.delete(self.entries, self.permanent, self.progress.emit, lambda: self.stop)
            for entry, _ in report.finished:
                if entry.kind == "contents" and os.path.isdir(entry.path):
                    sizes[entry.key] = scanner.folder_size(entry.path, entry.older_than)[0]
        except Exception as e:                              # report it instead of crashing
            log.exception("delete failed")
            report = deleter.Report(permanent=self.permanent)
            report.failed.append(("", "Something went wrong: %s" % e))
        self.done.emit(report, sizes)


def apply_report(state, report, sizes):
    """Updates what the pages show after a delete, without a new scan."""
    gone = set()
    for entry, freed in report.finished:
        key = entry.key
        if entry.kind == "recyclebin":
            gone.add(key)
            continue
        if entry.kind == "contents":
            new = sizes.get(key, 0)
            if state.scan is not None:
                state.scan.shrink(entry.path, entry.size - new)
            entry.size = new
            if new <= 0:
                gone.add(key)
            continue
        if not os.path.lexists(entry.path):
            gone.add(key)
            if state.scan is not None:
                state.scan.forget(entry.path, entry.size)
    for g in state.junk:
        g.entries = [e for e in g.entries if e.key not in gone and e.size > 0]
    state.junk = [g for g in state.junk if g.entries]
    for g in state.leftovers:
        g.entries = [e for e in g.entries if e.key not in gone and os.path.lexists(e.path)]
    state.leftovers = [g for g in state.leftovers if g.entries]
    if not report.permanent:                    # the Recycle Bin grew
        size, count = winapi.recycle_bin_size()
        bin_group = next((g for g in state.junk if g.id == "recyclebin"), None)
        if size > 0:
            info = knowledge.known(os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "$Recycle.Bin"))
            entry = junk.Entry("", "recyclebin", size, info, count)
            if bin_group is None:
                state.junk.insert(0, junk.Group("recyclebin", "Recycle Bin", "Files you deleted before. They still "
                                                "use space until the bin is emptied.", knowledge.SAFE, [entry]))
            else:
                bin_group.entries = [entry]
    for g in state.dups:
        g.paths = [p for p in g.paths if os.path.lexists(p)]
    state.dups = [g for g in state.dups if len(g.paths) > 1]
    state.drives = winapi.drives()
    return gone
