"""Leftovers: what uninstalled programs left behind.

Three kinds:
- Leftover folders: a folder in Program Files, ProgramData or AppData that no installed program matches, that nothing
  running uses, and that hasn't changed for months. Tidy can't be 100% sure (some tools never register themselves),
  so these are always "Your choice", with the reasons spelled out.
- Empty folders in those same places: nothing inside, nothing to lose.
- Broken shortcuts in the Start menu and on the desktop: they point at a program that is gone.

The deleter calls verify() again for every leftover just before deleting it.
"""
import os
import re
import struct
import time
import winreg
from dataclasses import dataclass

import psutil

from . import knowledge, scanner, winapi
from .junk import Entry, Group
from .knowledge import CHOICE, SAFE, Info

QUIET_DAYS = 90             # a folder that changed more recently is still in use by something
MIN_SIZE = 1024 * 1024      # smaller leftovers aren't worth anyone's time (empty folders are listed apart)

# never leftovers: Windows' own folders, shared runtimes, driver vendors, caches the Junk page already handles
PROTECTED = {
    "microsoft", "windows", "packages", "temp", "tmp", "programs", "common files", "windowsapps",
    "modifiablewindowsapps", "internet explorer", "windows defender", "windows defender advanced threat protection",
    "windows mail", "windows media player", "windows multimedia platform", "windows nt", "windows photo viewer",
    "windows portable devices", "windows security", "windows sidebar", "windowspowershell", "reference assemblies",
    "msbuild", "dotnet", "uninstall information", "package cache", "packagemanagement", "comms",
    "connecteddevicesplatform", "d3dscache", "crashdumps", "nvidia", "nvidia corporation", "amd", "ati", "intel",
    "realtek", "ssh", "usoshared", "usoprivate", "softwaredistribution", "regid.1991-06.com.microsoft",
    "desktop.ini", "history", "fontcache", "identities", "virtualstore", "applicationdata", "application data",
    "microsoft help", "microsoft.net", "msi", "installshield installation information", "oracle", "java",
    "docker", "wsl", "google", "mozilla", "squirreltemp", "npm-cache", "pip", "yarn", "nuget", "gradle",
    "jetbrains", "pypa", "python", "node", "nodejs", "git", "github", "ms-playwright", "electron", "cache",
    "caches", "logs", "log", "tidy", "zunimistudio", "clipstudio", "chatdoom", "embarcadero", "assembly",
    "device stage", "windows kits", "microsoft sdks", "microsoft sql server", "iis", "iis express",
    "windows app certification kit", "microsoft visual studio", "vs", "visualstudio", "steam", "epic games",
    "riot games", "battle.net", "ea", "ubisoft", "rockstar games", "asus", "armourycrate", "rog", "dell", "hp",
    "lenovo", "acer", "msi", "gigabyte", "dts", "dolby", "waves", "nahimic", "conexant", "synaptics", "elan",
    "killer networking", "rivet networks", "chocolatey", "scoop", "qualcomm", "mediatek", "broadcom", "bluetooth",
}


@dataclass
class Program:
    name: str
    publisher: str
    paths: list             # install location, icon and uninstaller folders (normalised)


