@echo off
title Building Legacy ARK Launcher exe...
echo ============================================
echo  Legacy ARK Launcher - exe builder
echo ============================================
echo.
echo [1/3] Installing build tools (PyInstaller + PyQt6 + pypresence)...
echo        PyQt6 = the whole launcher UI (including QtMultimedia)
echo        pypresence = Discord Rich Presence (Settings ^> Discord)
echo        Everything else the launcher uses is Python stdlib
echo        (json, subprocess, urllib, zipfile, etc.) — no other
echo        third-party package is imported, so nothing else is needed.
echo        v1.60: pypresence was MISSING from this script in v1.59 —
echo        that is why an exe built from v1.59 could never show
echo        presence, even if the code was there. It is back now.
python -m pip install --upgrade pyinstaller pyqt6 pypresence
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. Make sure Python is installed and on PATH.
    pause
    exit /b 1
)
echo.
echo [2/3] Building exe (takes a few minutes, be patient)...
python -m PyInstaller --noconfirm --clean ^
  --name "LegacyARK-Launcher" ^
  --icon=logo.ico ^
  --noconsole --onefile ^
  --collect-all PyQt6 ^
  --collect-all pypresence ^
  --hidden-import pypresence ^
  --hidden-import tek_lib ^
  --hidden-import tek_steamclient ^
  --add-data "versions.json;." ^
  --add-data "descriptions.json;." ^
  --add-data "mods.json;." ^
  --add-data "logo.png;." ^
  --add-data "logo.ico;." ^
  --add-data "art;art" ^
  cml-launcher-gui.py
if errorlevel 1 (
    echo.
    echo ERROR: build failed. See output above.
    pause
    exit /b 1
)
echo.
echo [3/3] Done!
echo.
echo Your exe is at: dist\LegacyARK-Launcher.exe
echo Copy it anywhere you like - no Python needed.
echo.
pause
