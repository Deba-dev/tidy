"""Finds files with exactly the same contents among the person's own files.

Files of the same size are compared by a quick fingerprint (start and end of the file) and only those still alike are
read in full. The copy kept by default is the oldest one (usually the original); the others are offered as extras.
"""
import hashlib
import os
from dataclasses import dataclass

CHUNK = 1024 * 1024
EDGE = 64 * 1024


@dataclass
class DupGroup:
    size: int
    paths: list                 # the suggested original first

    @property
    def extra(self):
        """Space freed by keeping only one copy."""
        return self.size * (len(self.paths) - 1)


def _quick(path, size):
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        h.update(f.read(EDGE))
        if size > 2 * EDGE:
            f.seek(-EDGE, os.SEEK_END)
            h.update(f.read(EDGE))
    return h.digest()


def _full(path, cancelled):
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        while True:
            if cancelled():
                raise InterruptedError
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.digest()


def _keep_order(path):
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        mtime = float("inf")
    return mtime, len(path), path.lower()


def find(candidates, progress=None, cancelled=lambda: False):
    """candidates: {size: [paths]} from the scanner. progress(done_bytes, total_bytes, path)."""
    groups = []
    todo = sorted(candidates.items(), key=lambda kv: -kv[0])
    total = sum(size * len(paths) for size, paths in todo)
    done = 0
    for size, paths in todo:
        if cancelled():
            break
        by_quick = {}
        for p in paths:
            try:
                by_quick.setdefault(_quick(p, size), []).append(p)
            except OSError:
                pass
        for same in by_quick.values():
            if len(same) < 2:
                continue
            if size <= 2 * EDGE:            # the quick fingerprint already read the whole file
                by_full = {b"": same}
            else:
                by_full = {}
                for p in same:
                    if progress:
                        progress(done, total, p)
                    try:
                        by_full.setdefault(_full(p, cancelled), []).append(p)
                    except InterruptedError:
                        return groups
                    except OSError:
                        pass
            for copies in by_full.values():
                if len(copies) > 1:
                    groups.append(DupGroup(size, sorted(copies, key=_keep_order)))
        done += size * (len(paths))
        if progress:
            progress(min(done, total), total, "")
    groups.sort(key=lambda g: -g.extra)
    return groups