def _key(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _exe_folder(value):
    """The folder of the program in a registry value like '"C:\\x\\uninst.exe" /S' or 'C:\\x\\app.exe,0'."""
    if not value:
        return ""
    v = value.strip()
    m = re.match(r'^"([^"]+)"', v)
    path = m.group(1) if m else re.split(r"\.exe\b", v, flags=re.I)[0] + (".exe" if ".exe" in v.lower() else "")
    path = path.split(",")[0].strip()
    if "msiexec" in path.lower() or not os.path.isabs(path):
        return ""
    return knowledge.norm(os.path.dirname(path) if os.path.splitext(path)[1] else path)


def installed():
    """Programs Windows knows about (Settings > Apps), for this account and the whole PC, 32 and 64 bit."""
    found = []
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive, flags in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
                        (winreg.HKEY_CURRENT_USER, 0)):
        try:
            root = winreg.OpenKey(hive, base, 0, winreg.KEY_READ | flags)
        except OSError:
            continue
        with root:
            for i in range(10000):
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(root, sub) as k:
                        vals = {}
                        for name in ("DisplayName", "Publisher", "InstallLocation", "DisplayIcon",
                                     "UninstallString"):
                            try:
                                vals[name] = str(winreg.QueryValueEx(k, name)[0] or "")
                            except OSError:
                                vals[name] = ""
                except OSError:
                    continue
                paths = [p for p in (knowledge.norm(vals["InstallLocation"].strip('"')) if
                                     vals["InstallLocation"].strip() else "", _exe_folder(vals["DisplayIcon"]),
                                     _exe_folder(vals["UninstallString"])) if p and len(p) > 3]
                found.append(Program(vals["DisplayName"] or sub, vals["Publisher"], paths))
    packages = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages")
    try:
        for name in os.listdir(packages):          # Store apps: "SpotifyAB.SpotifyMusic_zpdnekdrzrea0"
            found.append(Program(name.split("_")[0].replace(".", " "), "", []))
    except OSError:
        pass
    return found


def running_folders():
    out = set()
    for p in psutil.process_iter(["exe"]):
        exe = p.info.get("exe")
        if exe:
            out.add(knowledge.norm(os.path.dirname(exe)))
    return out


class Matcher:
    """Tells whether a folder still belongs to an installed or running program."""
    def __init__(self, programs=None, running=None):
        self.programs = programs if programs is not None else installed()
        self.running = running if running is not None else running_folders()
        self.names = set()
        self.words = set()
        for prog in self.programs:
            for text in (prog.name, prog.publisher):
                k = _key(text)
                if k:
                    self.names.add(k)
                for w in re.split(r"[^a-z0-9]+", (text or "").lower()):
                    if len(w) >= 4:
                        self.words.add(w)
        tops = {knowledge.norm(r) for r, _ in roots()} | {knowledge.norm(os.environ[v]) for v in
                                                           ("USERPROFILE", "SystemRoot") if os.environ.get(v)}
        # some installers write "C:\Program Files" itself as their place: that must not claim every folder in it
        self.paths = {p for prog in self.programs for p in prog.paths if p not in tops and len(p) > 3}

    def owner(self, path, name):
        """Why this folder is still in use ("" when nothing claims it)."""
        p = knowledge.norm(path)
        for q in self.paths | self.running:
            if q == p or q.startswith(p + "\\"):     # a program lives in it (or in a folder inside it)
                return "in use"
        k = _key(name)
        if len(k) < 3:
            return "short name"
        for n in self.names:
            if (len(k) >= 4 and k in n) or (len(n) >= 5 and n in k):
                return "matches " + n
        first = re.split(r"[^a-z0-9]+", name.lower())[0]
        if len(first) >= 4 and first in self.words:
            return "matches " + first
        return ""


def roots():
    """(folder, needs admin) pairs whose direct sub-folders are checked."""
    env = os.environ.get
    local = env("LOCALAPPDATA", "")
    roaming = env("APPDATA", "")
    home = env("USERPROFILE", "")
    out = [(env("ProgramW6432", env("ProgramFiles", "")), True), (env("ProgramFiles(x86)", ""), True),
           (env("ProgramData", ""), True), (local, False), (os.path.join(local, "Programs"), False),
           (roaming, False), (os.path.join(home, "AppData", "LocalLow"), False)]
    seen, res = set(), []
    for path, admin in out:
        if path and os.path.isdir(path) and knowledge.norm(path) not in seen:
            seen.add(knowledge.norm(path))
            res.append((path, admin))
    return res


def _measure(path):
    """(bytes, files, newest change time) of a folder, links not followed."""
    total, files, newest = 0, 0, 0.0
    try:
        newest = os.stat(path).st_mtime
    except OSError:
        pass
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if e.is_symlink() or e.is_junction():
                            continue
                        st = e.stat(follow_symlinks=False)
                        newest = max(newest, st.st_mtime)
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += st.st_size
                            files += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return total, files, newest


