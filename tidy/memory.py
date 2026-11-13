"""What is using memory (RAM), explained, and the honest ways to free some.

Windows fills spare memory with a cache on purpose: unused memory is wasted memory. So Tidy doesn't promise magic.
It shows which apps use the most, explains each one (Safe to close / Your choice / Keep), and offers:

- Close ticked apps: each app is asked to close normally (like clicking its X), so it can ask to save your work.
  Only if the person says so are apps that stay open forced to quit.
- Free up memory: asks every app to hand back memory it isn't using right now (Windows' EmptyWorkingSet). Apps take
  back what they need, so it helps most just before starting a game on a PC with little memory.
- Clear standby cache (administrator only): drops files Windows kept in memory "just in case".
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass, field

import psutil

from .knowledge import CHOICE, KEEP, SAFE

IS_WINDOWS = sys.platform == "win32"

# Windows' own processes and drivers: closing them can freeze or crash the PC, or kill the taskbar
SYSTEM = {
    "system", "system idle process", "registry", "memory compression", "secure system", "smss.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "fontdrvhost.exe",
    "dwm.exe", "explorer.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe", "runtimebroker.exe", "searchhost.exe",
    "searchindexer.exe", "searchprotocolhost.exe", "searchfilterhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "shellhost.exe", "textinputhost.exe", "applicationframehost.exe", "audiodg.exe",
    "spoolsv.exe", "msmpeng.exe", "nissrv.exe", "mpdefendercoreservice.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "smartscreen.exe", "wmiprvse.exe", "conhost.exe", "dllhost.exe", "wudfhost.exe",
    "lockapp.exe", "sgrmbroker.exe", "useroobebroker.exe", "dashost.exe", "unsecapp.exe", "wlanext.exe",
    "msedgewebview2.exe", "crossdeviceresume.exe", "igfxem.exe", "igfxcuiservice.exe", "igfxhk.exe", "igfxtray.exe",
    "nvcontainer.exe", "nvdisplay.container.exe", "atiesrxx.exe", "atieclxx.exe", "amdrsserv.exe",
    "rtkaudueservice64.exe", "rtkauduservice64.exe", "dpmservice.exe", "smss", "vmmem", "vmmemws", "vmcompute.exe",
}
SYSTEM_WHY = {
    "explorer.exe": ("Windows Explorer", "Your taskbar, Start menu, desktop and File Explorer windows."),
    "dwm.exe": ("Desktop Window Manager", "Draws every window on your screen."),
    "msedgewebview2.exe": ("Edge WebView2", "The web engine many apps (Widgets, Teams, Outlook, games' launchers) "
                           "use to show their screens. Closing it breaks the app that uses it."),
    "svchost.exe": ("Windows services", "Runs dozens of Windows' background services (network, sound, updates)."),
    "msmpeng.exe": ("Microsoft Defender", "Your antivirus."),
    "memory compression": ("Memory compression", "Windows squeezes memory here so more fits. It is a good thing."),
    "vmmem": ("Virtual machines / WSL", "Memory used by WSL, Docker or another virtual machine. Stop them from "
              "their own app (for example 'wsl --shutdown')."),
    "vmmemws": ("Windows Sandbox / WSL", "Memory used by a virtual machine. Stop it from its own app."),
}
# harmless to close: they start again on their own when needed
HELPERS = {
    "googleupdate.exe", "microsoftedgeupdate.exe", "adobearm.exe", "jusched.exe", "onedrivestandaloneupdater.exe",
    "updater.exe", "update.exe", "adobecollabsync.exe", "acrotray.exe", "ccxprocess.exe", "adobeipcbroker.exe",
    "crashpad_handler.exe", "squirrel.exe", "gamebarpresencewriter.exe", "gamebar.exe", "widgets.exe",
    "phoneexperiencehost.exe", "yourphone.exe", "cortana.exe",
}


@dataclass
class App:
    name: str               # exe name, lower case: "chrome.exe"
    title: str              # "Google Chrome"
    what: str
    safety: str
    advice: str
    path: str = ""
    pids: list = field(default_factory=list)
    memory: int = 0          # bytes in use (working set), all its processes together
    windows: int = 0         # open windows

    @property
    def key(self):
        return self.name

    @property
    def count(self):
        return len(self.pids)


@dataclass
class Status:
    total: int
    available: int
    used: int
    percent: float
    commit_used: int = 0
    commit_limit: int = 0

    @property
    def level(self):
        """SAFE (plenty left), CHOICE (getting full) or KEEP (very full) for the gauge colour."""
        return SAFE if self.percent < 70 else CHOICE if self.percent < 85 else KEEP


def status():
    vm = psutil.virtual_memory()
    st = Status(vm.total, vm.available, vm.total - vm.available, vm.percent)
    if IS_WINDOWS:
        class PERF(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("CommitTotal", ctypes.c_size_t), ("CommitLimit", ctypes.c_size_t),
                        ("CommitPeak", ctypes.c_size_t), ("PhysicalTotal", ctypes.c_size_t),
                        ("PhysicalAvailable", ctypes.c_size_t), ("SystemCache", ctypes.c_size_t),
                        ("KernelTotal", ctypes.c_size_t), ("KernelPaged", ctypes.c_size_t),
                        ("KernelNonpaged", ctypes.c_size_t), ("PageSize", ctypes.c_size_t),
                        ("HandleCount", wintypes.DWORD), ("ProcessCount", wintypes.DWORD),
                        ("ThreadCount", wintypes.DWORD)]
        perf = PERF()
        perf.cb = ctypes.sizeof(perf)
        if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(perf), perf.cb):
            st.commit_used = perf.CommitTotal * perf.PageSize
            st.commit_limit = perf.CommitLimit * perf.PageSize
    return st


# ---------------------------------------------------------------- windows and file descriptions
def visible_windows():
    """{pid: [hwnd]} for normal, visible, titled top-level windows (what you see on the taskbar)."""
    out = {}
    if not IS_WINDOWS:
        return out
    user32 = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        if user32.GetWindow(hwnd, 4):                    # GW_OWNER: dialogs and tool windows belong to another
            return True
        cloaked = wintypes.DWORD(0)
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value:                                # hidden Store app windows
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.setdefault(pid.value, []).append(hwnd)
        return True
    user32.EnumWindows(proto(cb), 0)
    return out


_desc_cache = {}


def describe_exe(path):
    """The program's own name from its file (e.g. "Google Chrome"), or ""."""
    if not path or not IS_WINDOWS:
        return ""
    if path in _desc_cache:
        return _desc_cache[path]
    text = ""
    try:
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(path, None)
        if size:
            buf = ctypes.create_string_buffer(size)
            if ver.GetFileVersionInfoW(path, 0, size, buf):
                ptr = ctypes.c_void_p()
                n = wintypes.UINT()
                langs = [(0x0409, 0x04B0), (0x0409, 0x04E4), (0x0000, 0x04B0)]
                if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(n)) and n.value:
                    arr = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
                    langs.insert(0, (arr[0], arr[1]))
                for lang, cp in langs:
                    for key in ("FileDescription", "ProductName"):
                        q = "\\StringFileInfo\\%04x%04x\\%s" % (lang, cp, key)
                        if ver.VerQueryValueW(buf, q, ctypes.byref(ptr), ctypes.byref(n)) and n.value > 1:
                            text = ctypes.wstring_at(ptr).strip()       # stops at the first NUL
                            if text:
                                break
                    if text:
                        break
    except OSError:
        text = ""
    _desc_cache[path] = text
    return text


