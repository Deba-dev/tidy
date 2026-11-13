# Tidy

A storage cleaner for Windows PCs and laptops that **explains everything it shows**.

Other cleaners list folders and file sizes and leave beginners guessing what is safe. Tidy labels every item in
plain words with one of three colours:

| Colour | Meaning | Examples |
| --- | --- | --- |
| 🟢 **Safe to delete** | Junk Windows and apps make again by themselves. | Temp files, browser and app caches, shader caches, crash dumps, Windows Update leftovers, Recycle Bin |
| 🟠 **Your choice** | Your own files. Only you know if you still need them. | Videos, downloads, old installers, duplicate copies, games' leftover downloads |
| 🔴 **Keep** | Windows and installed programs. Tidy never lets you tick these. | `C:\Windows`, Program Files, AppData, page file, restore points |

Some red items come with a button to the right Windows tool instead (for example Apps settings to uninstall a
program, or Storage settings for the old Windows folder).

## What it does

1. **Scan**: pick drives; Tidy looks for known junk, maps every folder, finds large files and duplicate files
   (only among your own files, never program or Windows files).
2. **Look**: five pages — Overview, Junk, Space map, Large files, Duplicates — and an "About this item" panel that
   says what the selected thing is, whether it can go, and what happens after.
3. **Tick and review**: tick on any page; the bar at the bottom adds it up. *Review and delete* lists everything
   once more.
4. **Delete**: choose **Move to the Recycle Bin** (can be undone) or **Delete permanently** (frees space now).
   Amber items need an extra "they are mine" tick.

## Safety rules (in code, not only in the UI)

- `tidy/deleter.py` re-checks every item before deleting, whatever page it came from: no drive roots, nothing
  `knowledge.py` marks Keep, nothing of Tidy itself.
- Temp folders are emptied, never removed, and only files older than a day (setting) go.
- Junctions and symbolic links are never followed while scanning or deleting.
- Files in use are skipped and reported, never forced.
- Duplicates: at least one copy always stays (the UI and the review both enforce it).
- OneDrive "online-only" files are never read (that would download them).
- Every deletion is written to `%LOCALAPPDATA%\Tidy\logs\tidy.log` (rotating, 3 MB at most).

## Run from source

```
pip install -r requirements.txt
python main.py
```

Tests: `set QT_QPA_PLATFORM=offscreen` then `python -m pytest -q tests` (they only delete inside temporary test
folders).

Build: `build.bat` (PyInstaller) then Inno Setup with `installer.iss`. A `v*` tag builds and publishes
`Tidy-Setup.exe` through `.github/workflows/release.yml`.

## Where the knowledge lives

`tidy/knowledge.py` holds every explanation: known places (patterns like `{local}\Temp`), file types, and the
zone fallbacks for anything unknown. Add a new app's cache there and the Junk page, the Space map and the deleter
all pick it up. `tidy/junk.py` lists the places the Junk page looks in.
