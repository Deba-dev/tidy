"""Leftovers (on fake program folders in a temp folder) and Memory (on a throwaway test process)."""
import os
import subprocess
import sys
import time

import pytest

from tidy import deleter, leftovers, memory
from tidy.knowledge import CHOICE, KEEP, SAFE

OLD = time.time() - 400 * 86400


def age(path, when=OLD):
    for dirpath, dirs, files in os.walk(path):
        for name in files + dirs:
            os.utime(os.path.join(dirpath, name), (when, when))
    os.utime(path, (when, when))


@pytest.fixture
def place(tmp_path, monkeypatch):
    root = tmp_path / "Programs"
    root.mkdir()
    (root / "OldApp").mkdir()
    (root / "OldApp" / "data.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    (root / "OldApp" / "old.exe").write_bytes(b"MZ")
    age(root / "OldApp")
    (root / "Discord").mkdir()
    (root / "Discord" / "big.bin").write_bytes(b"d" * (2 * 1024 * 1024))
    age(root / "Discord")
    (root / "EmptyThing").mkdir()
    age(root / "EmptyThing")
    (root / "FreshApp").mkdir()
    (root / "FreshApp" / "new.bin").write_bytes(b"n" * (2 * 1024 * 1024))
    (root / "Microsoft").mkdir()
    (root / "Microsoft" / "keep.bin").write_bytes(b"m" * (2 * 1024 * 1024))
    age(root / "Microsoft")
    (root / "InstalledHere").mkdir()
    (root / "InstalledHere" / "app.bin").write_bytes(b"i" * (2 * 1024 * 1024))
    age(root / "InstalledHere")
    monkeypatch.setattr(leftovers, "roots", lambda: [(str(root), False)])
    monkeypatch.setattr(leftovers, "broken_shortcuts", lambda: [])
    programs = [leftovers.Program("Discord", "Discord Inc.", []),
                leftovers.Program("Some Tool", "Acme", [leftovers.knowledge.norm(str(root / "InstalledHere"))])]
    matcher = leftovers.Matcher(programs, running=set())
    monkeypatch.setattr(leftovers, "cached_matcher", lambda max_age=30: matcher)
    return root, matcher


def test_finds_only_real_leftovers(place):
    root, matcher = place
    groups = {g.id: g for g in leftovers.find(matcher=matcher)}
    names = [os.path.basename(e.path) for e in groups["leftovers"].entries]
    assert names == ["OldApp"]                                  # not Discord, Fresh, Microsoft or InstalledHere
    e = groups["leftovers"].entries[0]
    assert e.info.safety == CHOICE and e.origin == "leftover" and "portable" in e.info.advice
    assert [os.path.basename(x.path) for x in groups["empty"].entries] == ["EmptyThing"]
    assert groups["empty"].entries[0].info.safety == SAFE


def test_deleter_rechecks_leftovers(place):
    root, matcher = place
    groups = {g.id: g for g in leftovers.find(matcher=matcher)}
    old = groups["leftovers"].entries[0]
    matcher.names.add("oldapp")                                 # it got installed again meanwhile
    assert "uses it again" in deleter.refuse(old)
    matcher.names.discard("oldapp")
    assert deleter.refuse(old) == ""
    rep = deleter.delete([old, groups["empty"].entries[0]], permanent=True)
    assert not (root / "OldApp").exists() and not (root / "EmptyThing").exists()
    assert rep.freed == 2 * 1024 * 1024 + 2


def test_leftover_outside_program_places_is_refused(tmp_path, place):
    stray = tmp_path / "elsewhere"
    stray.mkdir()
    from tidy.junk import Entry
    from tidy.knowledge import Info
    e = Entry(str(stray), "path", 0, Info("x", "x", SAFE, "x"), origin="leftover")
    assert deleter.refuse(e) == "Not in a place where programs install."


def test_matcher_ignores_installers_that_claim_a_whole_root(tmp_path, monkeypatch):
    root = tmp_path / "PF"
    (root / "Gone").mkdir(parents=True)
    monkeypatch.setattr(leftovers, "roots", lambda: [(str(root), True)])
    m = leftovers.Matcher([leftovers.Program("Lazy", "", [leftovers.knowledge.norm(str(root))])], running=set())
    assert m.owner(str(root / "Gone"), "Gone") == ""


def test_shortcut_target(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows only")
    target = tmp_path / "gone.exe"
    target.write_bytes(b"MZ")
    lnk = tmp_path / "Gone.lnk"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); $s.TargetPath='%s'; $s.Save()"
          % (lnk, target))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60)
    if r.returncode != 0 or not lnk.exists():
        pytest.skip("couldn't make a shortcut here")
    assert os.path.normcase(leftovers.lnk_target(str(lnk))) == os.path.normcase(str(target))
    assert leftovers.verify(str(lnk)) == "The shortcut works again."
    target.unlink()
    assert leftovers.verify(str(lnk)) == ""


# ---------------------------------------------------------------- memory
def test_status():
    st = memory.status()
    assert st.total > st.available > 0 and 0 < st.percent < 100
    assert st.level in (SAFE, CHOICE, KEEP)


def test_apps_list_explains_windows_and_tidy():
    apps = {a.name: a for a in memory.apps()}
    assert apps["<tidy>"].safety == KEEP
    if "explorer.exe" in apps:
        assert apps["explorer.exe"].safety == KEEP
    assert all(a.title and a.what and a.advice for a in apps.values())


def test_close_needs_force_for_windowless(tmp_path):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        app = memory.App("sleeper.exe", "Sleeper", "test", CHOICE, "test", pids=[p.pid])
        left = memory.close([app], wait=1.0)
        assert p.poll() is None and left                          # no window to ask: still running
        memory.close([app], force=True, wait=5.0)
        assert p.wait(timeout=5) is not None
    finally:
        if p.poll() is None:
            p.kill()


def test_close_never_touches_keep():
    app = memory.App("x.exe", "X", "x", KEEP, "x", pids=[os.getpid()])
    assert memory.close([app], force=True, wait=0.1) == []
    assert True                                                   # still alive to say so


def test_trim_runs():
    assert memory.trim() >= 0