# ---------------------------------------------------------------- the list
def _session(pid):
    if not IS_WINDOWS:
        return 1
    sid = wintypes.DWORD()
    if ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid)):
        return sid.value
    return 0


def apps():
    """Running apps grouped by program, most memory first."""
    me = os.getpid()
    my_session = _session(me)
    windows = visible_windows()
    groups = {}
    for p in psutil.process_iter(["pid", "name", "exe", "memory_info"]):
        info = p.info
        name = (info.get("name") or "").lower()
        mem = info.get("memory_info")
        if not name or info["pid"] == 0:          # "System Idle Process" is not memory anyone uses
            continue
        size = mem.rss if mem else 0
        key = "<tidy>" if info["pid"] == me else name
        app = groups.get(key)
        if app is None:
            app = groups[key] = _explain(name, info.get("exe") or "", info["pid"], my_session, me)
        app.pids.append(info["pid"])
        app.memory += size
        app.windows += len(windows.get(info["pid"], []))
        if not app.path and info.get("exe"):
            app.path = info["exe"]
    out = sorted(groups.values(), key=lambda a: -a.memory)
    for a in out:
        if a.safety == CHOICE and not a.windows and a.name not in HELPERS:
            a.what = a.what.rstrip(".") + ". It has no open window: it runs in the background, often as a tray icon."
    return out


