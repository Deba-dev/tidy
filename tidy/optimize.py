"""Speed up: changes that really help, nothing risky, and every one of them can be undone.

What Tidy changes (all per-account settings Windows itself offers in Settings, except where noted):
- Game Mode on, Xbox background recording off, mouse acceleration off, transparency/animations off (low-end PCs)
- Power mode / plan for best performance (and back)
- Startup apps on or off, with the same switch Task Manager uses (StartupApproved)
- Which graphics card a game uses on laptops with two (Settings > System > Display > Graphics)

Before Tidy writes a value it saves the old one under settings["changes"], so "Undo" puts back exactly what was
there, even after Tidy restarts. What Tidy deliberately doesn't do is listed in WONT_DO.
"""
import ctypes
import json
import os
import re
import struct
import subprocess
import sys
import time
import uuid
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field

import psutil

from . import memory, winapi
from .knowledge import CHOICE, KEEP, SAFE

IS_WINDOWS = sys.platform == "win32"
HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
HIVES = {"HKCU": HKCU, "HKLM": HKLM}
NO_WINDOW = 0x08000000

GOOD, IMPROVE, INFO = "good", "improve", "info"
STATUS_SAFETY = {GOOD: SAFE, IMPROVE: CHOICE, INFO: None}

WONT_DO = [
    ("Turn off Windows services", "Saves almost nothing on a modern PC and breaks things later (updates, sound, "
     "Bluetooth, the Store), often weeks after, when nobody remembers why."),
    ("Registry cleaning", "Leftover registry entries take no space and don't slow anything down. Deleting the wrong "
     "one can stop programs or Windows from starting."),
    ("Network or 'ping' boosters", "TCP tweaks from old guides do nothing on Windows 10 and 11, and some make online "
     "games worse. A wired connection is the real fix."),
    ("Turn off Defender, updates or the page file", "Each gives a tiny or no gain and makes your PC unsafe or "
     "unstable: games crash when memory runs out without a page file."),
    ("'RAM boosters' that run all the time", "Constantly emptying memory makes apps reload from disk, which is "
     "slower. Tidy's Free up memory is a one-time button for before a game."),
    ("Overclocking or undervolting", "It can help, but it depends on your exact hardware and can crash or overheat "
     "it. Use your PC maker's or graphics card's own tool if you want it."),
]


# ---------------------------------------------------------------- registry with undo
def reg_get(hive, path, name):
    """(value, type), or (None, None) when it isn't there."""
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None, None


