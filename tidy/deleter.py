"""Deletes what the person ticked, either to the Recycle Bin or permanently.

The last line of defence: every item is checked again here, whatever page it came from. Tidy refuses drive roots,
anything knowledge marks KEEP, and its own files. Junctions and links are removed as links; their targets are never
followed. Files in use are skipped and reported, never forced.
"""
import logging
import os
import stat
import sys
import time
from dataclasses import dataclass, field

from . import knowledge, winapi
from .knowledge import KEEP

log = logging.getLogger("tidy.delete")


@dataclass
class Report:
    freed: int = 0              # bytes removed from disk (permanent) or moved to the Recycle Bin
    done: int = 0               # items fully handled
    files: int = 0              # files removed
    failed: list = field(default_factory=list)      # (path, reason)
    finished: list = field(default_factory=list)    # (entry, bytes) for the pages to update
    permanent: bool = False
    cancelled: bool = False


def _own_dirs():
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    return [knowledge.norm(here)]


def refuse(entry):
    """Why this entry must not be deleted, or "" when it may."""
    if entry.kind == "recyclebin":
        return ""
    path = entry.path
    if not path or not os.path.isabs(path):
        return "Not a full path."
    p = knowledge.norm(path)
    if len(p) <= 3 or knowledge.zone(path) == "root":
        return "Tidy never deletes a whole drive."
    if not os.path.lexists(path):
        return "Already gone."
    info = knowledge.explain(path, os.path.isdir(path))
    if entry.origin == "leftover":
        from . import leftovers             # leftovers live in program places on purpose: check them their own way
        why = leftovers.verify(path)
        if why:
            return why
    elif info.safety == KEEP:
        return "Tidy keeps this: %s." % info.title
    if entry.kind == "path" and info.keep_folder and os.path.isdir(path) and entry.origin != "leftover":
        return "This folder must stay; only its contents can go."
    for own in _own_dirs():
        if p == own or own.startswith(p + "\\") or p.startswith(own + "\\"):
            return "This is part of Tidy itself."
    return ""


def _long(path):
    path = os.path.abspath(path)
    if os.name != "nt" or path.startswith("\\\\"):
        return path
    return "\\\\?\\" + path


def _is_link(entry):
    try:
        return entry.is_symlink() or entry.is_junction()
    except OSError:
        return False


def _unlink(path):
    try:
        os.unlink(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)            # read-only files
        os.unlink(path)


class _Run:
    def __init__(self, report, progress, cancelled):
        self.r, self.progress, self.cancelled = report, progress, cancelled
        self.last = 0.0

    def tick(self, path):
        now = time.monotonic()
        if self.progress and now - self.last > 0.08:
            self.last = now
            self.progress(path)

    def fail(self, path, err):
        reason = _reason(err)
        self.r.failed.append((path, reason))
        log.info("skipped %s: %s", path, reason)

    # ---- permanent
    def remove_tree(self, path, older_than=None, keep_top=False):
        """Deletes a folder's files bottom-up, then the folders that became empty. Returns bytes freed."""
        freed = 0
        try:
            entries = list(os.scandir(_long(path)))
        except OSError as e:
            self.fail(path, e)
            return 0
        for e in entries:
            if self.cancelled():
                return freed
            shown = os.path.join(path, e.name)
            self.tick(shown)
            try:
                if _is_link(e):
                    if older_than is None:          # a link: remove the link itself, never what it points to
                        (os.rmdir if e.is_dir(follow_symlinks=False) else os.unlink)(e.path)
                    continue
                if e.is_dir(follow_symlinks=False):
                    # a folder changed in the last hours may belong to a program running right now: empty its old
                    # files but leave the folder itself
                    young = older_than is not None and e.stat(follow_symlinks=False).st_mtime > older_than
                    freed += self.remove_tree(shown, older_than, keep_top=young)
                    continue
                st = e.stat(follow_symlinks=False)
                if older_than is not None and st.st_mtime > older_than:
                    continue
                _unlink(e.path)
                freed += st.st_size
                self.r.files += 1
            except OSError as err:
                self.fail(shown, err)
        if not keep_top:
            try:
                os.rmdir(_long(path))
            except OSError:
                pass                                 # not empty: something inside was in use or too new
        return freed

    # ---- Recycle Bin
    def recycle_contents(self, path, older_than=None):
        freed = 0
        try:
            entries = list(os.scandir(path))
        except OSError as e:
            self.fail(path, e)
            return 0
        for e in entries:
            if self.cancelled():
                break
            self.tick(e.path)
            try:
                if _is_link(e):
                    continue
                if e.is_dir(follow_symlinks=False):
                    size, newest = _measure(e.path)
                    if older_than is not None and newest > older_than:
                        continue
                else:
                    st = e.stat(follow_symlinks=False)
                    if older_than is not None and st.st_mtime > older_than:
                        continue
                    size = st.st_size
            except OSError as err:
                self.fail(e.path, err)
                continue
            why = winapi.to_recycle_bin(e.path)
            if why:
                self.r.failed.append((e.path, why))
            else:
                freed += size
                self.r.files += 1
        return freed


