@echo off
REM Double-click this file. First run installs what is needed (needs internet once).
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.10+ from https://www.python.org/downloads/
  echo ^(tick "Add Python to PATH"^) and double-click this file again.
  pause
  exit /b 1
)
if not exist .venv (
  echo First time setup - please wait 2-3 minutes...
  py -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python run.py
pause
