@echo off
REM Makes dist\OMR-Reader.exe - a single file you can copy to any Windows PC (no Python needed there).
cd /d "%~dp0"
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --onefile --name OMR-Reader --add-data "omr\static;omr\static" --hidden-import waitress --collect-submodules pymupdf run.py
echo Done: dist\OMR-Reader.exe
pause
