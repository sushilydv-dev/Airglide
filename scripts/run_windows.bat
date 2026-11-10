@echo off
rem Start Airglide from source on Windows (run scripts\setup_windows.ps1 once first).
cd /d "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run setup first:  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
