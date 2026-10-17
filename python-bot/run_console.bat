@echo off
title EVA Bot - Run (console mode, for debugging)
cd /d "%~dp0"
rem Console launcher - shows startup errors and keeps the window open on failure.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m entry.launcher
) else (
    python -m entry.launcher
)
if %errorlevel% neq 0 (
    echo.
    echo EVA Bot could not open the Dashboard. See data\logs\gui_console.log for details.
    pause
)
