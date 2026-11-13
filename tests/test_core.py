"""Core tests: explanations, safety guard, scanning, duplicates and deleting (in a temp folder only)."""
import os
import time

import pytest

from tidy import deleter, duplicates, junk, knowledge, scanner
from tidy.knowledge import CHOICE, KEEP, SAFE

WIN = os.environ.get("SystemRoot", r"C:\Windows")
SYS = os.environ.get("SystemDrive", "C:") + "\\"
HOME = os.environ.get("USERPROFILE", r"C:\Users\me")
LOCAL = os.environ.get("LOCALAPPDATA", HOME + r"\AppData\Local")


@pytest.mark.parametrize("path,safety", [
    (WIN, KEEP),
    (WIN + r"\System32\drivers\etc\hosts", KEEP),
    (WIN + r"\Temp", SAFE),
    (WIN + r"\Temp\abc.tmp", SAFE),
    (WIN + r"\SoftwareDistribution\Download", SAFE),
    (WIN + r"\WinSxS", KEEP),
    (WIN + r"\Installer", KEEP),
    (SYS + "pagefile.sys", KEEP),
    (SYS + "hiberfil.sys", KEEP),
    (SYS + "Windows.old", KEEP),
    (SYS + "System Volume Information", KEEP),
    (SYS + r"Program Files\Some App\app.exe", KEEP),
    (SYS + r"Program Files (x86)\Steam\steamapps\shadercache\730", SAFE),
    (SYS + r"Program Files (x86)\Steam\steamapps\common", KEEP),
    (SYS + r"Program Files (x86)\Steam\steamapps\common\Some Game", KEEP),
    (SYS + r"Program Files\nodejs\node_modules\npm", KEEP),
    (HOME, KEEP),
    (HOME + r"\Documents", KEEP),
    (HOME + r"\Documents\cv.docx", CHOICE),
    (HOME + r"\Downloads", KEEP),
    (HOME + r"\Downloads\setup.exe", CHOICE),
    (HOME + r"\Videos\clip.mp4", CHOICE),
    (HOME + r"\code\site\node_modules", CHOICE),
    (HOME + r"\code\site\.git", KEEP),
    (HOME + r"\code\app\__pycache__", SAFE),
    (HOME + r"\AppData", KEEP),
    (LOCAL + r"\Discord\settings.json", KEEP),
    (LOCAL + r"\Temp", SAFE),
    (LOCAL + r"\Temp\x\y.dat", SAFE),
    (LOCAL + r"\Google\Chrome\User Data\Default\Cache", SAFE),
    (LOCAL + r"\Google\Chrome\User Data\Default\Login Data", KEEP),
    (LOCAL + r"\Google\Chrome\User Data\Profile 2\Code Cache\js", SAFE),
    (LOCAL + r"\NVIDIA\DXCache", SAFE),
    (LOCAL + r"\Microsoft\Windows\Explorer\thumbcache_256.db", SAFE),
    (LOCAL + r"\Microsoft\Windows\Explorer\iconcache_16.db", KEEP),
    (r"D:\Movies\film.mkv", CHOICE),
    (r"D:\Games", CHOICE),
])
def test_explain_safety(path, safety):
    info = knowledge.explain(path, is_dir=os.path.splitext(path)[1] == "")
    assert info.safety == safety, (path, info)
    assert info.what and info.advice and info.title


def test_temp_folders_stay():
    assert knowledge.explain(LOCAL + r"\Temp", True).keep_folder
    assert knowledge.explain(WIN + r"\Temp", True).admin


def test_zones():
    assert knowledge.zone(SYS) == "root"
    assert knowledge.zone(WIN + r"\System32") == "system"
    assert knowledge.zone(LOCAL + r"\x") == "appdata"
    assert knowledge.zone(HOME + r"\Desktop\a.txt") == "user"
    assert knowledge.zone(r"D:\stuff") == "other"


def test_unknown_program_names_itself():
    info = knowledge.explain(SYS + r"Program Files\Acme Paint\bin\paint.exe", False)
    assert info.title == "Acme Paint" and info.action == knowledge.APPS


# ---------------------------------------------------------------- the guard
def make_entry(path, kind="path", older=None):
    is_dir = os.path.isdir(path)
    e = junk.entry_for(path, 1, is_dir, older_than=older)
    e.kind = kind
    return e


@pytest.mark.parametrize("path", [SYS, WIN, WIN + r"\System32", HOME, HOME + r"\Documents",
                                  SYS + "Program Files"])
def test_refuses_important_places(path):
    if not os.path.exists(path):
        pytest.skip("not on this PC")
    assert deleter.refuse(make_entry(path))


def test_refuses_relative_and_missing(tmp_path):
    assert deleter.refuse(junk.Entry("relative\\x", "path", 1, knowledge.explain(r"D:\x", False)))
    assert deleter.refuse(make_entry(str(tmp_path / "nope.txt"))) == "Already gone."


# ---------------------------------------------------------------- scanning
def build(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "one.bin").write_bytes(b"x" * 1000)
    (tmp_path / "a" / "b" / "two.bin").write_bytes(b"y" * 3000)
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "big.bin").write_bytes(b"z" * 5000)
    return tmp_path


