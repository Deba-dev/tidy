"""Walks whole drives fast and remembers how big every folder is.

Only folders are kept in memory (files are listed again, one folder at a time, when the person opens a folder in the
Space map), so even a drive with a million files fits. Junctions and symbolic links are never followed: they point at
folders that are counted elsewhere (and some loop forever). OneDrive files that live only in the cloud count as 0
bytes on this PC and are never read.
"""
import heapq
import os
import time

from . import knowledge
from .winapi import ONLINE_ONLY

DUP_MIN = 1024 * 1024                   # duplicates smaller than 1 MB are not worth anyone's time
DUP_SKIP = {"node_modules", ".git", "site-packages", "__pycache__", "steamapps", "$recycle.bin", ".venv", "venv",
            "windowsapps", "appdata", "program files", "program files (x86)", "programdata", "windows"}
DUP_SKIP_EXT = {".dll", ".sys", ".pyd", ".so", ".lnk", ".ini", ".dat", ".db", ".pak"}


class DirNode:
    __slots__ = ("name", "parent", "size", "own", "files", "dirs", "mtime", "denied", "gone")

    def __init__(self, name, parent):
        self.name = name
        self.parent = parent
        self.size = 0           # everything inside, sub-folders included
        self.own = 0            # files directly in this folder
        self.files = 0          # number of files inside, sub-folders included
        self.dirs = []
        self.mtime = 0.0
        self.denied = False     # Windows didn't let us look inside
        self.gone = False       # deleted by Tidy since the scan

    @property
    def path(self):
        names = []
        node = self
        while node is not None:
            names.append(node.name)
            node = node.parent
        names.reverse()
        return os.path.join(*names) if names else ""

    def child(self, name):
        low = name.lower()
        for d in self.dirs:
            if d.name.lower() == low:
                return d
        return None


class ScanResult:
    def __init__(self):
        self.roots = []                 # one DirNode per drive
        self.large = []                 # (size, path, mtime) of big files, largest first
        self.dup_candidates = {}        # size -> [path, ...]
        self.files = 0
        self.dirs = 0
        self.bytes = 0
        self.denied = 0
        self.online_only = 0
        self.seconds = 0.0
        self.cancelled = False

    def find(self, path):
        """The DirNode for a folder path, or None."""
        p = knowledge.norm(path)
        for root in self.roots:
            r = knowledge.norm(root.name)
            if p == r:
                return root
            if p.startswith(r.rstrip("\\") + "\\"):
                node = root
                for part in p[len(r.rstrip("\\")) + 1:].split("\\"):
                    node = node.child(part)
                    if node is None:
                        return None
                return node
        return None

    def shrink(self, path, size):
        """After Tidy emptied a folder that stays: take what went off it and every folder above it."""
        node = self.find(path)
        if node is None or size <= 0:
            return
        node.dirs = [d for d in node.dirs if os.path.isdir(os.path.join(path, d.name))]
        above = node
        while above is not None:
            above.size = max(0, above.size - size)
            above = above.parent
        node.own = max(0, node.size - sum(d.size for d in node.dirs))

    def forget(self, path, size):
        """After Tidy deleted something: take its size off every folder above it."""
        node = self.find(path)
        if node is not None and node.parent is not None:
            node.gone = True
            node.parent.dirs = [d for d in node.parent.dirs if d is not node]
            above = node.parent
        else:
            above = self.find(os.path.dirname(path))
            if above is not None:
                above.own = max(0, above.own - size)
        while above is not None:
            above.size = max(0, above.size - size)
            above = above.parent
        self.large = [x for x in self.large if not _inside(x[1], path)]


def _inside(child, parent):
    c, p = knowledge.norm(child), knowledge.norm(parent)
    return c == p or c.startswith(p.rstrip("\\") + "\\")