def reg_set(hive, path, name, value, kind):
    with winreg.CreateKeyEx(HIVES[hive], path, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def reg_del(hive, path, name):
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_WRITE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _pack(value):
    return {"hex": value.hex()} if isinstance(value, (bytes, bytearray)) else value


def _unpack(value):
    return bytes.fromhex(value["hex"]) if isinstance(value, dict) and "hex" in value else value


class Changes:
    """Tidy's own record of what it changed and what was there before."""
    def __init__(self, settings):
        self.s = settings

    def all(self):
        return dict(self.s.get("changes") or {})

    def has(self, tid):
        return tid in self.all()

    def write(self, tid, writes):
        """writes: [(hive, path, name, value, kind)]. The old values are saved the first time only."""
        changes = self.all()
        if tid not in changes:
            old = []
            for hive, path, name, _, _ in writes:
                value, kind = reg_get(hive, path, name)
                old.append([hive, path, name, _pack(value), kind])
            changes[tid] = {"reg": old, "at": time.time()}
            self.s.set("changes", changes)
        for hive, path, name, value, kind in writes:
            reg_set(hive, path, name, value, kind)

    def remember(self, tid, data):
        """Saves something that isn't a registry value (the power plan) the first time."""
        changes = self.all()
        if tid not in changes:
            changes[tid] = {"data": data, "at": time.time()}
            self.s.set("changes", changes)

    def undo(self, tid):
        changes = self.all()
        entry = changes.pop(tid, None)
        if entry is None:
            return None
        for hive, path, name, value, kind in entry.get("reg", []):
            if value is None:
                reg_del(hive, path, name)
            else:
                reg_set(hive, path, name, _unpack(value), kind)
        self.s.set("changes", changes)
        return entry


# ---------------------------------------------------------------- checks
@dataclass
class Check:
    id: str
    title: str
    status: str                 # GOOD, IMPROVE or INFO
    summary: str                # how it is now, in a few words
    what: str                   # what it is and what changing it does
    action: str = ""            # button text, "" when there is nothing to do
    undo: bool = False          # Tidy changed it and can put it back
    goto: str = ""              # another page or section the button opens
    links: list = field(default_factory=list)   # [(button text, url)]


def checks(settings):
    ch = Changes(settings)
    out = [check_gamemode(ch), check_recording(ch), check_power(ch), check_mouse(ch), check_drivers(),
           check_restart(), check_space(), check_visual(ch)]
    return [c for c in out if c is not None]


GAMEBAR = r"Software\Microsoft\GameBar"
DVR = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
MOUSE = r"Control Panel\Mouse"
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
METRICS = r"Control Panel\Desktop\WindowMetrics"


def check_gamemode(ch):
    value, _ = reg_get("HKCU", GAMEBAR, "AutoGameModeEnabled")
    on = value is None or value == 1
    return Check("gamemode", "Game Mode", GOOD if on else IMPROVE, "On" if on else "Off",
                 "While you play, Game Mode stops Windows Update from installing drivers or restarting, and gives "
                 "the game first pick of your processor. It's on in Windows by default and only acts while a game "
                 "runs.", "" if on else "Turn on", ch.has("gamemode"))


def check_recording(ch):
    value, _ = reg_get("HKCU", DVR, "HistoricalCaptureEnabled")
    on = value == 1
    return Check("recording", "Xbox background recording", IMPROVE if on else GOOD, "On" if on else "Off",
                 "Xbox Game Bar can record the last minutes of every game all the time, which costs frames per "
                 "second. Turning it off keeps Game Bar and Win+Alt+R recording; only the always-on recording "
                 "stops. Clip apps like OBS, Medal or Clip Studio don't need it.", "Turn off" if on else "",
                 ch.has("recording"))


def check_mouse(ch):
    speed, _ = reg_get("HKCU", MOUSE, "MouseSpeed")
    on = str(speed) != "0"
    return Check("mouse", "Mouse acceleration ('Enhance pointer precision')", IMPROVE if on else GOOD,
                 "On" if on else "Off",
                 "With it on, a fast flick moves the pointer further than a slow one of the same distance, so your "
                 "aim changes with speed. Most players of shooters (Valorant, CS2, Apex) turn it off for "
                 "consistent aim. You may want to adjust your sensitivity a little afterwards.",
                 "Turn off" if on else "", ch.has("mouse"))


def check_visual(ch):
    transparency, _ = reg_get("HKCU", PERSONALIZE, "EnableTransparency")
    anim, _ = reg_get("HKCU", METRICS, "MinAnimate")
    on = transparency != 0 or str(anim) != "0"
    small = psutil.virtual_memory().total <= 8.5 * 1024 ** 3
    status = (IMPROVE if small else INFO) if on else GOOD
    return Check("visual", "See-through effects and window animations", status, "On" if on else "Off",
                 "Turning off transparency and the minimise/maximise animation makes Windows feel snappier on PCs "
                 "with 8 GB of memory or less, or without a graphics card. On a strong PC you won't notice a "
                 "difference, so it's optional.", "Turn off" if on else "", ch.has("visual"))


def check_restart():
    days = (time.time() - psutil.boot_time()) / 86400
    old = days >= 7
    return Check("restart", "Last restart", IMPROVE if old else GOOD,
                 ("%d days ago" % days) if days >= 1 else "Today",
                 "A restart clears memory leaks and finishes updates. 'Shut down' doesn't count when Fast Startup is "
                 "on: Windows only sleeps deeply. Restart (not shut down) about once a week."
                 + ("  Your PC hasn't restarted for %d days." % days if old else ""))


def check_space():
    sysdrive = (os.environ.get("SystemDrive") or "C:") + "\\"
    try:
        import shutil
        u = shutil.disk_usage(sysdrive)
    except OSError:
        return None
    low = u.free < 15 * 1024 ** 3 or u.free / u.total < 0.10
    from .ui.theme import size_text
    return Check("space", "Free space on the Windows drive", IMPROVE if low else GOOD,
                 "%s free" % size_text(u.free),
                 "Windows and games need free space for updates, the page file and shader caches. Below about 15 GB "
                 "things slow down and updates fail.", "Clean junk" if low else "", goto="junk" if low else "")


# ---------------------------------------------------------------- power
class _GUID(ctypes.Structure):
    _fields_ = [("b", ctypes.c_ubyte * 16)]


def _guid(text):
    g = _GUID()
    ctypes.memmove(g.b, uuid.UUID(text).bytes_le, 16)
    return g


OVERLAY_BEST = "ded574b5-45a0-4f42-8737-46345c09c238"
OVERLAY_BALANCED = "00000000-0000-0000-0000-000000000000"
PLAN_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
PLAN_HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
PLAN_ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
PLAN_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"


def power_state():
    """{"plan": guid, "plan_name": str, "overlay": guid or None}."""
    out = {"plan": "", "plan_name": "", "overlay": None}
    if not IS_WINDOWS:
        return out
    try:
        text = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=10,
                              creationflags=NO_WINDOW).stdout
        m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})\s+\((.*)\)", text, re.I)
        if m:
            out["plan"], out["plan_name"] = m.group(1).lower(), m.group(2)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        g = _GUID()
        if ctypes.windll.powrprof.PowerGetEffectiveOverlayScheme(ctypes.byref(g)) == 0:
            out["overlay"] = str(uuid.UUID(bytes_le=bytes(g.b)))
    except (OSError, AttributeError):
        pass
    return out


