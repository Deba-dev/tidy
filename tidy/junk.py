"""Known junk: groups of places that are (almost) always safe to clean, each with a plain explanation.

Every item's safety comes from knowledge.explain(), so the Junk page, the Space map and the deleter always agree.
"""
import glob
import os
import time
from dataclasses import dataclass, field

from . import knowledge, scanner, winapi
from .knowledge import CHOICE, SAFE


@dataclass
class Entry:
    """One thing the person can tick. kind: "path" (delete it), "contents" (empty the folder, keep the folder) or
    "recyclebin" (empty the Recycle Bin)."""
    path: str
    kind: str
    size: int
    info: knowledge.Info
    count: int = 0
    older_than: float = None        # only files last changed before this time (temp folders)
    note: str = ""                  # extra line, e.g. "Copy 2 of 3"
    locked: str = ""                # why it can't be ticked right now ("Needs administrator")

    @property
    def key(self):
        return "<recyclebin>" if self.kind == "recyclebin" else knowledge.norm(self.path)

    @property
    def name(self):
        if self.kind == "recyclebin":
            return "Recycle Bin"
        return os.path.basename(self.path.rstrip("\\/")) or self.path


@dataclass
class Group:
    id: str
    title: str
    what: str
    safety: str
    entries: list = field(default_factory=list)

    @property
    def size(self):
        return sum(e.size for e in self.entries)


def entry_for(path, size, is_dir, count=0, older_than=None):
    """An Entry for any path, following what knowledge says (folders that must stay are emptied instead)."""
    info = knowledge.explain(path, is_dir)
    kind = "contents" if is_dir and info.keep_folder else "path"
    return Entry(path, kind, size, info, count, older_than if kind == "contents" else None)


# (id, title, what, patterns, mode, min age in hours or None)
RULES = [
    ("temp", "Temporary files", "Files programs and Windows leave behind while they work.",
     ["%TEMP%", "%SystemRoot%\\Temp"], "contents", "temp"),
    ("updates", "Windows Update leftovers", "Updates Windows already downloaded and installed.",
     ["%SystemRoot%\\SoftwareDistribution\\Download",
      "%SystemRoot%\\ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft\\Windows\\DeliveryOptimization\\Cache"],
     "contents", None),
    ("crash", "Crash reports and dumps", "Reports saved when an app or Windows crashed. Only developers use them.",
     ["%LOCALAPPDATA%\\CrashDumps", "%LOCALAPPDATA%\\Microsoft\\Windows\\WER",
      "%ProgramData%\\Microsoft\\Windows\\WER", "%SystemRoot%\\Minidump", "%SystemRoot%\\MEMORY.DMP",
      "%SystemRoot%\\LiveKernelReports"], "auto", None),
    ("browsers", "Browser caches", "Copies of web pages and pictures your browsers keep. Passwords, bookmarks, "
     "history and logins are not touched.",
     [base + "\\User Data\\*\\" + sub
      for base in ("%LOCALAPPDATA%\\Google\\Chrome", "%LOCALAPPDATA%\\Microsoft\\Edge",
                   "%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser", "%LOCALAPPDATA%\\Vivaldi")
      for sub in ("Cache", "Code Cache", "GPUCache", "Service Worker\\CacheStorage")] +
     ["%LOCALAPPDATA%\\Mozilla\\Firefox\\Profiles\\*\\cache2", "%LOCALAPPDATA%\\Opera Software\\*\\Cache",
      "%APPDATA%\\Opera Software\\*\\Cache", "%LOCALAPPDATA%\\Microsoft\\Windows\\INetCache"], "contents", None),
    ("apps", "App caches", "Pictures and data apps like Discord, Spotify and Steam keep so they open faster.",
     ["%APPDATA%\\" + app + "\\" + sub for app in ("discord", "Code", "Slack", "Microsoft\\Teams", "WhatsApp")
      for sub in ("Cache", "Code Cache", "GPUCache")] +
     ["%APPDATA%\\Code\\CachedData", "%LOCALAPPDATA%\\Spotify\\Storage", "%LOCALAPPDATA%\\Steam\\htmlcache",
      "%LOCALAPPDATA%\\EpicGamesLauncher\\Saved\\webcache*"], "contents", None),
    ("shaders", "Graphics shader caches", "Graphics data games and apps build to load faster. Built again "
     "automatically.",
     ["%LOCALAPPDATA%\\D3DSCache", "%LOCALAPPDATA%\\NVIDIA\\DXCache", "%LOCALAPPDATA%\\NVIDIA\\GLCache",
      "%LOCALAPPDATA%\\AMD\\DxCache", "%LOCALAPPDATA%\\AMD\\DxcCache", "%LOCALAPPDATA%\\AMD\\GLCache",
      "%USERPROFILE%\\AppData\\LocalLow\\Intel\\ShaderCache"], "contents", None),
    ("thumbs", "Thumbnail cache", "Small preview pictures File Explorer shows. Made again when you open folders.",
     ["%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer\\thumbcache_*.db"], "auto", None),
    ("dev", "Developer caches", "Packages downloaded by coding tools (npm, pip, Yarn, NuGet, Gradle). They download "
     "again when a project needs them.",
     ["%LOCALAPPDATA%\\npm-cache", "%LOCALAPPDATA%\\pip\\Cache", "%LOCALAPPDATA%\\Yarn\\Cache",
      "%USERPROFILE%\\.nuget\\packages", "%USERPROFILE%\\.gradle\\caches"], "auto", None),
    ("drivers", "Driver installer leftovers", "Files unpacked or downloaded while installing graphics drivers. "
     "Your drivers stay installed.",
     ["%SystemDrive%\\AMD", "%SystemDrive%\\NVIDIA", "%ProgramData%\\NVIDIA Corporation\\Downloader"], "auto", None),
    ("installers", "Old installers in Downloads", "Setup files you downloaded more than a month ago. The programs "
     "stay installed if you delete them; check none is something you can't download again.",
     ["%USERPROFILE%\\Downloads\\*.exe", "%USERPROFILE%\\Downloads\\*.msi"], "auto", "old"),
]


