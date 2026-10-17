@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python somya.py
pause