def _measure(path):
    """(bytes, newest change time) of a folder."""
    total, newest = 0, 0.0
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if _is_link(e):
                            continue
                        st = e.stat(follow_symlinks=False)
                        newest = max(newest, st.st_mtime)
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += st.st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total, newest


def _reason(err):
    if isinstance(err, PermissionError):
        win = getattr(err, "winerror", None)
        if win == 32:
            return "In use by another program."
        return "In use, or Windows didn't allow it."
    if isinstance(err, FileNotFoundError):
        return "Already gone."
    return str(getattr(err, "strerror", None) or err)


def remove_nested(entries):
    """Drops entries that sit inside another ticked folder (that folder takes them along)."""
    paths = sorted({knowledge.norm(e.path) for e in entries if e.kind == "path" and e.path})
    out = []
    for e in entries:
        if e.kind == "recyclebin":
            out.append(e)
            continue
        p = knowledge.norm(e.path)
        if any(p != q and p.startswith(q.rstrip("\\") + "\\") for q in paths):
            continue
        out.append(e)
    return out


def delete(entries, permanent, progress=None, cancelled=lambda: False):
    """Deletes the entries. progress(path) is called now and then. Returns a Report."""
    report = Report(permanent=permanent)
    run = _Run(report, progress, cancelled)
    for entry in remove_nested(entries):
        if cancelled():
            report.cancelled = True
            break
        why = refuse(entry)
        if why:
            if why != "Already gone.":
                report.failed.append((entry.path or entry.name, why))
            log.info("refused %s: %s", entry.path, why)
            continue
        freed = 0
        path = entry.path
        log.info("%s %s %s", "delete" if permanent else "recycle", entry.kind, path or "Recycle Bin")
        if entry.kind == "recyclebin":
            if winapi.empty_recycle_bin():
                freed = entry.size
            else:
                report.failed.append(("Recycle Bin", "Windows couldn't empty it."))
        elif entry.kind == "contents":
            if permanent or not winapi.recycle_bin_works(path):
                freed = run.remove_tree(path, entry.older_than, keep_top=True)
            else:
                freed = run.recycle_contents(path, entry.older_than)
        elif os.path.isdir(path) and not os.path.islink(path):
            if permanent or not winapi.recycle_bin_works(path):
                freed = run.remove_tree(path)
            else:
                size, _ = _measure(path)
                why = winapi.to_recycle_bin(path)
                if why:
                    report.failed.append((path, why))
                else:
                    freed = size
        else:
            run.tick(path)
            try:
                size = os.lstat(path).st_size
                if permanent or not winapi.recycle_bin_works(path):
                    _unlink(_long(path))
                    why = ""
                else:
                    why = winapi.to_recycle_bin(path)
                if why:
                    report.failed.append((path, why))
                else:
                    freed = size
                    report.files += 1
            except OSError as err:
                run.fail(path, err)
        report.freed += freed
        report.finished.append((entry, freed))
        report.done += 1
    log.info("finished: %d items, %d bytes %s, %d skipped", report.done, report.freed,
             "freed" if permanent else "to the Recycle Bin", len(report.failed))
    return report