def scan(roots, large_min=100 * 1024 * 1024, progress=None, cancelled=lambda: False, large_keep=500):
    """Scans each root folder. progress(files, bytes, path) is called a few times a second."""
    res = ScanResult()
    start = time.monotonic()
    last = 0.0
    large = []                          # min-heap of (size, path, mtime)
    order = []                          # every DirNode, parents before children
    for root in roots:
        top = DirNode(os.path.abspath(root), None)
        res.roots.append(top)
        stack = [(top, top.name, _dup_ok(top.name))]
        while stack:
            if cancelled():
                res.cancelled = True
                break
            node, path, dup_ok = stack.pop()
            order.append(node)
            try:
                it = os.scandir(path)
            except OSError:
                node.denied = True
                res.denied += 1
                continue
            with it:
                while True:
                    try:
                        entry = next(it)
                    except StopIteration:
                        break
                    except OSError:
                        node.denied = True
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.is_symlink() or entry.is_junction():
                                continue
                            sub = DirNode(entry.name, node)
                            try:
                                sub.mtime = entry.stat(follow_symlinks=False).st_mtime
                            except OSError:
                                pass
                            node.dirs.append(sub)
                            res.dirs += 1
                            stack.append((sub, entry.path, dup_ok and _dup_ok(entry.path, entry.name)))
                            continue
                        if entry.is_symlink():
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if getattr(st, "st_file_attributes", 0) & ONLINE_ONLY:
                        res.online_only += 1
                        continue
                    size = st.st_size
                    node.own += size
                    node.files += 1
                    res.files += 1
                    res.bytes += size
                    if size >= large_min:
                        item = (size, entry.path, st.st_mtime)
                        if len(large) < large_keep:
                            heapq.heappush(large, item)
                        elif size > large[0][0]:
                            heapq.heapreplace(large, item)
                    if dup_ok and size >= DUP_MIN and os.path.splitext(entry.name)[1].lower() not in DUP_SKIP_EXT:
                        res.dup_candidates.setdefault(size, []).append(entry.path)
            now = time.monotonic()
            if progress and now - last > 0.1:
                last = now
                progress(res.files, res.bytes, path)
        if res.cancelled:
            break
    # sizes flow up: children were created after their parents, so walk backwards
    for node in order:
        node.size = node.own
    for node in reversed(order):
        if node.parent is not None:
            node.parent.size += node.size
            node.parent.files += node.files
    res.large = sorted(large, reverse=True)
    res.dup_candidates = {s: p for s, p in res.dup_candidates.items() if len(p) > 1}
    res.seconds = time.monotonic() - start
    return res


def _dup_ok(path, name=None):
    """Duplicates are only looked for among the person's own files, never program or Windows files."""
    if name is not None and (name.lower() in DUP_SKIP or name.startswith(".")):
        return False                # ".cursor", ".gradle"...: tools' own files, not the person's
    where = knowledge.zone(path)
    if where == "other":            # loose folders on the Windows drive are mostly vendor and program files
        return not knowledge.norm(path).startswith(knowledge.norm(os.environ.get("SystemDrive", "C:") + "\\"))
    return where in ("user", "root")


def list_folder(path, limit=400):
    """Files directly inside a folder: [(name, size, mtime)], biggest first, plus (count, bytes) of the rest."""
    files = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False) or e.is_symlink():
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                online = getattr(st, "st_file_attributes", 0) & ONLINE_ONLY
                files.append((e.name, 0 if online else st.st_size, st.st_mtime))
    except OSError:
        return [], (0, 0)
    files.sort(key=lambda f: -f[1])
    rest = files[limit:]
    return files[:limit], (len(rest), sum(f[1] for f in rest))


def folder_size(path, older_than=None, cancelled=lambda: False):
    """(bytes, files) inside a folder, optionally only files older than a timestamp. Links are not followed."""
    total = count = 0
    stack = [path]
    while stack and not cancelled():
        p = stack.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if not (e.is_symlink() or e.is_junction()):
                                stack.append(e.path)
                            continue
                        if e.is_symlink():
                            continue
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if older_than is not None and st.st_mtime > older_than:
                        continue
                    if getattr(st, "st_file_attributes", 0) & ONLINE_ONLY:
                        continue
                    total += st.st_size
                    count += 1
        except OSError:
            continue
    return total, count