def test_scan_sizes(tmp_path):
    root = build(tmp_path)
    res = scanner.scan([str(root)], large_min=4000)
    top = res.roots[0]
    assert top.size == 9000 and top.files == 3
    a = top.child("a")
    assert a.size == 4000 and a.own == 1000
    assert res.find(str(root / "a" / "b")).size == 3000
    assert [os.path.basename(p) for _, p, _ in res.large] == ["big.bin"]
    res.forget(str(root / "a" / "b"), 3000)
    assert top.size == 6000 and a.size == 1000 and a.child("b") is None


def test_scan_skips_junctions(tmp_path):
    build(tmp_path)
    link = tmp_path / "loop"
    rc = os.system('mklink /J "%s" "%s" >nul 2>&1' % (link, tmp_path)) if os.name == "nt" else 1
    if rc != 0:
        pytest.skip("can't make a junction here")
    res = scanner.scan([str(tmp_path)])
    assert res.roots[0].size == 9000


def test_list_folder(tmp_path):
    root = build(tmp_path)
    files, rest = scanner.list_folder(str(root / "a"), limit=5)
    assert files[0][0] == "one.bin" and rest == (0, 0)


# ---------------------------------------------------------------- duplicates
def test_duplicates(tmp_path):
    data = os.urandom(300 * 1024)
    for name in ("x1.bin", "x2.bin", "x3.bin"):
        (tmp_path / name).write_bytes(data)
    (tmp_path / "other.bin").write_bytes(data[:-1] + b"\0")      # same size, different end
    old = time.time() - 1000
    os.utime(tmp_path / "x2.bin", (old, old))
    cands = {len(data): [str(tmp_path / n) for n in ("x1.bin", "x2.bin", "x3.bin", "other.bin")]}
    groups = duplicates.find(cands)
    assert len(groups) == 1
    g = groups[0]
    assert len(g.paths) == 3 and g.paths[0].endswith("x2.bin") and g.extra == 2 * len(data)


# ---------------------------------------------------------------- deleting (inside tmp_path only)
def test_delete_permanent_file_and_folder(tmp_path):
    root = build(tmp_path)
    entries = [make_entry(str(root / "c" / "big.bin")), make_entry(str(root / "a")),
               make_entry(str(root / "a" / "one.bin"))]       # nested in a: dropped, a takes it
    rep = deleter.delete(entries, permanent=True)
    assert not (root / "a").exists() and not (root / "c" / "big.bin").exists()
    assert rep.freed == 9000 and not rep.failed and rep.done == 2


def test_delete_contents_keeps_new_files(tmp_path):
    folder = tmp_path / "cache"
    (folder / "sub").mkdir(parents=True)
    old = time.time() - 3 * 86400
    for name in ("old.tmp", "sub/old2.tmp"):
        (folder / name).write_bytes(b"o" * 100)
        os.utime(folder / name, (old, old))
    os.utime(folder / "sub", (old, old))
    (folder / "new.tmp").write_bytes(b"n" * 100)
    e = make_entry(str(folder), kind="contents", older=time.time() - 86400)
    e.older_than = time.time() - 86400
    rep = deleter.delete([e], permanent=True)
    assert folder.exists() and (folder / "new.tmp").exists()
    assert not (folder / "old.tmp").exists() and not (folder / "sub").exists()
    assert rep.freed == 200


def test_delete_never_follows_junction(tmp_path):
    keep = tmp_path / "precious"
    keep.mkdir()
    (keep / "photo.jpg").write_bytes(b"p" * 10)
    victim = tmp_path / "victim"
    victim.mkdir()
    rc = os.system('mklink /J "%s" "%s" >nul 2>&1' % (victim / "link", keep)) if os.name == "nt" else 1
    if rc != 0:
        pytest.skip("can't make a junction here")
    deleter.delete([make_entry(str(victim))], permanent=True)
    assert (keep / "photo.jpg").exists() and not victim.exists()


def test_delete_readonly(tmp_path):
    f = tmp_path / "ro.txt"
    f.write_bytes(b"r")
    os.chmod(f, 0o444)
    rep = deleter.delete([make_entry(str(f))], permanent=True)
    assert not f.exists() and rep.files == 1


def test_recycle_bin(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows only")
    from tidy import winapi
    if not winapi.recycle_bin_works(str(tmp_path)):
        pytest.skip("temp folder is not on a fixed drive")
    f = tmp_path / "tidy-test-recycle.txt"
    f.write_bytes(b"hello")
    rep = deleter.delete([make_entry(str(f))], permanent=False)
    assert not f.exists() and rep.freed == 5 and not rep.failed


def test_vendor_folders_and_upgrade_leftovers():
    assert knowledge.explain(SYS + r"eSupport\eDriver\x.png", False).safety == CHOICE
    assert knowledge.explain(SYS + "$GetCurrent", True).safety == SAFE
    assert knowledge.explain(SYS + "$Windows.~BT", True).action == knowledge.TEMPFILES


def test_duplicates_only_in_own_files():
    assert scanner._dup_ok(HOME + r"\Music", "Music")
    assert not scanner._dup_ok(SYS + "eSupport", "eSupport")
    assert not scanner._dup_ok(HOME + r"\AppData", "AppData")
    assert scanner._dup_ok(r"D:\Movies", "Movies")


def test_appdata_names_the_app():
    info = knowledge.explain(LOCAL + r"\ClipStudio\models\model.bin", False)
    assert info.safety == KEEP and info.title == "ClipStudio"
    assert not scanner._dup_ok(HOME + r"\.cursor", ".cursor")