def find(temp_hours=24, installer_days=30, cancelled=lambda: False, progress=None):
    """Looks in every known junk place. Returns a list of Groups (only those with something in them)."""
    now = time.time()
    admin = winapi.is_admin()
    groups = []
    size, count = winapi.recycle_bin_size()
    if size > 0:
        info = knowledge.known(os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "$Recycle.Bin"))
        groups.append(Group("recyclebin", "Recycle Bin", "Files you deleted before. They still use space until the "
                            "bin is emptied.", SAFE, [Entry("", "recyclebin", size, info, count)]))
    for rid, title, what, pats, mode, age in RULES:
        if cancelled():
            break
        older = now - temp_hours * 3600 if age == "temp" else now - installer_days * 86400 if age == "old" else None
        group = Group(rid, title, what, SAFE)
        seen = set()
        for pat in pats:
            expanded = os.path.expandvars(pat)
            if "%" in expanded:
                continue
            for path in sorted(glob.glob(expanded)) if any(c in expanded for c in "*?[") else [expanded]:
                key = knowledge.norm(path)
                if key in seen or not os.path.lexists(path):
                    continue
                seen.add(key)
                if progress:
                    progress(path)
                is_dir = os.path.isdir(path)
                if is_dir:
                    size, n = scanner.folder_size(path, older if mode == "contents" or age else None, cancelled)
                else:
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    if age == "old" and st.st_mtime > older:
                        continue
                    size, n = st.st_size, 1
                if size <= 0:
                    continue
                e = entry_for(path, size, is_dir, n, older)
                if mode == "contents" and is_dir:
                    e.kind, e.older_than = "contents", older
                if e.info.admin and not admin:
                    e.locked = "Needs administrator"
                group.entries.append(e)
        if group.entries:
            group.entries.sort(key=lambda e: -e.size)
            group.safety = knowledge.worst(*(e.info.safety for e in group.entries))
            groups.append(group)
    return groups


def total(groups, safety=SAFE, unlocked=True):
    return sum(e.size for g in groups for e in g.entries
               if e.info.safety == safety and not (unlocked and e.locked))


__all__ = ["Entry", "Group", "find", "entry_for", "total", "SAFE", "CHOICE"]
