@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo The project virtual environment is missing.
    echo Run: python -m venv venv
    echo Then: venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
"venv\Scripts\python.exe" -X utf8 start_gui.py
if errorlevel 1 pause