def _set_overlay(guid):
    try:
        return ctypes.windll.powrprof.PowerSetActiveOverlayScheme(_guid(guid)) == 0
    except (OSError, AttributeError):
        return False


def _set_plan(guid):
    try:
        return subprocess.run(["powercfg", "/setactive", guid], capture_output=True, timeout=10,
                              creationflags=NO_WINDOW).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def is_fast(state):
    return state["plan"] in (PLAN_HIGH, PLAN_ULTIMATE) or state["overlay"] == OVERLAY_BEST


def on_battery():
    try:
        b = psutil.sensors_battery()
    except (AttributeError, RuntimeError):
        return None
    return None if b is None else not b.power_plugged


def check_power(ch):
    st = power_state()
    fast = is_fast(st)
    name = st["plan_name"] or "Unknown"
    if st["overlay"] == OVERLAY_BEST:
        name += " · Best performance"
    battery = on_battery()
    what = ("How hard Windows lets your processor and graphics work. Best performance gives games and apps full "
            "speed; the cost is more heat, fan noise and power use.")
    if battery is not None:
        what += " On a laptop, plug in the charger when you play: on battery the PC holds itself back anyway."
    return Check("power", "Power mode", GOOD if fast else IMPROVE, name, what,
                 "" if fast else "Use best performance", ch.has("power"))


def set_power_fast(ch, tid="power"):
    st = power_state()
    ch.remember(tid, {"plan": st["plan"], "overlay": st["overlay"]})
    if is_fast(st):
        return True
    if st["plan"] == PLAN_SAVER:
        _set_plan(PLAN_BALANCED)
    if _set_overlay(OVERLAY_BEST) and power_state()["overlay"] == OVERLAY_BEST:
        return True
    return _set_plan(PLAN_HIGH)


def restore_power(ch, tid="power"):
    entry = ch.undo(tid)
    if not entry:
        return False
    data = entry.get("data") or {}
    if data.get("plan") and power_state()["plan"] != data["plan"]:
        _set_plan(data["plan"])
    if data.get("overlay") is not None:
        _set_overlay(data["overlay"])
    return True


# ---------------------------------------------------------------- applying and undoing checks
SPI_SETMOUSE, SPI_SETANIMATION = 0x0004, 0x0049
SPIF = 0x01 | 0x02          # SPIF_UPDATEINIFILE | SPIF_SENDCHANGE


def _apply_mouse_live():
    if not IS_WINDOWS:
        return
    vals = [int(reg_get("HKCU", MOUSE, n)[0] or 0) for n in ("MouseThreshold1", "MouseThreshold2", "MouseSpeed")]
    arr = (ctypes.c_int * 3)(*vals)
    ctypes.windll.user32.SystemParametersInfoW(SPI_SETMOUSE, 0, arr, SPIF)


class ANIMATIONINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("iMinAnimate", ctypes.c_int)]


def _apply_animation_live():
    if not IS_WINDOWS:
        return
    on = str(reg_get("HKCU", METRICS, "MinAnimate")[0]) != "0"
    info = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), 1 if on else 0)
    ctypes.windll.user32.SystemParametersInfoW(SPI_SETANIMATION, ctypes.sizeof(info), ctypes.byref(info), SPIF)