def _explain(name, path, pid, my_session, me):
    pretty = describe_exe(path) or os.path.splitext(name)[0]
    if pid == me:
        return App("<tidy>", "Tidy", "This app.", KEEP, "Tidy itself.", path)
    if name in SYSTEM or name in SYSTEM_WHY:
        title, what = SYSTEM_WHY.get(name, (pretty, "Part of Windows or a driver."))
        return App(name, title, what, KEEP, "Keep it running. Closing it can freeze your PC, cut the sound or "
                   "network, or make the taskbar disappear. Windows manages its memory by itself.", path)
    if _session(pid) != my_session:
        return App(name, pretty, "A background service: it runs for the whole PC, not just your account (often "
                   "part of a driver, antivirus or an app's updater).", KEEP,
                   "Keep it. Services are managed by Windows; to get rid of one, uninstall the program it belongs to.",
                   path)
    if name in HELPERS:
        return App(name, pretty, "A helper that checks for updates or keeps a feature ready.", SAFE,
                   "Safe to close. It starts again by itself when it is needed.", path)
    return App(name, pretty, "An app running in your account.", CHOICE,
               "Close it if you're not using it. Tidy asks it to close normally, so it can ask you to save your "
               "work first.", path)


# ---------------------------------------------------------------- actions
WM_CLOSE = 0x0010


def close(app_list, force=False, wait=4.0):
    """Asks each app to close (or ends it with force=True). Returns the names still running."""
    windows = visible_windows()
    procs = []
    for a in app_list:
        if a.safety == KEEP:
            continue
        for pid in a.pids:
            try:
                procs.append(psutil.Process(pid))
            except psutil.Error:
                continue
            if force:
                try:
                    psutil.Process(pid).terminate()
                except psutil.Error:
                    pass
            elif IS_WINDOWS:
                for hwnd in windows.get(pid, []):
                    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    gone, alive = psutil.wait_procs(procs, timeout=wait)
    return sorted({n for n in (_name(p) for p in alive) if n})


def _name(p):
    try:
        return p.name().lower()
    except psutil.Error:
        return ""


def trim():
    """Asks every process we may touch to give back memory it isn't using. Returns bytes freed (roughly)."""
    if not IS_WINDOWS:
        return 0
    before = psutil.virtual_memory().available
    k32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SET_QUOTA = 0x1000, 0x0100
    for pid in psutil.pids():
        if pid in (0, 4):
            continue
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA, False, pid)
        if h:
            psapi.EmptyWorkingSet(h)
            k32.CloseHandle(h)
    time.sleep(0.5)
    return max(0, psutil.virtual_memory().available - before)


def _enable_privilege(name):
    advapi = ctypes.windll.advapi32

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Luid", LUID), ("Attributes", wintypes.DWORD)]

    token = wintypes.HANDLE()
    TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY, SE_PRIVILEGE_ENABLED = 0x20, 0x8, 0x2
    if not advapi.OpenProcessToken(ctypes.windll.kernel32.GetCurrentProcess(),
                                   TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
        return False
    try:
        luid = LUID()
        if not advapi.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
            return False
        tp = TOKEN_PRIVILEGES(1, luid, SE_PRIVILEGE_ENABLED)
        advapi.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
        return ctypes.windll.kernel32.GetLastError() == 0
    finally:
        ctypes.windll.kernel32.CloseHandle(token)


def clear_standby():
    """Drops the standby list (files Windows keeps in memory just in case). Needs administrator. Returns bytes freed,
    or -1 when Windows didn't allow it."""
    if not IS_WINDOWS:
        return -1
    before = psutil.virtual_memory().available
    if not _enable_privilege("SeProfileSingleProcessPrivilege"):
        return -1
    SystemMemoryListInformation, MemoryPurgeStandbyList = 80, 4
    cmd = ctypes.c_int(MemoryPurgeStandbyList)
    rc = ctypes.windll.ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(cmd),
                                                    ctypes.sizeof(cmd))
    if rc != 0:
        return -1
    time.sleep(0.3)
    return max(0, psutil.virtual_memory().available - before)
