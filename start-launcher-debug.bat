@echo off
title CML Launcher
cd /d "%~dp0"

:: 1. Check if PyQt6 is already installed
python -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo PyQt6 not found. Attempting to install...
    :: 2. Use 'python -m pip' to ensure it installs to the correct Python version
    python -m pip install PyQt6 pypresence
    
    :: 3. Check if the installation actually worked
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

:: 3b. Discord presence needs pypresence (optional, launcher still runs without it)
python -c "import pypresence" >nul 2>&1
if errorlevel 1 (
    echo pypresence not found. Installing for Discord Rich Presence...
    python -m pip install pypresence
)

:: 4. Run the launcher
echo Starting CML Launcher...
python cml-launcher-gui.py

:: 5. If the launcher crashes, keep the window open so you can see the error
if errorlevel 1 (
    echo.
    echo Launcher stopped with an error.
    pause
)