def apply(check_id, settings):
    """Makes the recommended change. True when done."""
    ch = Changes(settings)
    if check_id == "gamemode":
        ch.write("gamemode", [("HKCU", GAMEBAR, "AutoGameModeEnabled", 1, winreg.REG_DWORD)])
    elif check_id == "recording":
        ch.write("recording", [("HKCU", DVR, "HistoricalCaptureEnabled", 0, winreg.REG_DWORD)])
    elif check_id == "mouse":
        ch.write("mouse", [("HKCU", MOUSE, "MouseSpeed", "0", winreg.REG_SZ),
                           ("HKCU", MOUSE, "MouseThreshold1", "0", winreg.REG_SZ),
                           ("HKCU", MOUSE, "MouseThreshold2", "0", winreg.REG_SZ)])
        _apply_mouse_live()
    elif check_id == "visual":
        ch.write("visual", [("HKCU", PERSONALIZE, "EnableTransparency", 0, winreg.REG_DWORD),
                            ("HKCU", METRICS, "MinAnimate", "0", winreg.REG_SZ)])
        _apply_animation_live()
    elif check_id == "power":
        return set_power_fast(ch)
    else:
        return False
    return True


def undo(check_id, settings):
    ch = Changes(settings)
    if check_id in ("power", "boost-power"):
        return restore_power(ch, check_id)
    done = ch.undo(check_id) is not None
    if check_id == "mouse":
        _apply_mouse_live()
    elif check_id == "visual":
        _apply_animation_live()
    return done


def undo_all(settings):
    for tid in list(Changes(settings).all()):
        if tid.startswith("startup:"):
            Changes(settings).undo(tid)
        elif tid.startswith("gpu:"):
            Changes(settings).undo(tid)
        else:
            undo(tid, settings)


# ---------------------------------------------------------------- graphics drivers
DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
DRIVER_PAGES = {
    "nvidia": ("Get the NVIDIA app", "https://www.nvidia.com/en-us/software/nvidia-app/"),
    "amd": ("Open AMD drivers", "https://www.amd.com/en/support/download/drivers.html"),
    "intel": ("Open Intel driver assistant", "https://www.intel.com/content/www/us/en/support/detect.html"),
}


@dataclass
class GPU:
    name: str
    vendor: str             # nvidia, amd, intel or ""
    date: float             # driver date (timestamp), 0 when unknown
    version: str

    @property
    def integrated(self):
        n = self.name.lower()
        return self.vendor == "intel" and "arc" not in n or (self.vendor == "amd" and "radeon(tm) graphics" in n)


def gpus():
    out = []
    try:
        root = winreg.OpenKey(HKLM, DISPLAY_CLASS)
    except OSError:
        return out
    with root:
        for i in range(32):
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(root, sub) as k:
                    def q(n):
                        try:
                            return str(winreg.QueryValueEx(k, n)[0])
                        except OSError:
                            return ""
                    name, date, ver, provider = q("DriverDesc"), q("DriverDate"), q("DriverVersion"), q("ProviderName")
            except OSError:
                continue
            low = (name + " " + provider).lower()
            if not name or "basic display" in low or "remote" in low or "virtual" in low or "parsec" in low:
                continue
            vendor = "nvidia" if "nvidia" in low else "amd" if ("amd" in low or "radeon" in low or "ati " in low) \
                else "intel" if "intel" in low else ""
            ts = 0.0
            try:
                ts = time.mktime(time.strptime(date, "%m-%d-%Y"))
            except (ValueError, OverflowError):
                pass
            out.append(GPU(name, vendor, ts, ver))
    return out


def check_drivers():
    cards = gpus()
    if not cards:
        return None
    old = [g for g in cards if g.date and time.time() - g.date > 365 * 86400]
    lines = ["%s: driver from %s" % (g.name, time.strftime("%B %Y", time.localtime(g.date)) if g.date else
                                      "an unknown date") for g in cards]
    what = ("Graphics drivers bring fixes and speed-ups for new games; old ones are a common cause of crashes and "
            "stutter. " + "; ".join(lines) + ".")
    links = [DRIVER_PAGES[g.vendor] for g in old if g.vendor in DRIVER_PAGES]
    if old and any(g.integrated for g in old) and len(cards) > 1:
        what += " The built-in graphics also matters on a laptop: the screen goes through it."
    return Check("drivers", "Graphics drivers", IMPROVE if old else GOOD,
                 ("%d out of date" % len(old)) if old else "Up to date", what, links=links)


