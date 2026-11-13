"""UI smoke test: builds the window off-screen, scans a test folder, ticks things, deletes them and checks the pages."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                       # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402

from tidy import knowledge, scanner, duplicates      # noqa: E402
from tidy.settings import Settings                   # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from tidy.ui import theme
    theme.apply(a, "light")
    return a


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("TIDY_DATA", str(tmp_path / "data"))
    from tidy.ui.main_window import MainWindow
    w = MainWindow(Settings(str(tmp_path / "settings.json")))
    yield w
    w.modes.quitting = True
    w.close()


def make_state(root):
    from tidy.ui.workers import State
    from tidy import junk
    st = State()
    st.scan = scanner.scan([str(root)], large_min=1024 * 1024)
    st.dups = duplicates.find(st.scan.dup_candidates)
    cache = root / "cache"
    info = knowledge.Info("Test cache", "A test cache.", knowledge.SAFE, "Safe.", keep_folder=True)
    e = junk.Entry(str(cache), "contents", scanner.folder_size(str(cache))[0], info, 2)
    st.junk = [junk.Group("test", "Test junk", "Junk for the test.", knowledge.SAFE, [e])]
    return st


def build(tmp_path):
    root = tmp_path / "files"
    (root / "cache" / "sub").mkdir(parents=True)
    (root / "cache" / "a.tmp").write_bytes(b"a" * 5000)
    (root / "cache" / "sub" / "b.tmp").write_bytes(b"b" * 5000)
    data = os.urandom(2 * 1024 * 1024)
    (root / "photos").mkdir()
    (root / "photos" / "trip.mp4").write_bytes(data)
    (root / "backup").mkdir()
    (root / "backup" / "trip copy.mp4").write_bytes(data)
    old = time.time() - 10 * 86400
    os.utime(root / "photos" / "trip.mp4", (old, old))
    return root


def test_pages_load_and_delete(window, tmp_path, monkeypatch):
    root = build(tmp_path)
    if knowledge.zone(str(root)) not in ("user", "other", "appdata"):
        pytest.skip("temp folder is in a protected place")
    # the test files live in the user's Temp folder, which knowledge calls "safe"; make the duplicates "your choice"
    window.state = make_state(root)
    window.reload()
    assert window.junk.tree.topLevelItemCount() == 1
    assert window.space.tree.topLevelItemCount() == 1
    assert window.large.tree.topLevelItemCount() == 2            # two 2 MB files over the 1 MB line
    if knowledge.zone(str(root)) == "user":
        assert window.dupes.tree.topLevelItemCount() == 1
    for i in range(window.stack.count()):
        window.nav.setCurrentRow(i)
        QApplication.processEvents()

    # tick the junk group: its entry lands in the selection
    window.junk.tick_safe()
    QApplication.processEvents()
    assert len(window.selection.entries()) == 1
    top = window.junk.tree.topLevelItem(0)
    assert top.checkState(0) == Qt.CheckState.Checked

    # the same file ticked on two pages counts once
    big = str(root / "backup" / "trip copy.mp4")
    for item, e in window.large.tree.entries():
        if e.path == big:
            item.setCheckState(0, Qt.CheckState.Checked)
    QApplication.processEvents()
    assert len(window.selection.entries()) == 2

    # delete permanently without the dialog
    from tidy import deleter
    from tidy.ui.workers import apply_report
    rep = deleter.delete(window.selection.entries(), permanent=True)
    sizes = {e.key: scanner.folder_size(e.path)[0] for e, _ in rep.finished if e.kind == "contents"}
    gone = apply_report(window.state, rep, sizes)
    for k in gone:
        window.selection.remove(k)
    window.reload()
    assert not os.path.exists(big)
    assert (root / "cache").is_dir() and not os.listdir(root / "cache")
    assert window.junk.tree.topLevelItemCount() == 0
    assert window.dupes.tree.topLevelItemCount() == 0
    assert window.state.scan.roots[0].size == 2 * 1024 * 1024


def test_keep_rows_have_no_box(window):
    from tidy import junk
    win = os.environ.get("SystemRoot", r"C:\Windows")
    e = junk.entry_for(win, 10, True)
    item = window.space.tree.add_entry(None, e, ["Windows", "10", "", ""])
    assert not item.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert item.data(0, Qt.ItemDataRole.CheckStateRole) is None


def test_review_dialog(window, tmp_path):
    from tidy import junk
    from tidy.ui.dialogs import ReviewDialog
    f = tmp_path / "x.mp4"
    f.write_bytes(b"1")
    e = junk.entry_for(str(f), 1, False)
    e.info = knowledge.Info("Video", "A video.", knowledge.CHOICE, "Yours.")
    dlg = ReviewDialog(window, [e], window.s)
    assert not dlg.go.isEnabled()                 # amber items need the "they are mine" tick
    dlg.confirm_mine.setChecked(True)
    assert dlg.go.isEnabled()
    dlg.permanent.setChecked(True)
    assert dlg.go.text() == "Delete permanently"


def test_icon_file(tmp_path, app):
    from tidy.ui.icon import write_ico
    path = tmp_path / "icon.ico"
    write_ico(str(path))
    assert path.read_bytes()[:4] == b"\0\0\1\0"


def test_group_with_locked_row_keeps_its_box(window, tmp_path):
    from tidy import junk
    from tidy.ui.workers import State
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    info = knowledge.Info("Cache", "A cache.", knowledge.SAFE, "Safe.")
    free = junk.Entry(str(a), "path", 10, info)
    locked = junk.Entry(str(b), "path", 10, info, locked="Needs administrator")
    st = State()
    st.junk = [junk.Group("g", "Group", "A group.", knowledge.SAFE, [free, locked])]
    window.state = st
    window.reload()
    group = window.junk.tree.topLevelItem(0)
    assert group.checkState(0) == Qt.CheckState.Unchecked
    group.setCheckState(0, Qt.CheckState.Checked)
    QApplication.processEvents()
    assert [e.key for e in window.selection.entries()] == [free.key]
    assert group.checkState(0) == Qt.CheckState.Checked


def test_rows_inside_a_ticked_folder(window, tmp_path):
    from tidy import junk
    from tidy.ui.workers import State
    (tmp_path / "f" / "sub").mkdir(parents=True)
    (tmp_path / "f" / "sub" / "x.bin").write_bytes(b"x" * 10)
    st = State()
    st.scan = scanner.scan([str(tmp_path / "f")])
    window.state = st
    window.reload()
    tree = window.space.tree
    root = tree.topLevelItem(0)
    sub = root.child(0)
    sub.setExpanded(True)
    QApplication.processEvents()
    e = junk.entry_for(str(tmp_path / "f" / "sub"), 10, True)
    if not tree.can_tick(e):
        pytest.skip("temp folder is protected here")
    sub.setCheckState(0, Qt.CheckState.Checked)
    QApplication.processEvents()
    inner = sub.child(0)
    assert inner.checkState(0) == Qt.CheckState.Checked
    assert not inner.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert len(window.selection.entries()) == 1
