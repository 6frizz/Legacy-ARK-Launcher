# Legacy ARK Launcher

A Windows launcher for playing **old ARK: Survival Evolved builds, 2015–2024** — The Island at launch through Scorched Earth, Ragnarok, Aberration, Extinction, Valguero, Genesis, Crystal Isles, and later maps.

Pick a build, download it, and play it. It also handles Workshop mods, hosting a server, backups, and a Dino Runner mini-game while you wait.

> **Unofficial fan tool. Not affiliated with, endorsed by, or connected to Studio Wildcard.**
> ARK: Survival Evolved, and all ARK artwork, names, and logos, are trademarks / copyrighted material of Studio Wildcard.
> This repository's MIT license covers the launcher code only — **not** ARK's game files, artwork, or name.

## What this is NOT

- **It does not include ARK.** No game files are in this repo, and no game files are distributed with the launcher.
- **It does not give you ARK for free.** You must own ARK: Survival Evolved on Steam. The launcher downloads old builds through **your own Steam account** using Valve's SteamCMD, and Steam will only serve builds you own.
- **It does not handle your Steam password.** You type your password / Steam Guard code yourself, in SteamCMD's own window, when Steam asks. The launcher never asks for, stores, types, or passes your password — it only passes `+login <your username>`.

## Requirements

- Windows 10/11
- Python 3.11+ and PyQt6 — **or** the built `.exe` (see below, no Python needed)
- A Steam account that owns ARK: Survival Evolved
- Tens of GB free disk space per build (old ARK builds are large)

## Run from source

1. Download / clone this repo.
2. Install PyQt6:
   ```
   python -m pip install PyQt6
   ```
3. Double-click `start-launcher.vbs` (no console window), or `start-launcher.bat` (checks PyQt6 first, brief console window).
   - If it ever crashes silently, run `start-launcher-debug.bat` instead — it keeps the console open — or check `launcher-error.log` next to the `.py`.

On first run:
- Settings → Steam → type your **Steam username only** (never your password there), then Settings → Steam → Set up SteamCMD.
- Pick a build on Versions, hit Download. If a SteamCMD window asks for your password / Guard code, type it in that window yourself.
- When it says **Installed**, hit Play.

## Build the .exe (Windows only)

On a Windows PC, in the repo folder, double-click `build-exe.bat`.
It installs PyInstaller + PyQt6, then builds a single-file exe:

```
dist\LegacyARK-Launcher.exe
```

Copy that exe anywhere — no Python needed to run it. SteamCMD and downloads live in a `steamcmd/` folder next to the exe, and your settings live in `~/.cml-launcher/settings.json` (your home folder, **not** in the repo).

Note: the exe is unsigned, so Windows SmartScreen will warn on first run. Click “More info” → “Run anyway”.

## How downloads work

- One SteamCMD window downloads every depot for the build, then quits (`+quit`).
- The launcher watches the download folder, then copies the depots into your install folder (default `CML-ARK` in your home folder), writes `steam_appid.txt` next to the game exe (Steam's own documented mechanism — the client still verifies you own ARK), and cleans up the raw depot files.
- Closing the launcher window while downloading does **not** break the install: it hides to the system tray and the download finishes normally. Reopen from the tray when it says finished.
- Quitting from tray → Quit, or hitting Cancel, stops the download but **keeps partial files**, so hitting Download again resumes instead of starting over.
- Do **not** close the SteamCMD window itself mid-download — that stops SteamCMD, and you will need to hit Download again to resume.

## Primitive+ (important)

Primitive+ is **not** a map and **not** a normal mod — it is a Total Conversion.

1. It did not exist before Jul 2016, so Jun 2015–Jun 2016 builds have no Primitive+ at all.
2. It is a separate **free** DLC in Steam (app 508150). If you never claimed it in Steam, SteamCMD cannot download it even though it is free — add it to your Steam library first, then Download again.
3. Even with it downloaded, Play still launches vanilla ARK — in ARK's main menu, before Host/Local, pick Total Conversion → Primitive Plus (the game restarts).

## Mods

`mods.json` is a catalog of 27 verified Steam Workshop mods, with build ranges. Ranges are best-effort: Workshop publishes no per-version list, and a download is the latest cooked version, which may fail on very old builds. Jun–Sep 2015 builds have 0 compatible mods in the catalog, Oct–Nov 2015 have 1 — that is honest, not a bug.

You can edit `mods.json` — the launcher reads it on startup, no recompile needed. `workshop_id` is a string.

## Artwork

`art/*.jpg` are ARK's real Steam store headers (460×215), fetched from Steam's CDN, and `art/ark-background.png` is the default background image. **These are Wildcard's artwork, not covered by the MIT license in this repo.** They are included here for identification in the launcher UI. If `art/` is ever lost, open Tools → “Download official ARK headers” to re-fetch them straight from Steam.

The top-bar JOIN DISCORD button opens the community Discord invite in your browser. It is just a text link button, no logo — it does not show Discord Rich Presence status in the launcher.

## Files in this repo

- `cml-launcher-gui.py` — the whole launcher (PyQt6)
- `versions.json` — 97 builds, 2015–2024, with Steam depot manifests
- `descriptions.json` — per-build descriptions
- `mods.json` — Workshop mod catalog
- `art/` — Steam header images + background
- `logo.png` / `logo.ico` — launcher icon
- `build-exe.bat` / `LegacyARK-Launcher.spec` — PyInstaller exe build
- `start-launcher.bat` / `start-launcher.vbs` / `start-launcher-debug.bat` — run from source

Not in this repo, on purpose: your settings (`~/.cml-launcher/settings.json`), SteamCMD, downloaded builds, backups, and logs. See `.gitignore`.

## License

MIT for the launcher code — see `LICENSE`. ARK game files, artwork, and trademarks are **not** MIT and are **not** yours to redistribute — this repo does not redistribute them as game files, and the header images are Wildcard's, included for UI identification only.