# ---------------------------------------------------------------- startup apps
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"

STARTUP_KEEP = ("securityhealth", "windowsdefender", "defender", "rtkaud", "realtek", "synaptics", "syntp",
                "elantech", "etdctrl", "igfx", "ctfmon", "nahimic", "dolby", "waves", "maxxaudio", "bluetooth", "touchpad",
                "precisiontouchpad", "intel\\", "amdnoise", "vgtray", "vanguard", "faceit", "easyanticheat")
STARTUP_SAFE = ("steam", "epicgameslauncher", "epic games", "discord", "spotify", "teams", "skype", "origin",
                "eadesktop", "ea app", "upc.exe", "ubisoft", "battle.net", "battlenet", "overwolf", "medal", "opera",
                "brave", "chrome", "msedge", "edgeautolaunch", "microsoftedgeautolaunch", "googleupdate", "adobe",
                "ccxprocess", "cortana", "whatsapp", "telegram", "zoom", "ccleaner", "utorrent", "qbittorrent",
                "bittorrent", "messenger", "slack", "notion", "figma", "riotclient", "rockstar", "goggalaxy",
                "galaxyclient", "playnite", "itunes", "icloud", "quicktime", "java update", "jusched", "skypebridge",
                "cursor.exe", "perplexity", "chatgpt", "claude.exe")


@dataclass
class StartupItem:
    name: str               # registry value or shortcut file name
    command: str
    exe: str
    source: str             # "HKCU Run", "HKLM Run", "Startup folder"...
    approved: tuple         # (hive, path) of its StartupApproved key
    enabled: bool
    title: str = ""
    what: str = ""
    safety: str = CHOICE
    advice: str = ""
    locked: str = ""

    @property
    def tid(self):
        return "startup:%s:%s:%s" % (self.approved[0], self.approved[1].rsplit("\\", 1)[-1], self.name)


def _exe_of(command):
    c = os.path.expandvars((command or "").strip())
    m = re.match(r'^"([^"]+)"', c)
    if m:
        return m.group(1)
    m = re.match(r"^(.+?\.exe)\b", c, re.I)
    return m.group(1) if m else c.split(" ")[0]


def _approved(hive, path, name):
    value, _ = reg_get(hive, path, name)
    if not isinstance(value, (bytes, bytearray)) or not value:
        return True
    return value[0] & 1 == 0            # 02/06 = on, 03/07 = off


def startup_items():
    admin = winapi.is_admin()
    items = []
    for hive, run, approved, source in (("HKCU", RUN, APPROVED + r"\Run", "Starts for you"),
                                        ("HKLM", RUN, APPROVED + r"\Run", "Starts for every account"),
                                        ("HKLM", RUN32, APPROVED + r"\Run32", "Starts for every account")):
        try:
            key = winreg.OpenKey(HIVES[hive], run, 0, winreg.KEY_READ | (winreg.KEY_WOW64_64KEY if hive == "HKLM"
                                                                         else 0))
        except OSError:
            continue
        with key:
            for i in range(500):
                try:
                    name, cmd, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                it = StartupItem(name, str(cmd), _exe_of(str(cmd)), source, (hive, approved),
                                 _approved(hive, approved, name))
                if hive == "HKLM" and not admin:
                    it.locked = "Needs administrator"
                items.append(it)
    for folder, hive, source in ((os.path.join(os.environ.get("APPDATA", ""),
                                               r"Microsoft\Windows\Start Menu\Programs\Startup"), "HKCU",
                                  "Startup folder"),
                                 (os.path.join(os.environ.get("ProgramData", ""),
                                               r"Microsoft\Windows\Start Menu\Programs\Startup"), "HKLM",
                                  "Startup folder (every account)")):
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for f in names:
            if f.lower() == "desktop.ini":
                continue
            path = os.path.join(folder, f)
            target = path
            if f.lower().endswith(".lnk"):
                from .leftovers import lnk_target
                target = lnk_target(path) or path
            it = StartupItem(f, path, target, source, (hive, APPROVED + r"\StartupFolder"),
                             _approved(hive, APPROVED + r"\StartupFolder", f))
            if hive == "HKLM" and not admin:
                it.locked = "Needs administrator"
            items.append(it)
    for it in items:
        _explain_startup(it)
    items.sort(key=lambda i: ({SAFE: 0, CHOICE: 1, KEEP: 2}[i.safety], i.title.lower()))
    return items