def _ago(ts):
    days = (time.time() - ts) / 86400
    if days >= 730:
        return "%d years" % (days // 365)
    if days >= 60:
        return "%d months" % (days // 30)
    return "%d days" % days


def find(cancelled=lambda: False, progress=None, matcher=None):
    """Groups of leftovers: folders, empty folders and broken shortcuts."""
    m = matcher or Matcher()
    admin = winapi.is_admin()
    quiet = time.time() - QUIET_DAYS * 86400
    folders = Group("leftovers", "Leftover folders", "Folders that seem to be left behind by programs that are no "
                    "longer installed. Look at each one: Tidy can't be completely sure.", CHOICE)
    empty = Group("empty", "Empty folders", "Folders with nothing inside, left by programs that were removed.", SAFE)
    for root, needs_admin in roots():
        try:
            children = list(os.scandir(root))
        except OSError:
            continue
        inherited = knowledge.known(os.path.join(root, "~tidy-probe~"))     # what any folder here gets from above
        for e in children:
            if cancelled():
                return []
            try:
                if not e.is_dir(follow_symlinks=False) or e.is_symlink() or e.is_junction():
                    continue
            except OSError:
                continue
            name = e.name
            if name.lower() in PROTECTED or name.startswith((".", "$", "{")) or len(name) < 2:
                continue
            if progress:
                progress(e.path)
            info = knowledge.known(e.path)
            if info is not None and info is not inherited and info.safety != knowledge.KEEP:
                continue                        # a cache or temp folder of its own, explained on the Junk page
            if m.owner(e.path, name):
                continue
            size, files, newest = _measure(e.path)
            locked = "Needs administrator" if needs_admin and not admin else ""
            if files == 0 and size == 0:
                if newest > quiet:
                    continue                    # just made: a program may be about to fill it
                entry = Entry(e.path, "path", 0, Info(name, "An empty folder, probably left behind when a program "
                              "was removed.", SAFE, "Safe to delete: there is nothing inside."), 0, origin="leftover")
                entry.locked = locked
                empty.entries.append(entry)
                continue
            if newest > quiet or size < MIN_SIZE:
                continue
            where = os.path.basename(root.rstrip("\\/")) or root
            has_programs = _has_exe(e.path)
            what = ("Probably left behind by '%s', which is no longer installed. No installed program matches its "
                    "name, nothing running uses it, and nothing in it changed for %s." % (name, _ago(newest)))
            advice = ("Usually safe to delete. If it held settings or saves of something you still use (for example "
                      "a game's saves), those go too, so use the Recycle Bin when unsure.")
            if has_programs:
                advice = ("It still has program files inside. If you run '%s' without installing it (a portable "
                          "app), keep it. Otherwise it's usually safe; use the Recycle Bin when unsure." % name)
            entry = Entry(e.path, "path", size, Info(name, what, CHOICE, advice), files, origin="leftover",
                          note="In %s. Last changed %s ago." % (where, _ago(newest)))
            entry.locked = locked
            folders.entries.append(entry)
    shortcuts = Group("shortcuts", "Broken shortcuts", "Start menu and desktop shortcuts to programs that are gone.",
                      SAFE)
    for lnk, target in broken_shortcuts():
        shortcuts.entries.append(Entry(lnk, "path", _size(lnk), Info(
            os.path.splitext(os.path.basename(lnk))[0], "A shortcut to '%s', which no longer exists." % target, SAFE,
            "Safe to delete: clicking it would only show an error."), 1, origin="leftover",
            locked="Needs administrator" if _machine_wide(lnk) and not admin else ""))
    groups = []
    for g in (folders, empty, shortcuts):
        if g.entries:
            g.entries.sort(key=lambda x: (-x.size, x.path.lower()))
            groups.append(g)
    return groups


def _has_exe(path, limit=2000):
    seen = 0
    for _, _, files in os.walk(path):
        for f in files:
            if f.lower().endswith(".exe"):
                return True
            seen += 1
        if seen > limit:
            break
    return False


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


# ---------------------------------------------------------------- shortcuts
def shortcut_places():
    env = os.environ.get
    out = [os.path.join(env("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
           os.path.join(env("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs"),
           os.path.join(env("USERPROFILE", ""), "Desktop"), os.path.join(env("PUBLIC", ""), "Desktop")]
    return [p for p in out if os.path.isdir(p)]


def _machine_wide(path):
    p = knowledge.norm(path)
    return any(p.startswith(knowledge.norm(b) + "\\") for b in (os.environ.get("ProgramData", "x:\\none"),
                                                               os.environ.get("PUBLIC", "x:\\none")))


def lnk_target(path):
    """The file a .lnk shortcut points at, read from the file itself; None when it has no plain file target (web
    links, Store apps, installer 'advertised' shortcuts)."""
    try:
        with open(path, "rb") as f:
            data = f.read(1 << 16)
    except OSError:
        return None
    if len(data) < 0x4C or struct.unpack_from("<I", data, 0)[0] != 0x4C:
        return None
    flags = struct.unpack_from("<I", data, 0x14)[0]
    pos = 0x4C
    if flags & 0x1:                                     # HasLinkTargetIDList
        pos += 2 + struct.unpack_from("<H", data, pos)[0]
    if not flags & 0x2 or pos + 28 > len(data):         # HasLinkInfo
        return None
    info = pos
    size, header, li_flags, _vol, local_off, _net, suffix_off = struct.unpack_from("<7I", data, info)
    if not li_flags & 0x1:                              # no local path (a network share)
        return None

    def cstr(off, wide):
        start = info + off
        if wide:
            end = start
            while end + 1 < len(data) and data[end:end + 2] != b"\0\0":
                end += 2
            return data[start:end].decode("utf-16-le", "replace")
        end = data.find(b"\0", start)
        return data[start:end].decode("mbcs" if os.name == "nt" else "latin-1", "replace")

    if header >= 0x24 and info + 36 <= len(data):
        local_u, suffix_u = struct.unpack_from("<2I", data, info + 28)
        base, suffix = cstr(local_u, True), cstr(suffix_u, True)
    else:
        base, suffix = cstr(local_off, False), cstr(suffix_off, False)
    target = base + suffix if suffix and not base.endswith("\\") else base + suffix
    return target or None


def broken_shortcuts():
    """[(shortcut, missing target)] for shortcuts whose target is gone from a drive that is plugged in."""
    out = []
    for place in shortcut_places():
        for dirpath, dirs, files in os.walk(place):
            for f in files:
                if not f.lower().endswith(".lnk"):
                    continue
                lnk = os.path.join(dirpath, f)
                target = lnk_target(lnk)
                if not target or "%" in target or target.startswith("\\\\"):
                    continue
                drive = os.path.splitdrive(target)[0]
                if not drive or not os.path.exists(drive + "\\"):
                    continue                        # a USB drive that isn't plugged in right now
                if not os.path.exists(target):
                    out.append((lnk, target))
    return out


# ---------------------------------------------------------------- the deleter's last check
_cache = [0.0, None]


def cached_matcher(max_age=30):
    """One Matcher for a whole delete run (reading the registry for every folder would be slow)."""
    if _cache[1] is None or time.monotonic() - _cache[0] > max_age:
        _cache[:] = [time.monotonic(), Matcher()]
    return _cache[1]

def verify(path, matcher=None):
    """"" when this is still a leftover Tidy may delete, else why not."""
    p = knowledge.norm(path)
    if p.endswith(".lnk"):
        target = lnk_target(path)
        if target and not os.path.exists(target):
            return ""
        return "The shortcut works again."
    parent = knowledge.norm(os.path.dirname(path))
    if parent not in {knowledge.norm(r) for r, _ in roots()}:
        return "Not in a place where programs install."
    name = os.path.basename(path.rstrip("\\/"))
    if name.lower() in PROTECTED:
        return "Tidy keeps this folder."
    why = (matcher or cached_matcher()).owner(path, name)
    if why:
        return "A program uses it again (%s)." % why
    return ""


__all__ = ["find", "verify", "lnk_target", "broken_shortcuts", "Matcher", "scanner"]
