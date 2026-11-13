"""The few Windows calls Tidy needs, through ctypes (no extra packages)."""
import ctypes
import os
import shutil
import string
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM = 2, 3, 4, 5

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
ONLINE_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


@dataclass
class Drive:
    root: str           # "C:\\"
    label: str
    kind: str           # "Local disk", "USB drive", ...
    total: int
    free: int
    system: bool        # Windows lives here

    @property
    def used(self):
        return self.total - self.free

    @property
    def letter(self):
        return self.root[:2]


def drives():
    """Fixed and removable drives with their size. Network drives and empty card readers are left out."""
    out = []
    sysdrive = (os.environ.get("SystemDrive") or "C:").upper()
    if not IS_WINDOWS:
        u = shutil.disk_usage("/")
        return [Drive("/", "System", "Local disk", u.total, u.free, True)]
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = letter + ":\\"
        kind = k32.GetDriveTypeW(root)
        if kind not in (DRIVE_FIXED, DRIVE_REMOVABLE):
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue                                # no disk in a card reader
        name = ctypes.create_unicode_buffer(261)
        k32.GetVolumeInformationW(root, name, 261, None, None, None, None, 0)
        label = name.value or ("Windows" if letter + ":" == sysdrive else "Local Disk")
        out.append(Drive(root, label, "USB drive" if kind == DRIVE_REMOVABLE else "Local disk", usage.total,
                         usage.free, letter + ":" == sysdrive))
    return out


def is_admin():
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin(args=()):
    """Starts Tidy again with administrator rights (Windows asks the person). True if it started."""
    if not IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, list(args)
    else:
        exe, params = sys.executable, [os.path.abspath(sys.argv[0])] + list(args)
    line = subprocess.list2cmdline(params)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, line, None, 1)
    return rc > 32


# ---------------------------------------------------------------- Recycle Bin
class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


def recycle_bin_size():
    """(bytes, items) in the Recycle Bins of all drives."""
    if not IS_WINDOWS:
        return 0, 0
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
        return 0, 0
    return int(info.i64Size), int(info.i64NumItems)


def empty_recycle_bin():
    """Empties every Recycle Bin without Windows' own question, progress window or sound. True on success."""
    if not IS_WINDOWS:
        return False
    SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 1, 2, 4
    rc = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI |
                                                  SHERB_NOSOUND)
    return rc in (0, -2147418113)               # E_UNEXPECTED = the bin was already empty


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def to_recycle_bin(path):
    """Moves one file or folder to the Recycle Bin. Returns "" on success, else a short reason."""
    if not IS_WINDOWS:
        return "The Recycle Bin is only available on Windows."
    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    FOF_NOCONFIRMMKDIR = 0x200
    if not recycle_bin_works(path):
        return "This drive has no Recycle Bin."
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"            # ctypes adds the second NUL
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI | FOF_NOCONFIRMMKDIR
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if not os.path.lexists(path):
        return ""
    if rc in (5, 0x78):                                 # access denied
        return "Windows didn't allow it (needs administrator)."
    if rc == 32 or op.fAnyOperationsAborted:            # sharing violation
        return "In use by another program."
    return "In use or not allowed (code %d)." % rc


def recycle_bin_works(path):
    """USB sticks and memory cards have no Recycle Bin: deleting there is always permanent."""
    if not IS_WINDOWS:
        return False
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    return ctypes.windll.kernel32.GetDriveTypeW(root) == DRIVE_FIXED


# ---------------------------------------------------------------- opening things
def reveal(path):
    """Opens File Explorer with the item selected."""
    if IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def open_uri(uri):
    if IS_WINDOWS:
        os.startfile(uri)