def _explain_startup(it):
    desc = memory.describe_exe(it.exe) if os.path.isfile(it.exe) else ""
    if desc.lower() in ("update", "updater", "launcher", "helper", "setup", "app", "application"):
        desc = ""                       # Discord's "Update.exe": the startup entry's own name says more
    it.title = desc or os.path.splitext(it.name)[0]
    low = (it.name + " " + it.exe + " " + desc).lower()
    if any(k in low for k in STARTUP_KEEP):
        it.safety = KEEP
        it.what = "Part of a driver, your antivirus or anti-cheat (for example sound, touchpad or Vanguard)."
        it.advice = "Keep it on. Without it a device, a security feature or a game's anti-cheat may not work."
    elif any(k in low for k in STARTUP_SAFE):
        it.safety = SAFE
        it.what = "An app or launcher that opens itself when Windows starts, before you need it."
        it.advice = ("Safe to turn off. Windows starts faster and the app stops using memory in the background; "
                     "it still opens normally when you click it.")
    else:
        it.safety = CHOICE
        it.what = "A program that starts itself with Windows."
        it.advice = ("Turn it off if you don't need it the moment Windows starts. You can still open it yourself, "
                     "and turn it back on here any time.")
    if not os.path.exists(it.exe) and os.path.isabs(it.exe):
        it.what += " Its program file is missing, so it does nothing anyway."
        it.safety = SAFE
        it.advice = "Safe to turn off: the program it would start isn't there any more."


def set_startup(item, enabled, settings):
    """Turns a startup app on or off with Windows' own switch (the one Task Manager uses)."""
    hive, path = item.approved
    if enabled:
        data = bytes([2]) + bytes(11)
    else:
        ft = int((time.time() + 11644473600) * 10_000_000)
        data = bytes([3, 0, 0, 0]) + struct.pack("<Q", ft)
    Changes(settings).write(item.tid, [(hive, path, item.name, data, winreg.REG_BINARY)])
    item.enabled = enabled


# ---------------------------------------------------------------- graphics card per game
GPU_PREFS = r"Software\Microsoft\DirectX\UserGpuPreferences"
SKIP_EXE = re.compile(r"crash|unins|setup|redist|vc_?redist|dxsetup|directx|report|helper|eac|easyanticheat|"
                      r"battleye|be_service|update|launcher_helper|ue4prereq|uninstall|dotnet|vcredist|cefprocess|"
                      r"webhelper|overlay", re.I)


@dataclass
class Game:
    name: str
    exe: str
    store: str
    preference: int = 0     # 0 Windows decides, 1 power saving, 2 high performance


def _steam_libraries():
    steam, _ = reg_get("HKCU", r"Software\Valve\Steam", "SteamPath")
    libs = []
    if steam:
        steam = os.path.normpath(steam)
        libs.append(steam)
        try:
            with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
                for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                    libs.append(os.path.normpath(m.group(1).replace("\\\\", "\\")))
        except OSError:
            pass
    seen, out = set(), []
    for lib in libs:
        if lib.lower() not in seen and os.path.isdir(os.path.join(lib, "steamapps")):
            seen.add(lib.lower())
            out.append(lib)
    return out


def _main_exe(folder, depth=5):
    best, size = "", 0
    base = folder.rstrip("\\").count("\\")
    for dirpath, dirs, files in os.walk(folder):
        if dirpath.count("\\") - base >= depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if not SKIP_EXE.search(d) and d.lower() not in ("_commonredist", "redist",
                                                                                      "support", "tools")]
        for f in files:
            if f.lower().endswith(".exe") and not SKIP_EXE.search(f):
                try:
                    s = os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    continue
                if s > size:
                    best, size = os.path.join(dirpath, f), s
    return best


