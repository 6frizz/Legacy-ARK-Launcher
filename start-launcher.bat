@echo off
title CML Launcher
cd /d "%~dp0"

:: 1. Check if PyQt6 is already installed (brief console, closes below)
python -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo PyQt6 not found. Attempting to install...
    python -m pip install PyQt6 pypresence
    python -c "import PyQt6" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ==========================================
        echo ERROR: Could not install PyQt6 automatically.
        echo Please open your terminal and run:
        echo    python -m pip install PyQt6 pypresence
        echo ==========================================
        pause
        exit /b
    )
    echo Installation successful!
)

:: 1b. Discord presence needs pypresence (optional, launcher still runs without it)
python -c "import pypresence" >nul 2>&1
if errorlevel 1 (
    echo pypresence not found. Installing for Discord Rich Presence...
    python -m pip install pypresence >nul 2>&1
)

:: 2. Run the launcher with NO console window (pythonw, not python),
:: then close this terminal immediately. The launcher runs on its own.
:: If it ever crashes silently, run start-launcher-debug.bat instead
:: (that one keeps the terminal open) or check launcher-error.log
:: next to the .py, which the launcher writes on any error.
start "" pythonw cml-launcher-gui.py
exit /b 0
