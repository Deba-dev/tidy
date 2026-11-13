"""Speed up: every change is undone exactly. Runs against HKCU\\Software\\TidyTest only, never real settings,
and never changes the real power plan."""
import os
import winreg

import pytest

from tidy import optimize
from tidy.knowledge import KEEP, SAFE
from tidy.settings import Settings

BASE = r"Software\TidyTest"


def _wipe():
    def rm(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    rm(path + "\\" + sub)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass
    rm(BASE)


@pytest.fixture
def s(tmp_path, monkeypatch):
    _wipe()
    for name in ("GAMEBAR", "DVR", "MOUSE", "PERSONALIZE", "METRICS", "GPU_PREFS", "APPROVED"):
        monkeypatch.setattr(optimize, name, BASE + "\\" + name)
    monkeypatch.setattr(optimize, "_apply_mouse_live", lambda: None)
    monkeypatch.setattr(optimize, "_apply_animation_live", lambda: None)
    yield Settings(str(tmp_path / "s.json"))
    _wipe()


def test_change_and_undo_restores_exactly(s):
    optimize.reg_set("HKCU", optimize.MOUSE, "MouseSpeed", "1", winreg.REG_SZ)
    optimize.reg_set("HKCU", optimize.MOUSE, "MouseThreshold1", "6", winreg.REG_SZ)
    assert optimize.check_mouse(optimize.Changes(s)).status == optimize.IMPROVE
    optimize.apply("mouse", s)
    assert optimize.reg_get("HKCU", optimize.MOUSE, "MouseSpeed")[0] == "0"
    assert optimize.check_mouse(optimize.Changes(s)).undo
    optimize.apply("mouse", s)                      # applying twice keeps the first "before"
    optimize.undo("mouse", s)
    assert optimize.reg_get("HKCU", optimize.MOUSE, "MouseSpeed")[0] == "1"
    assert optimize.reg_get("HKCU", optimize.MOUSE, "MouseThreshold1")[0] == "6"
    assert optimize.reg_get("HKCU", optimize.MOUSE, "MouseThreshold2") == (None, None)    # wasn't there: removed
    assert not optimize.Changes(s).all()


def test_gamemode_and_recording(s):
    optimize.reg_set("HKCU", optimize.GAMEBAR, "AutoGameModeEnabled", 0, winreg.REG_DWORD)
    optimize.reg_set("HKCU", optimize.DVR, "HistoricalCaptureEnabled", 1, winreg.REG_DWORD)
    ch = optimize.Changes(s)
    assert optimize.check_gamemode(ch).status == optimize.IMPROVE
    assert optimize.check_recording(ch).status == optimize.IMPROVE
    optimize.apply("gamemode", s)
    optimize.apply("recording", s)
    assert optimize.check_gamemode(ch).status == optimize.GOOD
    assert optimize.check_recording(ch).status == optimize.GOOD
    optimize.undo_all(s)
    assert optimize.reg_get("HKCU", optimize.GAMEBAR, "AutoGameModeEnabled")[0] == 0
    assert optimize.reg_get("HKCU", optimize.DVR, "HistoricalCaptureEnabled")[0] == 1


def test_gpu_preference_keeps_other_options(s):
    exe = r"D:\Games\Some Game\game.exe"
    optimize.reg_set("HKCU", optimize.GPU_PREFS, exe, "AppStatus=0;SwapEffectUpgradeEnable=1;", winreg.REG_SZ)
    optimize.set_gpu_preference(exe, 2, s)
    value = optimize.reg_get("HKCU", optimize.GPU_PREFS, exe)[0]
    assert value == "AppStatus=0;SwapEffectUpgradeEnable=1;GpuPreference=2;"
    assert optimize.gpu_preference(exe) == 2
    optimize.Changes(s).undo("gpu:" + exe.lower())
    assert optimize.reg_get("HKCU", optimize.GPU_PREFS, exe)[0] == "AppStatus=0;SwapEffectUpgradeEnable=1;"


def test_startup_switch(s):
    item = optimize.StartupItem("Spotify", r'"C:\x\Spotify.exe" /minimized', r"C:\x\Spotify.exe", "Starts for you",
                                ("HKCU", optimize.APPROVED + r"\Run"), True)
    assert optimize._approved("HKCU", item.approved[1], "Spotify")          # no value: on
    optimize.set_startup(item, False, s)
    raw = optimize.reg_get("HKCU", item.approved[1], "Spotify")[0]
    assert raw[0] == 3 and len(raw) == 12 and not optimize._approved("HKCU", item.approved[1], "Spotify")
    optimize.set_startup(item, True, s)
    assert optimize._approved("HKCU", item.approved[1], "Spotify")
    optimize.Changes(s).undo(item.tid)
    assert optimize.reg_get("HKCU", item.approved[1], "Spotify") == (None, None)


def test_startup_explained():
    keep = optimize.StartupItem("SecurityHealth", "", r"C:\Windows\System32\SecurityHealthSystray.exe", "",
                                ("HKLM", ""), True)
    steam = optimize.StartupItem("Steam", "", r"C:\nowhere\steam.exe", "", ("HKCU", ""), True)
    idea = optimize.StartupItem("IntelliJ Toolbox", "", r"C:\nowhere\toolbox.exe", "", ("HKCU", ""), True)
    for it in (keep, steam, idea):
        optimize._explain_startup(it)
    assert keep.safety == KEEP and steam.safety == SAFE
    assert idea.safety == SAFE and "missing" in idea.what          # its program is gone, so it does nothing


def test_command_parsing():
    assert optimize._exe_of(r'"C:\Program Files\App\app.exe" --tray') == r"C:\Program Files\App\app.exe"
    assert optimize._exe_of(r"C:\Tools\tool.exe -silent") == r"C:\Tools\tool.exe"
    assert optimize._parse_pref("GpuPreference=2;AppStatus=0;") == {"GpuPreference": "2", "AppStatus": "0"}


def test_boost_restores_power_without_touching_checkup_choice(s, monkeypatch):
    calls = []
    state = {"plan": optimize.PLAN_BALANCED, "plan_name": "Balanced", "overlay": optimize.OVERLAY_BALANCED}
    monkeypatch.setattr(optimize, "power_state", lambda: dict(state))

    def overlay(g):
        calls.append(("overlay", g))
        state["overlay"] = g
        return True

    def plan(g):
        calls.append(("plan", g))
        state["plan"] = g
        return True
    monkeypatch.setattr(optimize, "_set_overlay", overlay)
    monkeypatch.setattr(optimize, "_set_plan", plan)
    monkeypatch.setattr(optimize.memory, "apps", lambda: [])
    monkeypatch.setattr(optimize.memory, "trim", lambda: 0)
    res = optimize.start_boost(s, [])
    assert state["overlay"] == optimize.OVERLAY_BEST and s.get("boost_on") and res["closed"] == []
    optimize.stop_boost(s)
    assert state["overlay"] == optimize.OVERLAY_BALANCED and not s.get("boost_on")
    assert not optimize.Changes(s).has("power")


def test_checks_run(s):
    ids = [c.id for c in optimize.checks(s)]
    assert {"gamemode", "recording", "power", "mouse", "restart"} <= set(ids)


def test_reads_this_pc():
    optimize.power_state()
    optimize.gpus()
    items = optimize.startup_items()
    assert all(i.title and i.advice for i in items)
    games = optimize.find_games()
    assert all(os.path.isabs(g.exe) for g in games)