def find_games():
    games = []
    for lib in _steam_libraries():
        apps = os.path.join(lib, "steamapps")
        try:
            manifests = [f for f in os.listdir(apps) if f.startswith("appmanifest_") and f.endswith(".acf")]
        except OSError:
            continue
        for mf in manifests:
            try:
                with open(os.path.join(apps, mf), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            name = re.search(r'"name"\s+"([^"]+)"', text)
            folder = re.search(r'"installdir"\s+"([^"]+)"', text)
            if not name or not folder:
                continue
            if re.search(r"redistributable|steamworks|proton|soundtrack|dedicated server|sdk", name.group(1), re.I):
                continue
            path = os.path.join(apps, "common", folder.group(1))
            exe = _main_exe(path) if os.path.isdir(path) else ""
            if exe:
                games.append(Game(name.group(1), exe, "Steam"))
    manifests = os.path.join(os.environ.get("ProgramData", ""), r"Epic\EpicGamesLauncher\Data\Manifests")
    try:
        for f in os.listdir(manifests):
            if not f.endswith(".item"):
                continue
            try:
                with open(os.path.join(manifests, f), encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            home = data.get("InstallLocation", "")
            if not home or not os.path.isdir(home):
                continue
            # the launch file is often a small launcher (PlayGTAV.exe); the graphics card choice must go on the game
            exe = _main_exe(home) or os.path.join(home, data.get("LaunchExecutable", ""))
            if os.path.isfile(exe):
                games.append(Game(data.get("DisplayName") or os.path.basename(exe), exe, "Epic Games"))
    except OSError:
        pass
    games += _riot_games()
    seen, out = set(), []
    for g in games:
        if g.exe.lower() not in seen:
            seen.add(g.exe.lower())
            g.preference = gpu_preference(g.exe)
            out.append(g)
    out.sort(key=lambda g: g.name.lower())
    return out


RIOT_EXES = {"valorant": ("VALORANT", r"ShooterGame\Binaries\Win64\VALORANT-Win64-Shipping.exe"),
             "league_of_legends": ("League of Legends", r"Game\League of Legends.exe")}


def _riot_games():
    """Riot writes where each game lives in ProgramData/Riot Games/Metadata/<game>.live/*.product_settings.yaml."""
    out = []
    meta = os.path.join(os.environ.get("ProgramData", ""), "Riot Games", "Metadata")
    for key, (name, rel) in RIOT_EXES.items():
        settings = os.path.join(meta, key + ".live", key + ".live.product_settings.yaml")
        try:
            with open(settings, encoding="utf-8", errors="replace") as f:
                m = re.search(r'product_install_full_path:\s*"([^"]+)"', f.read())
        except OSError:
            m = None
        homes = [m.group(1)] if m else []
        homes += [os.path.join(d.root, "Riot Games", name if key != "valorant" else os.path.join("VALORANT", "live"))
                  for d in winapi.drives()]
        for home in homes:
            exe = os.path.normpath(os.path.join(home, rel))
            if os.path.isfile(exe):
                out.append(Game(name, exe, "Riot"))
                break
    return out


def _parse_pref(text):
    parts = [p for p in (text or "").split(";") if p.strip()]
    return dict(p.split("=", 1) for p in parts if "=" in p)


def gpu_preference(exe):
    value, _ = reg_get("HKCU", GPU_PREFS, exe)
    try:
        return int(_parse_pref(value).get("GpuPreference", 0))
    except (TypeError, ValueError):
        return 0


def set_gpu_preference(exe, pref, settings):
    """Sets 'GpuPreference' for one program, keeping any other options Windows stored next to it."""
    value, _ = reg_get("HKCU", GPU_PREFS, exe)
    parts = _parse_pref(value if isinstance(value, str) else "")
    parts["GpuPreference"] = str(pref)
    text = "".join("%s=%s;" % kv for kv in parts.items())
    Changes(settings).write("gpu:" + exe.lower(), [("HKCU", GPU_PREFS, exe, text, winreg.REG_SZ)])


def two_gpus():
    cards = gpus()
    return len(cards) >= 2 and any(g.integrated for g in cards) and any(not g.integrated for g in cards)


# ---------------------------------------------------------------- Game Boost
def boost_candidates():
    """Running apps it may close for a game: everything that isn't Windows' own, Tidy, or a game launcher."""
    return [a for a in memory.apps() if a.safety != KEEP]


def start_boost(settings, close_names):
    """Best performance power, close the chosen apps (politely), hand back unused memory."""
    ch = Changes(settings)
    before = psutil.virtual_memory().available
    set_power_fast(ch, "boost-power")
    closing = [a for a in memory.apps() if a.name in set(close_names) and a.safety != KEEP]
    left = memory.close(closing, wait=3.0) if closing else []
    memory.trim()
    settings.set("boost_on", True)
    return {"closed": [a.title for a in closing if a.name not in left], "left": left,
            "freed": max(0, psutil.virtual_memory().available - before)}


def stop_boost(settings):
    restore_power(Changes(settings), "boost-power")
    settings.set("boost_on", False)
