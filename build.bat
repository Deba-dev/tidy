@echo off
REM Builds dist\Tidy\Tidy.exe for testing on this PC. Public releases are built by .github\workflows\release.yml.
cd /d "%~dp0"
if not exist .venv py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller==6.22.3
.venv\Scripts\python tools\make_icon.py
.venv\Scripts\python -m PyInstaller --noconfirm --windowed --noupx --name Tidy --icon assets\icon.ico --exclude-module tkinter main.py
