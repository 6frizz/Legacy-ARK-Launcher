#!/usr/bin/env python3
"""
Legacy ARK Launcher - dark flat hub UI (PyQt6).
Run:  pip install PyQt6  &&  python cml-launcher-gui.py
"""
import copy
import datetime
import html
import json
import math
import os
import random
import re
import shutil
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, QSize, QRect, pyqtSignal, QRectF, QPointF, QPoint, QObject, QEvent
from PyQt6.QtGui import (QColor, QDesktopServices, QFont,
                         QIcon, QPalette, QPen, QPainter, QPainterPath, QPixmap, QPolygon, QRegion)
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                             QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                             QGridLayout, QHBoxLayout, QLabel, QLayout, QWidgetItem, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMessageBox,
                             QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                             QSlider, QSplashScreen,
                             QStackedWidget, QVBoxLayout, QWidget, QProgressBar, QSizePolicy)

# v1.72.0: TEK Launcher engine-room port (sibling modules, imported
# guarded so a missing/corrupt module can never stop the launcher -
# the features that use them simply switch off).
try:
    import tek_lib
except Exception:
    tek_lib = None
try:
    import tek_steamclient
except Exception:
    tek_steamclient = None

# ------------------------------------------------------------------ config
APP_NAME = "Legacy ARK Launcher"
VERSION = "v1.72.0"
# v1.72.0: TEK Launcher (C#) engine room ported to Python - new
# tek_lib.py (VDF/KeyValues parser, Steam library detection via
# libraryfolders.vdf + appmanifest_*.acf, A2S_PLAYER, TEK's DLC table)
# and tek_steamclient.py (ctypes bindings for libtek-steamclient-2.dll,
# TEK's native Steam CM client; anonymous sign-in only, DLL downloaded
# on first use from TEK's mirrors, never bundled). Wired in: Servers
# cards show ping and a Players button lists who's online (A2S_PLAYER
# via tek_lib); Settings > Steam reports the Steam-library ARK
# detection; Mods 'Check (TEK CM)' verifies a Workshop ID through the
# CM client instead of the Web API. NOT ported: libtek-injector /
# libtek-game-runtime (process injection + Steamworks emulation) -
# game launching is exactly as before. See THIRD-PARTY-NOTICES.md.
# v1.71.2: usage-ping retry fix — v1.71.1 marked the day BEFORE sending,
# so a silently failed ping burned the whole day and the counter stayed
# empty with no error (his case: his PC reaches the counter fine, the
# ping code is correct, yet no hit ever landed). Now the day counts
# only on success, on a fresh key (old usage_ping_last_day marks are
# unproven — written before success-tracking — so his first v1.71.2
# launch retries right away instead of waiting for tomorrow), and a
# failed ping retries on the next launch or toggle flip. Folds in
# untested v1.71.1/71/70/69/68.
# v1.64.0: startup window diagnostic removed — no more launcher-windows.log
# created next to the exe on every launch (leftover from the v1.28.8/v1.28.9
# flashing-windows hunt; that bug was confirmed fixed in v1.28.13).
# launcher-error.log (crash-only) and the in-app log + Save log stay.
# v1.54.0: top-bar Discord button, wired at the user's order Nov 1, 2026.
# This invite supersedes the v1.46 placeholder (no link) for this button only.
# Community Servers tab, Sponsored servers, and the pirate Watch link are
# STILL removed (Oct 30 order) — this is only the top-bar Discord button.
DISCORD_INVITE_URL = "https://discord.gg/U8BRwhqpHA"

# ------------------------------------------------- Discord Rich Presence
# v1.60: RESTORED at user order Nov 1 01:03 (was removed Oct 30 v1.21.8
# with Servers/Sponsored/pirate link — presence is restored ONLY, those
# stay removed). Why it "didn't work" last time, figured out from the
# original code + current build script:
#  1) pypresence is OPTIONAL and import-guarded — without it the code
#     silently does nothing and never crashes, so presence just never
#     showed, with no error unless you used Settings > Test.
#  2) The CURRENT build-exe.bat (v1.59) did NOT install pypresence and
#     did NOT collect it for PyInstaller, even though the ORIGINAL
#     build-exe.bat did (pip install pypresence, --collect-all
#     pypresence, --hidden-import pypresence). So an exe built from
#     v1.59 could never show presence, even if the code was there.
#  3) Discord desktop app must be running, otherwise Presence.connect()
#     fails with DiscordNotFound — again silent in the old startup code.
# Fix in v1.60, all three:
#  - Presence code restored (below, same logic as original, import-guarded).
#  - build-exe.bat + start-launcher.bat now install pypresence.
#  - Settings > Discord section restored with a Test button that shows
#    the EXACT failure reason (not installed / Discord not running /
#    Client ID wrong / connection closed), so it can never silently fail
#    again. Startup idle presence is also no longer silent: if it fails
#    and presence is ON, the main window status bar shows the reason.
# Client ID: old app ID from the original file (1561553907270951002,
# app named "Legacy ARK Launcher"). A Client ID is NOT a secret token —
# it is a public application ID. If that Discord app was deleted, Test
# will say "Client ID looks wrong" — then create a new app at
# discord.com/developers/applications named "Legacy ARK Launcher" and
# paste its new Application ID into Settings > Discord Client ID.
_DISCORD_RPC = None

def _discord_lib():
    try:
        from pypresence import Presence
        return Presence
    except Exception:
        return None

def discord_available():
    return _discord_lib() is not None

def _discord_connect_reason(e):
    name = type(e).__name__
    msg = str(e) or ""
    if "DiscordNotFound" in name or "not running" in msg.lower():
        return "Discord desktop app isn't running — open Discord first, then try again."
    if "InvalidID" in name or "invalid" in name.lower():
        return "That Client ID looks wrong — check it at discord.com/developers/applications."
    if "PipeClosed" in name:
        return "Discord closed the connection — restart Discord and try again."
    return f"{name}: {msg}" if msg else name

def discord_set_playing(client_id, build_name):
    global _DISCORD_RPC
    client_id = (client_id or "").strip()
    build_name = (build_name or "").strip()
    if not client_id or not build_name:
        return False, "Missing Client ID."
    Presence = _discord_lib()
    if Presence is None:
        return False, "pypresence isn't installed."
    try:
        discord_clear()
        rpc = Presence(client_id)
        rpc.connect()
        rpc.update(details="Legacy ARK Launcher", state=f"Playing ARK {build_name}", start=int(time.time()), large_image="logo", large_text="Legacy ARK Launcher")  # v1.63: "logo" art asset must be uploaded in Discord Developer Portal > Rich Presence > Art Assets, named exactly "logo" (use logo.png, or the user's custom logo file when he sends it) — without that upload Discord shows "?" as in his Nov 1 01:28 screenshot.
        _DISCORD_RPC = rpc
        return True, ""
    except Exception as e:
        _DISCORD_RPC = None
        return False, _discord_connect_reason(e)

def discord_set_idle(client_id):
    global _DISCORD_RPC
    client_id = (client_id or "").strip()
    if not client_id:
        return False, "Missing Client ID."
    Presence = _discord_lib()
    if Presence is None:
        return False, "pypresence isn't installed."
    try:
        discord_clear()
        rpc = Presence(client_id)
        rpc.connect()
        rpc.update(details="Legacy ARK Launcher", state="Browsing builds", start=int(time.time()), large_image="logo", large_text="Legacy ARK Launcher")  # v1.63: same "logo" asset as playing.
        _DISCORD_RPC = rpc
        return True, ""
    except Exception as e:
        _DISCORD_RPC = None
        return False, _discord_connect_reason(e)

def discord_clear():
    global _DISCORD_RPC
    try:
        if _DISCORD_RPC is not None:
            try: _DISCORD_RPC.clear()
            except Exception: pass
            try: _DISCORD_RPC.close()
            except Exception: pass
    except Exception:
        pass
    _DISCORD_RPC = None

# ------------------------------------------------------------------ FlowLayout
# v1.45.0 FULL responsive fix: a wrapping layout, like text wrapping in a
# paragraph. Items go left-to-right, and when the next item would run
# past the right edge, it drops to the next line instead of clipping.
# This is the mechanism that makes "nothing goes off window" true at
# ANY window size: button rows, filter rows, tile rows and control rows
# get taller (vertical scroll handles that) instead of wider (which
# nothing handles, and which is what was cutting info off on the right).
# Hidden widgets and spacer items are skipped, so filtering (Tools,
# Mods) and stretch() calls do not leave blank gaps. Items are capped
# to the layout width, so even a single very long button cannot push
# past the edge. A FlowLayout is NOT a copy of anyone else's code —
# it is the standard Qt wrapping-layout pattern, written fresh here.
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList = []
    def __del__(self):
        try:
            item = self.takeAt(0)
            while item:
                item = self.takeAt(0)
        except Exception:
            pass
    def addItem(self, item):
        self.itemList.append(item)
    # v1.45.0/1.45.1: QLayout.addWidget takes ONLY a widget (no stretch arg),
    # and QLayout has no addLayout/addStretch/addSpacing at all — those are
    # QBoxLayout methods, and almost every converted row calls them
    # (addWidget(b, 1), addLayout(col, 1), addStretch(1)). These shims accept
    # those args and ignore stretch/alignment on purpose: a wrapping layout
    # does not stretch or right-align, it just wraps to the next line.
    # addWidget MUST go through super(), not QWidgetItem() in Python (see below).
    def addWidget(self, widget, stretch=0, alignment=None):
        # CRITICAL v1.45.1: do NOT create QWidgetItem(widget) here in Python.
        # That segfaults the whole app the moment this layout is installed
        # into a parent layout (verified offscreen: exit 139 at v.addLayout).
        # super().addWidget() creates the item in C++ with correct parenting
        # and ownership. Stretch/alignment are still ignored on purpose.
        super().addWidget(widget)
    def addLayout(self, layout, stretch=0):
        # v1.47.0: a sub-layout added to a FlowLayout MUST be parented to it,
        # or its widgets stay parentless and never show — that is why Settings
        # titles/subtitles, page headers, hero titles and card titles were
        # invisible in v1.45/46 even at full screen, while buttons (added via
        # super().addWidget, which parents them in C++) showed fine.
        # Parent the layout here, and reparent its widgets to this layout's
        # parent widget now if known, and again in doLayout when it is known.
        try: layout.setParent(self)
        except Exception: pass
        self.addItem(layout)
        try:
            _pw = self.parentWidget()
            if _pw is not None:
                self._reparent_layout_widgets(layout, _pw)
        except Exception: pass
    def _reparent_layout_widgets(self, layout, widget):
        try:
            for _i in range(layout.count()):
                _it = layout.itemAt(_i)
                if _it is None: continue
                _w = _it.widget()
                if _w is not None:
                    try: _w.setParent(widget)
                    except Exception: pass
                elif _it.layout() is not None:
                    self._reparent_layout_widgets(_it.layout(), widget)
        except Exception: pass
    def addStretch(self, stretch=0):
        pass
    def addSpacing(self, size):
        pass
    def count(self):
        return len(self.itemList)
    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None
    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None
    def expandingDirections(self):
        return Qt.Orientation.Horizontal
    def hasHeightForWidth(self):
        return True
    def heightForWidth(self, width):
        return self.doLayout(QRect(0, 0, width, 0), True)
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)
    def sizeHint(self):
        return self.minimumSize()
    def minimumSize(self):
        # Standard wrapping-layout minimum: widest/tallest single item,
        # not 0. Returning 0 here risked a parent layout collapsing the
        # whole row to 0 height when heightForWidth was not consulted.
        # The layout still shrinks to any width because doLayout wraps.
        size = QSize(0, 0)
        for item in self.itemList:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            try:
                size = size.expandedTo(item.minimumSize())
            except Exception:
                pass
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size
    def doLayout(self, rect, testOnly):
        x = rect.x(); y = rect.y(); lineHeight = 0; spacing = self.spacing()
        if spacing < 0:
            spacing = 6  # -1 means "style default" in Qt; use 6px, not -1px overlap
        m = self.contentsMargins()
        avail = max(0, rect.width() - m.left() - m.right())
        # v1.47.0: sub-layout widgets must be children of this layout's
        # parent widget to be visible at all. Reparent them here, at layout
        # time, when parentWidget() is finally known (it is None at add time
        # for layouts not yet installed on a widget).
        try:
            _pw = self.parentWidget()
            if _pw is not None:
                for _it2 in self.itemList:
                    if _it2 is not None and _it2.layout() is not None:
                        self._reparent_layout_widgets(_it2.layout(), _pw)
        except Exception: pass
        for item in self.itemList:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            if w is None and item.layout() is None:
                continue
            try:
                sz = item.sizeHint()
            except Exception:
                continue
            iw = min(sz.width(), avail) if avail > 0 else sz.width()
            ih = sz.height()
            if x > rect.x() and (x - rect.x() + iw + spacing) > avail and lineHeight > 0:
                x = rect.x(); y += lineHeight + spacing; lineHeight = 0
            if not testOnly:
                try:
                    item.setGeometry(QRect(QPoint(x, y), QSize(iw, ih)))
                except Exception:
                    pass
            x += iw + spacing
            lineHeight = max(lineHeight, ih)
        return y + lineHeight - rect.y()


# v1.21.8 cleanup: removed the community Servers tab + sponsored slots,
# all Discord integration and links, the Dino Runner mini-game, the
# pirate Watch link, and the broken What's-new dialog (its dialog class
# was missing). Core stays: Dashboard, Versions, Mods, Host, Backups,
# Help, Settings.
# v1.21.9: Dino Runner restored at the user's request — it was removed
# in v1.21.8, but he wants the mini-game + Play button during downloads.
# v1.22.0: Dino Runner rebuilt Chrome-style (Chromium T-Rex Runner rules:
# jump/duck, cacti, pterodactyls, night mode, HI score) — native Qt, no
# WebEngine, no copied Chromium code.
# v1.29.0: 100 MORE features (101-200, see IMPROVEMENTS-100-MORE.md)
# on top of the first 100 in v1.24.0. New Tools checks, Versions
# filters/buttons, Mods/Backups/Host buttons, Settings toggles,
# shortcuts, Dino stats and helpers. No Discord/Servers/sponsored/
# pirate content re-added, Host/Dino/headers/granite theme kept,
# v1.28.13 card parenting kept.
# v1.29.1 layout fix: removed the squeezed filt3 row (16 extra-action
# buttons clipped to single letters), split the Versions filter row
# into two readable rows with full combo/checkbox/button labels,
# split the details 7-button row into two rows, stripped the 101-130
# numbers from Tools button titles (category now "More checks"),
# and added nav tooltips (page name + Ctrl+number) for navigation.
# v1.28.13: version/DLC cards are parented immediately (ClickableCard
# (self) / QFrame(self)) — parentless cards were top-level windows
# until _reflow_grid added them, and fast2 caught 20 of them as
# 216x244 'Legacy ARK Launcher' windows flashing ~30ms each before
# the main window appeared.
# v1.28.10: FOUND the pre-load window — apply_always_on_top() called
# self.show() unconditionally, and __init__ calls it when
# always_on_top is on, so the main window appeared at 0,0 unpainted
# during the build, before centering and before main()'s show().
# Now it only re-shows if already visible; at startup it just sets
# the flag and main() shows the window once, centered and built.
# v1.28.9: pre-load window diagnostic — the v1.28.8 log ran AFTER
# win.show(), so it missed windows that appear and vanish WHILE
# the app is still loading. Now _dump_windows() logs at
# before-MainWindow, init-pages-built, init-refresh-done, and
# after-MainWindow-before-show, so a transient pre-load window
# will be caught at the checkpoint where it is still visible.
# v1.28.8: startup window diagnostic — main() now logs every
# top-level Qt window to launcher-windows.log (startup + 3s later),
# to settle whether the mystery launch rectangle is a launcher
# window at all. Assets are QPixmaps, not windows.
# v1.28.7: start-launcher.vbs added — a truly zero-console launch
# (pythonw via WScript, no .bat console flash at all). The .bat in
# v1.28.6 still flashed its own console briefly for the PyQt check,
# which is why the terminal window was still a thing.
# v1.28.6: no console window anymore — start-launcher.bat now runs
# pythonw (not python) and exits, so the "Starting CML Launcher..."
# terminal does not stay open behind the launcher. The old console
# version is kept as start-launcher-debug.bat, and the excepthook
# now also writes to launcher-error.log next to the .py, so a silent
# crash is still diagnosable. The exe build was already --noconsole.
# v1.28.5: collapsed nav icons are centered (the real alignment bug:
# #Nav's 16px left padding put icon centers at ~24px vs the logo's
# 32px). Reverted the v1.28.4 opacity trick — it made the launch
# flash longer — and dropped WA_TranslucentBackground entirely, so
# the window is opaque/solid from frame one (square corners now).
# Centering before show() is kept.
# v1.28.4: sidebar arrow is ONLY at the bottom (centered, under the
# nav icons) — no arrow at the top anymore, so the logo sits alone
# and centered. Also kills the transparent top-left flash on launch:
# the window is hidden (opacity 0) until its first paint, then
# revealed fully painted, and it is centered before show() instead
# of starting at (0,0).
# v1.28.3: collapsed sidebar gets its own vertical brand row (logo
# centered above the expand button) so the "A" lines up with the
# centered nav icons below it; the old horizontal collapsed row
# left-aligned the logo at ~13px while the icons sat at 32px. Two
# separate brand rows are visibility-toggled instead of rebuilding
# a live Qt layout. Also removed the QSplashScreen — it was the small
# flashing "LEGACY ARK" window on launch, not header art.
# v1.28.2: mods ranges corrected — 11 min_build labels were proven
# wrong by Steam's Workshop API creation dates (a mod cannot predate
# its own Workshop page); see MODS-COMPAT.md for the full table.
# Honest consequence: Jun-Sep 2015 builds now show 0 compatible mods
# and Oct-Nov 2015 show 1, because Workshop modding did not exist at
# the Jun 2015 launch. Maxes are still best-effort.
# v1.28.1: main theme is now Granite Grey — the v1.28.0 white theme
# was way too bright, so the default is a mid-dark granite grey with
# the same orange accent. ARK Light (white) and Ember (dark) stay in
# Settings → Theme.
# v1.28.0: main theme is now ARK Light — white/silver background with
# the logo's orange accent (new "arklight" theme, first in Settings →
# Theme, and the default for any install without a saved theme pick;
# Ember and the other dark themes are still there to switch back to).
# Palette, splash and default icon colors now follow the live theme
# instead of hard-coded dark values, so dialogs and titlebar icons
# stay readable on white.
# v1.27.2: art/*.jpg are now ARK's real store headers (460x215, from
# Steam's CDN), bundled in the zip at the user's request — the
# v1.27.1 zip still shipped the generated banners, which is why his
# cards showed "THE ISLAND / LEGACY ARK" gradients instead of ARK's
# art. Tools > Download official ARK headers now just re-fetches
# these same files if art/ is ever lost or overwritten.
# v1.27.1: hotfix — v1.27.0 crashed on launch (NameError: QSizePolicy
# was used by FullBleedBanner but never imported; it lives in QtWidgets).
# v1.27.0: version cards are full-bleed (banner fills the whole card
# width, edge to edge, no inset frame; taller 120px banner), Tools gains
# "Download official ARK headers" (fetches ARK's own 460x215 headers
# straight from Steam's CDN into art/ — one per map/DLC, picked per
# build by era_art_key), and a failed download now offers "Retry
# without Primitive+" so a Prim+ depot failure no longer kills the
# whole build. No Discord/Servers/sponsored content re-added.
# v1.26.0: real art banners (art/*.jpg, 13 generated banners — the old
# zip only had a README, so cards could only show the tiny drawn icon),
# Tools redesigned (grouped checks, result next to each button, Run-all
# summary at the top), and Primitive+ explained + hinted in-app.
# v1.25.0: compat mods for every version — mods.json grew from 3 to 27
# mods (Workshop IDs verified against Workshop listings), Versions details
# now lists compatible mods for the selected build, Mods tab gains a
# "Compatible with selected build only" filter + per-card ✓/✗ badge.
# Ranges are best-effort (see mods.json note): Workshop has no official
# per-version list, and a Workshop download is the latest cooked version.
# v1.24.0: 100 improvements pack — Tools page (30 diagnostics/actions),
# Versions filters/sort/copy/random, Mods search/sort/Copy ID, Backups
# search/summary, Settings toggles + export/import, shortcuts, and 12
# Dino upgrades (pause, slow mode, speed/jumps/dodged stats, NEW BEST).
# Full numbered list in IMPROVEMENTS-100.md. No Discord/Servers/sponsored
# content was re-added.
# v1.23.0: Dino Runner now uses Chromium's REAL sprite sheet
# (100-offline-sprite.png, embedded base64) — same trex, duck, ptero,
# cacti, cloud, horizon, moon, stars and GAME OVER art as chrome://dino.
DATA_DIR = Path.home() / ".cml-launcher"
SETTINGS_FILE = DATA_DIR / "settings.json"

def _app_dir():
    """Writable folder next to the app: beside the .exe when frozen with
    PyInstaller, beside the .py when running from source. SteamCMD and
    other runtime downloads live here so they survive restarts."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def _dump_windows(tag):
    """RETIRED in v1.64.0: the v1.28.8/v1.28.9 flashing-windows diagnostic.
    It wrote launcher-windows.log next to the exe on every launch; the
    flashing bug was confirmed fixed in v1.28.13, so the diagnostic is
    gone and no log file is created anymore. Kept as a no-op so the
    old call sites stay harmless."""
    return


def _resource(name):
    """Bundled read-only file (versions.json, art/, icons...): inside the
    PyInstaller bundle when frozen, beside the .py when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / name
    return Path(__file__).resolve().parent / name


def _open_url(url):
    """Open a URL in the browser. Never raises — tries the Windows-native
    opener, then Qt's, then Python's webbrowser. If every automatic way
    fails, shows the link in a copyable dialog so it never silently
    does nothing."""
    url = str(url or "").strip()
    if not url:
        return False
    if "://" not in url:
        url = "https://" + url
    try:
        if sys.platform == "win32":
            os.startfile(url)
            return True
    except Exception:
        pass
    try:
        if QDesktopServices.openUrl(QUrl(url)):
            return True
    except Exception:
        pass
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception:
        pass
    try:
        parent = QApplication.activeWindow()
        dlg = QDialog(parent)
        dlg.setWindowTitle("Open link")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        lab = QLabel("Couldn't open the browser automatically — copy the link below:")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        le = QLineEdit(url)
        le.setReadOnly(True)
        le.selectAll()
        lay.addWidget(le)
        row = FlowLayout()
        row.addStretch(1)
        cp = QPushButton("Copy link")
        cp.clicked.connect(lambda: _copy_text(url))
        row.addWidget(cp)
        ok = QPushButton("Close")
        ok.clicked.connect(dlg.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        dlg.exec()
        return True
    except Exception:
        return False

def _copy_text(text):
    """Copy text to the clipboard. Never raises."""
    try:
        QApplication.clipboard().setText(str(text or ""))
        return True
    except Exception:
        return False
# ------------------------------------------------------------------ mod catalog
MODS_FILE = _resource("mods.json")

def load_mods():
    """Read the mod catalog (mods.json next to the app). Returns a list of
    dicts: name, workshop_id, description, min_build, max_build. The file
    is user-editable — a bad file just yields an empty list, never a crash."""
    try:
        data = json.loads(MODS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    mods = data.get("mods", []) if isinstance(data, dict) else []
    out = []
    for m in mods:
        if isinstance(m, dict) and m.get("workshop_id"):
            out.append({
                "name": str(m.get("name", "Unnamed mod")),
                "workshop_id": str(m.get("workshop_id")),
                "description": str(m.get("description", "")),
                "min_build": str(m.get("min_build", "")),
                "max_build": str(m.get("max_build", "")),
            })
    return out

def mod_compatible(mod, version_name):
    """True if version_name falls inside the mod's min_build..max_build
    range, compared by (year, month) from the build names, NOT by
    versions.json order (that file is not chronological). Empty min/max
    means unbounded on that side. Unparseable version names match nothing."""
    v = parse_version_date(version_name)
    if v == (9999, 12):
        return False
    lo = parse_version_date(mod.get("min_build", "")) if mod.get("min_build") else (0, 0)
    hi = parse_version_date(mod.get("max_build", "")) if mod.get("max_build") else (9999, 12)
    return lo <= v <= hi

def mods_for_version(version_name, mods):
    """Every mod in the catalog whose range covers version_name."""
    return [m for m in mods if mod_compatible(m, version_name)]

# ------------------------------------------------------------------ backups
BACKUP_DIR = DATA_DIR / "backups"

def _saved_dir_for(store, version):
    """The ShooterGame/Saved folder for an installed build (may not exist)."""
    steam = steam_dir_for(store)
    if not steam:
        return None
    return game_dir_for(store, version, steam) / "ShooterGame" / "Saved"


def _multimedia_available():
    """True if QtMultimedia (QMediaPlayer) imports. Guarded — the app
    must never crash when the multimedia backend is missing."""
    try:
        from PyQt6.QtMultimedia import QMediaPlayer  # noqa: F401
        from PyQt6.QtMultimediaWidgets import QVideoWidget  # noqa: F401
        return True
    except Exception:
        return False

# ------------------------------------------------- first-run steam detect
def _first_run_steam_detect():
    """Hunt for Steam on first launch. winreg read of the Valve keys,
    then %ProgramFiles% variants and hardcoded fallbacks. Returns a
    folder path or "". No-op off Windows. Never raises."""
    if os.name != "nt":
        return ""
    try:
        import winreg
        for hive, sub, val in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        ]:
            try:
                with winreg.OpenKey(hive, sub) as k:
                    cand = str(winreg.QueryValueEx(k, val)[0]).replace("/", "\\")
                if cand and os.path.isfile(os.path.join(cand, "steam.exe")):
                    return cand
            except OSError:
                continue
    except ImportError:
        pass
    except Exception:
        pass
    cands = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        base = os.environ.get(env, "")
        if base:
            cands.append(os.path.join(base, "Steam"))
    cands += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    for cand in cands:
        try:
            if cand and os.path.isfile(os.path.join(cand, "steam.exe")):
                return cand
        except OSError:
            continue
    return ""

# ------------------------------------------------------------------ themes
# Each theme recolors the whole launcher. apply_theme() swaps the module
# globals + rebuilds QSS; Python-side QColor(BG) etc. pick up the new
# values live because they're read at paint time, not import time.
THEMES = {
    # v1.62.0: ONLY Ember + Custom are available, at user order
    # Nov 1 01:19 ("make only ember and customs themes aviable
    # get rid of rest"). Removed themes, deleted from this dict
    # (not just hidden from the dropdown, so no code path can
    # select them again): Config Editor, ARK Gems, Studio, Granite
    # Grey, ARK Light, Ocean, Forest, Crimson, Violet, Arctic,
    # Toxic, Sunset. Custom is NOT in this dict — it is built
    # from Ember in _theme_dict() with the user-picked accent
    # (Settings > Pick color...), so Custom always works even
    # though it has no fixed entry here.
    "ember": {"name": "Ember", "BG": "#0E0E10", "SIDEBAR": "#121214",
              "CARD": "#1A1B1E", "CARD_HOVER": "#232326", "INPUT_BG": "#16171A",
              "BORDER": "#2A2A2E", "HAIR": "#3A2E1A", "TEXT": "#F2EFE9",
              "MUTED": "#9A958C", "ACCENT": "#FF8800", "ACCENT_HOVER": "#FFA033",
              "ACCENT_DARK": "#E67A00", "GOLD": "#F0A02E", "ON_ACCENT": "#1A1206", "GLASS": "#26FFFFFF", "GLASS_HOVER": "#40FFFFFF", "GLASS_BORDER": "#59FFFFFF"},
}

# Live color globals — apply_theme() reassigns these; paint code reads
# them at paint time so themes switch without a restart.
BG = THEMES["ember"]["BG"]; CARD = THEMES["ember"]["CARD"]
CARD_HOVER = THEMES["ember"]["CARD_HOVER"]; INPUT_BG = THEMES["ember"]["INPUT_BG"]
ACCENT_DARK = THEMES["ember"]["ACCENT_DARK"]
BORDER = THEMES["ember"]["BORDER"]; HAIR = THEMES["ember"]["HAIR"]
TEXT = THEMES["ember"]["TEXT"]; MUTED = THEMES["ember"]["MUTED"]
FAINT = "#6B675F"; GOLD = THEMES["ember"]["GOLD"]
ACCENT = THEMES["ember"]["ACCENT"]; ACCENT_HOVER = THEMES["ember"]["ACCENT_HOVER"]
BTN_TEXT = "#1A1206"; TEAL = "#2EC4B6"; SUCCESS = "#4cbf5a"
WARNING = "#e0b050"; DANGER = "#E5484D"; SIDEBAR = THEMES["ember"]["SIDEBAR"]
QSS = ""

def _on_accent_text(hexcol):
    """Readable text color on top of an accent fill: dark text on light
    accents, white on dark ones. Used for Primary buttons and anywhere
    text sits directly on the accent color."""
    try:
        c = QColor(str(hexcol))
        lum = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0
    except Exception:
        lum = 0.0
    return "#1A1206" if lum > 0.45 else "#FFFFFF"

def _theme_dict(name, store=None):
    if name == "custom" and store is not None:
        base = dict(THEMES["ember"])
        custom_accent = (store.get("custom_accent", "") or "").strip()
        if custom_accent:
            base["ACCENT"] = custom_accent
            base["GOLD"] = custom_accent
            base["ON_ACCENT"] = _on_accent_text(custom_accent)
            base["name"] = "Custom"
        return base
    return THEMES.get(name, THEMES["ember"])

def build_qss(t):
    q = _QSS
    for key in ("BG", "SIDEBAR", "CARD", "CARD_HOVER", "INPUT_BG", "BORDER",
                "HAIR", "TEXT", "MUTED", "ACCENT", "ACCENT_HOVER",
                "ACCENT_DARK", "GOLD", "ON_ACCENT", "GLASS", "GLASS_HOVER",
                "GLASS_BORDER"):
        q = q.replace("@" + key + "@", t[key])
    return q

def apply_theme(name, store=None):
    """Switch the whole launcher's colors live. Safe to call any time —
    QSS rebuilds and Python-side colors are read at paint time."""
    global BG, CARD, CARD_HOVER, INPUT_BG, ACCENT_DARK, BORDER, HAIR, TEXT, MUTED, GOLD, ACCENT, ACCENT_HOVER, SIDEBAR, QSS, ON_ACCENT, GLASS, GLASS_HOVER, GLASS_BORDER
    t = _theme_dict(name, store)
    BG = t["BG"]; CARD = t["CARD"]; CARD_HOVER = t["CARD_HOVER"]; INPUT_BG = t["INPUT_BG"]
    ACCENT_DARK = t["ACCENT_DARK"]; BORDER = t["BORDER"]; HAIR = t["HAIR"]
    TEXT = t["TEXT"]; MUTED = t["MUTED"]; GOLD = t["GOLD"]
    ACCENT = t["ACCENT"]; ACCENT_HOVER = t["ACCENT_HOVER"]; SIDEBAR = t["SIDEBAR"]
    ON_ACCENT = t["ON_ACCENT"]
    GLASS = t.get("GLASS", "#26FFFFFF"); GLASS_HOVER = t.get("GLASS_HOVER", "#40FFFFFF"); GLASS_BORDER = t.get("GLASS_BORDER", "#59FFFFFF")
    QSS = build_qss(t)

_QSS = """
/* ============ base ============ */
QWidget { color: @TEXT@; font-size: 14px; background: transparent; }
QWidget:focus { outline: none; }

/* ============ labels / typography ============ */
QLabel#Muted { color: @MUTED@; }
QLabel#StatusText { background: @BG@; color: @TEXT@; font-weight: 700; padding: 6px 8px; border-radius: 6px; } /* v1.52: download status pill — solid, bright, readable over photo */
QLabel#Empty { color: #6B675F; }
QLabel#Brand { font-size: 22px; font-weight: 900; color: @TEXT@; }
QLabel#PageTitle { font-size: 24px; font-weight: 700; color: @TEXT@; }
QLabel#PageSub { font-size: 14px; color: @MUTED@; }
QLabel#HeroTitle { font-size: 24px; font-weight: 700; color: @TEXT@; }
QLabel#HeroStat { font-size: 22px; font-weight: 800; color: @ACCENT@; }
QLabel#CardTitle { font-size: 16px; font-weight: 700; }
QLabel#CardHead { font-size: 24px; font-weight: 700; }
QLabel#RowTitle { font-size: 14px; font-weight: 700; }
QLabel#SectionHeader { font-size: 10px; font-weight: 600; color: @MUTED@; }
QLabel#Count { color: @TEXT@; font-weight: 600; }
QLabel#Ver { color: #6B675F; font-size: 11px; }
QLabel#VersionPill { background: @CARD@; border: 1px solid @BORDER@; border-radius: 12px; padding: 4px 12px; color: @TEXT@; font-size: 11px; }

/* ============ cards & structure ============ */
QFrame#Card { background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,15); border-radius: 0px; }
QFrame#Card:hover { background: rgba(255,255,255,10); border: none; border-bottom: 1px solid rgba(255,255,255,15); }
QFrame#Hero { background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,15); border-radius: 0px; }
QFrame#Hero:hover { background: rgba(255,255,255,10); border: none; border-bottom: 1px solid rgba(255,255,255,15); }
QFrame#Hair { background: rgba(255,255,255,15); min-height: 1px; max-height: 1px; border: none; }
QFrame#Sidebar { background: transparent; border-right: 1px solid @BORDER@; }
QFrame#StatusBar { background: transparent; border-top: 1px solid @BORDER@; }
QFrame#DetailsCard { background: @GLASS@; border: 1px solid @GLASS_BORDER@; border-radius: 12px; }
QFrame#DetailsPanel { background: transparent; border-left: 1px solid rgba(255,255,255,15); }

/* ============ buttons ============ */
/* v1.51.0 glass: buttons are translucent washes, not solid black boxes —
   the background photo shows through faintly, with a light glass edge.
   Primary buttons keep their gradient (see below), Nav/Ghost keep theirs. */
QPushButton {
    background: @GLASS@; border: 1px solid @GLASS_BORDER@; border-radius: 8px;
    padding: 10px 20px; color: @TEXT@; font-weight: 600;
}
QPushButton:hover { background: @GLASS_HOVER@; border-color: @ACCENT@; }
QPushButton:pressed { background: @GLASS@; border-color: @ACCENT@; }
QPushButton:disabled { background: @GLASS@; border-color: @GLASS_BORDER@; color: #6B675F; }
QPushButton:focus { outline: none; }
QPushButton#Primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @ACCENT_DARK@, stop:0.5 @ACCENT@, stop:1 @ACCENT_HOVER@); border: none; border-radius: 8px;
    padding: 10px 22px; color: @ON_ACCENT@; font-weight: 700;
}
QPushButton#Primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @ACCENT_HOVER@, stop:0.5 @ACCENT@, stop:1 @ACCENT_DARK@); border: none; }
QPushButton#Primary:pressed { background: @ACCENT_DARK@; border: none; }
QPushButton#Primary:disabled { background: @BORDER@; color: #6B675F; border: none; }
QPushButton#Danger {
    background: rgba(229, 72, 77, 0.10); border: 1px solid #E5484D;
    border-radius: 8px; padding: 9px 18px; color: #E5484D; font-weight: 600;
}
QPushButton#Danger:hover { background: #E5484D; border-color: #E5484D; color: #FFFFFF; }
QPushButton#Danger:pressed { background: #C03035; border-color: #C03035; color: #FFFFFF; }
QPushButton#Nav {
    background: transparent; border: none; border-radius: 10px;
    margin: 2px 2px; padding: 10px 16px; text-align: left; color: #9a9a9a; font-weight: 600;
}
QPushButton#Nav:hover { background: rgba(255,255,255,10); color: #cdcdcd; border: none; }
QPushButton#Nav:checked { background: rgba(255,255,255,10); color: #ffffff; border: none; }
QPushButton#Ghost { background: transparent; border: 1px solid @BORDER@; border-radius: 8px; padding: 4px; }
QPushButton#Ghost:hover { border-color: @ACCENT@; background: transparent; }
QPushButton#TitleBtn { background: transparent; border: none; border-radius: 10px; padding: 0; }
QPushButton#TitleBtn:hover { background: @CARD_HOVER@; border: none; }
QPushButton#CloseBtn { background: transparent; border: none; border-radius: 10px; padding: 0; }
QPushButton#CloseBtn:hover { background: #E5484D; border: none; }
QPushButton#Tab {
    background: @CARD@; border: 1px solid @BORDER@; border-radius: 8px;
    padding: 10px 34px 10px 22px; min-width: 150px; text-align: left; color: @MUTED@;
}
QPushButton#Tab:hover { border-color: @ACCENT@; color: @TEXT@; }
QPushButton#Tab:checked { background: @CARD@; border: 1px solid @ACCENT@; color: @TEXT@; }
QPushButton#TabClose { background: transparent; border: none; border-radius: 8px; padding: 0; }
QPushButton#TabClose:hover { background: rgba(255,255,255,0.14); border: none; }
QPushButton#IconSq { min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; padding: 0; border-radius: 8px; }

/* ============ inputs ============ */
QLineEdit {
    background: @GLASS@; border: 1px solid @GLASS_BORDER@; border-radius: 8px;
    padding: 10px 14px; color: @TEXT@; selection-background-color: @HAIR@;
}
QLineEdit:focus { border-color: @ACCENT_DARK@; }
QLineEdit:disabled { background: @GLASS@; color: #6B675F; }
QPlainTextEdit#Code { background: transparent; border: none; padding: 6px 8px; selection-background-color: @BORDER@; }
QPlainTextEdit#Log { background: @BG@; border: 1px solid @GLASS_BORDER@; padding: 6px 8px; color: @TEXT@; font-family: Consolas; font-size: 15px; selection-background-color: @HAIR@; } /* v1.52 solid + bright, v1.55: 15px, was 11px — terminal was too small to read */
QPlainTextEdit {
    background: @GLASS@; border: 1px solid @GLASS_BORDER@; border-radius: 12px;
    padding: 8px; color: @TEXT@; selection-background-color: @HAIR@;
}
QPlainTextEdit:focus { border-color: @ACCENT@; }
QCheckBox { spacing: 10px; color: @TEXT@; }
QCheckBox:disabled { color: #6B675F; }
QCheckBox::indicator { width: 40px; height: 24px; border-radius: 12px; border: 1px solid @BORDER@; background: @CARD_HOVER@; }
QCheckBox::indicator:hover { border-color: @ACCENT@; }
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; }
QCheckBox::indicator:disabled { background: @BG@; border-color: @BORDER@; }
QComboBox {
    background: @GLASS@; border: 1px solid @GLASS_BORDER@; border-radius: 8px;
    padding: 10px 14px; color: @TEXT@;
}
QComboBox:focus { border-color: @ACCENT_DARK@; }
QComboBox:disabled { background: @GLASS@; color: #6B675F; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView {
    background: @INPUT_BG@; border: 1px solid @BORDER@; border-radius: 12px;
    selection-background-color: @ACCENT@; selection-color: @ON_ACCENT@; outline: none;
}
QComboBox QAbstractItemView::item { padding: 7px 12px; border: none; }
QSpinBox, QDoubleSpinBox {
    background: @GLASS@; border: 1px solid @GLASS_BORDER@; border-radius: 8px;
    padding: 7px 10px; color: @TEXT@; selection-background-color: @HAIR@;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: @ACCENT@; }
QSpinBox:disabled, QDoubleSpinBox:disabled { background: @GLASS@; color: #6B675F; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }
QSlider::groove:horizontal { background: @BORDER@; height: 4px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @ACCENT@; border-radius: 2px; }
QSlider::add-page:horizontal { background: @INPUT_BG@; border-radius: 3px; }
QSlider::handle:horizontal { background: #ffffff; width: 20px; height: 20px; margin: -8px 0; border-radius: 10px; border: 4px solid @ACCENT@; }
QSlider::handle:horizontal:hover { background: @ACCENT_HOVER@; }
QSlider::handle:horizontal:pressed { background: @ACCENT_DARK@; }
QSlider::groove:vertical { background: @BORDER@; width: 4px; border-radius: 2px; }
QSlider::handle:vertical { background: #ffffff; width: 20px; height: 20px; margin: 0 -8px; border-radius: 10px; border: 4px solid @ACCENT@; }
QProgressBar {
    background: @GLASS@; border: none; border-radius: 6px;
    text-align: center; color: @TEXT@; height: 12px; font-size: 10px;
}
QProgressBar::chunk { background: @ACCENT@; border-radius: 6px; }

/* ============ scrollbars ============ */
QScrollArea { border: none; background: transparent; }
/* The viewport behind cards/labels must match BG too — otherwise any
   not-yet-painted region (fast scroll, fresh cards) flashes white. */
QScrollArea > QWidget { background: transparent; }
QAbstractScrollArea::viewport { background: transparent; }
QScrollBar:vertical { background: transparent; width: 4px; margin: 0px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,77); border-radius: 2px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,120); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 4px; margin: 0px; }
QScrollBar::handle:horizontal { background: rgba(255,255,255,77); border-radius: 2px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: rgba(255,255,255,120); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ============ menus / tooltips / dialogs ============ */
QMenu { background: @CARD@; border: 1px solid @BORDER@; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 8px 26px 8px 16px; border-radius: 10px; color: @TEXT@; background: transparent; }
QMenu::item:selected { background: @CARD_HOVER@; }
QMenu::separator { height: 1px; background: @BORDER@; margin: 5px 10px; }
QToolTip { background: @CARD@; color: @TEXT@; border: 1px solid @BORDER@; border-radius: 10px; padding: 7px 10px; }
QDialog, QMessageBox { background: @BG@; }
QStackedWidget { background: transparent; }

/* ============ v1.36.0 100 visual improvements (QSS only, no layout changes) ============ */
/* Typography 1-12 */
QWidget { font-family: "Segoe UI"; } /* 1 base font family, consistent everywhere */
QLabel#PageTitle { font-weight: 800; } /* 2 page titles bolder */
QLabel#HeroTitle { font-weight: 800; } /* 3 hero title bolder */
QLabel#CardHead { font-weight: 800; } /* 4 card heads bolder */
QLabel#Brand { font-weight: 900; } /* 5 app name bolder, v1.49 header bigger/bolder */
QLabel#RowTitle { font-weight: 800; } /* 6 row titles bolder */
QLabel#SectionHeader { font-weight: 700; } /* 7 section headers bolder */
QLabel#CardTitle { font-weight: 800; } /* 8 card titles bolder */
QLabel#HeroStat { font-weight: 900; } /* 9 hero stats extra bold */
QPushButton { font-weight: 700; } /* 10 all buttons bolder */
QPushButton#Primary { font-weight: 800; } /* 11 primary buttons extra bold */
QLabel#Ver { font-size: 12px; } /* 12 version label slightly larger */
/* Cards / structure 13-24 */
QFrame#Card { background: transparent; border-bottom: 1px solid rgba(255,255,255,15); } /* 13 v1.41.0 rows not cards */
QFrame#Card:hover { background: rgba(255,255,255,10); } /* 14 v1.41.0 row hover wash only, no accent border */
QFrame#Hero { background: transparent; border-bottom: 1px solid rgba(255,255,255,15); } /* 15 v1.41.0 hero is a row */
QFrame#Hero:hover { background: rgba(255,255,255,10); } /* 16 v1.41.0 hero hover wash only */
QFrame#StatusBar { background: transparent; } /* 17 v1.40.0: status bar transparent over photo (later rule must stay transparent or it overrides the first) */
QFrame#Hair { background: rgba(255,255,255,15); } /* 18 v1.41.0 hairline white 6% like his */
QFrame#Sidebar { background: transparent; } /* 19 v1.40.0: sidebar transparent over photo, not a solid panel */
QLabel#CardTitle { color: @TEXT@; } /* 20 card titles explicit text color */
QLabel#Empty { color: @MUTED@; } /* 21 empty states use muted, not dull grey */
QLabel#Count { color: @TEXT@; font-weight: 700; } /* 22 counts bolder */
QLabel#Ver { color: @MUTED@; } /* 23 version label muted, not dull grey */
QLabel#PageSub { font-weight: 400; } /* 24 subtitles regular weight, contrast with bold titles */
/* Buttons 25-44 */
QPushButton:hover { font-weight: 700; } /* 25 buttons bolden on hover */
QPushButton:pressed { color: @MUTED@; } /* 26 buttons dim when pressed */
QPushButton:disabled { font-weight: 400; } /* 27 disabled buttons lighter weight */
QPushButton#Primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @ACCENT_HOVER@, stop:0.5 @ACCENT@, stop:1 @ACCENT_DARK@); } /* 28 primary hover gradient, diagonal reversed, v1.50 tri-color */
QPushButton#Primary:pressed { background: @ACCENT_DARK@; color: @ON_ACCENT@; } /* 29 primary pressed darker */
QPushButton#Primary:disabled { font-weight: 400; } /* 30 disabled primary lighter weight */
QPushButton#Danger:hover { font-weight: 700; } /* 31 danger hover bolder */
QPushButton#Danger:pressed { border-color: #C03035; } /* 32 danger pressed darker border */
QPushButton#Ghost:hover { background: @CARD_HOVER@; } /* 33 ghost hover fills in, not just border */
QPushButton#Ghost:pressed { background: @BG@; } /* 34 ghost pressed darker */
QPushButton#TitleBtn:hover { color: @TEXT@; } /* 35 title buttons text color on hover */
QPushButton#CloseBtn:hover { background: #E5484D; } /* 36 close hover red, explicit */
QPushButton#Tab:hover { background: @CARD_HOVER@; } /* 37 tabs fill on hover */
QPushButton#Tab:checked { background: @CARD_HOVER@; } /* 38 checked tabs fill, not flat card */
QPushButton#TabClose:hover { background: rgba(255,255,255,0.14); } /* 39 tab close hover, explicit */
QPushButton#IconSq:hover { border: 1px solid @ACCENT@; } /* 40 icon buttons orange border on hover */
QPushButton#IconSq:pressed { background: @BG@; } /* 41 icon buttons pressed darker */
QPushButton#Nav:hover { border: 1px solid transparent; } /* 42 nav hover transparent border, so checked border never jumps layout */
QPushButton#Nav:checked { font-weight: 700; } /* 43 active nav tab bolder */
QPushButton#Nav:pressed { background: @BG@; } /* 44 nav pressed darker */
/* Inputs 45-60 */
QLineEdit:hover { border-color: @HAIR@; } /* 45 inputs border lightens on hover */
QLineEdit:focus { background: @CARD_HOVER@; } /* 46 inputs fill on focus, in addition to orange border */
QLineEdit:disabled { border-color: @BORDER@; } /* 47 disabled inputs border explicit */
QComboBox:hover { border-color: @HAIR@; } /* 48 dropdowns border lightens on hover */
QComboBox:focus { background: @CARD_HOVER@; } /* 49 dropdowns fill on focus */
QComboBox:disabled { background: @BG@; } /* 50 disabled dropdowns background explicit */
QComboBox::drop-down { background: transparent; } /* 51 dropdown arrow area transparent */
QComboBox QAbstractItemView::item:selected { background: @ACCENT@; } /* 52 dropdown selected item orange, explicit */
QComboBox QAbstractItemView::item:hover { background: @CARD_HOVER@; } /* 53 dropdown hover fill */
QSpinBox:hover { border-color: @HAIR@; } /* 54 spin boxes border lightens on hover */
QSpinBox:focus { background: @CARD_HOVER@; } /* 55 spin boxes fill on focus */
QPlainTextEdit:hover { border-color: @HAIR@; } /* 56 text areas border lightens on hover */
QPlainTextEdit:focus { background: @CARD_HOVER@; } /* 57 text areas fill on focus */
QPlainTextEdit#Log { font-size: 15px; } /* 58 log text larger, easier to read — v1.55: 15px, was 12px */
QPlainTextEdit#Code { color: @TEXT@; } /* 59 code text explicit color */
QDoubleSpinBox:hover { border-color: @HAIR@; } /* 60 double spin boxes border lightens on hover */
/* CheckBox / Slider / Progress 61-75 */
QCheckBox { color: @TEXT@; } /* 61 checkboxes text explicit */
QCheckBox::indicator:hover { border-color: @ACCENT@; } /* 62 checkbox indicator orange on hover, explicit */
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; } /* 63 checked indicator orange, explicit */
QCheckBox::indicator:disabled { background: @BG@; } /* 64 disabled indicator background explicit */
QSlider::groove:horizontal { border: none; } /* 65 slider groove no border */
QSlider::sub-page:horizontal { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @ACCENT@, stop:1 @ACCENT_HOVER@); } /* 66 slider fill gradient */
QSlider::add-page:horizontal { background: @INPUT_BG@; } /* 67 slider track explicit */
QSlider::handle:horizontal { border: 2px solid @BG@; } /* 68 slider handle pops against groove */
QSlider::handle:horizontal:hover { background: @ACCENT_HOVER@; } /* 69 slider handle hover, explicit */
QSlider::handle:horizontal:pressed { background: @ACCENT_DARK@; } /* 70 slider handle pressed, explicit */
QSlider::groove:vertical { border: none; } /* 71 vertical slider groove no border */
QSlider::handle:vertical { border: 2px solid @BG@; } /* 72 vertical handle pops */
QProgressBar { color: @TEXT@; } /* 73 progress text explicit */
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @ACCENT@, stop:1 @ACCENT_HOVER@); } /* 74 progress fill gradient */
QSlider::handle:vertical:hover { background: @ACCENT_HOVER@; } /* 75 vertical handle hover */
/* Scrollbars / Menus / Tooltips / Dialogs 76-100 */
QScrollArea { background: transparent; } /* 76 v1.42.0 STEP 1: was solid BG, hid the photo — black box fix */
QScrollArea > QWidget { background: transparent; } /* 77 v1.42.0 STEP 1: transparent, like his */
QAbstractScrollArea::viewport { background: transparent; } /* 78 v1.42.0 STEP 1: transparent, like his */
QScrollBar:vertical { width: 4px; } /* 79 v1.42.0 STEP 1: 4px like his, not 12px */
QScrollBar::handle:vertical { border-radius: 2px; } /* 80 v1.42.0 STEP 1: 2px like his */
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,120); } /* 81 vertical handle orange on hover, explicit */
QScrollBar::handle:vertical:pressed { background: @ACCENT_DARK@; } /* 82 vertical handle pressed darker */
QScrollBar:horizontal { height: 4px; } /* 83 v1.42.0 STEP 1: 4px like his */
QScrollBar::handle:horizontal { border-radius: 2px; } /* 84 v1.42.0 STEP 1: 2px like his */
QScrollBar::handle:horizontal:hover { background: rgba(255,255,255,120); } /* 85 horizontal handle orange on hover, explicit */
QScrollBar::handle:horizontal:pressed { background: @ACCENT_DARK@; } /* 86 horizontal handle pressed darker */
QScrollBar::add-page:vertical { background: transparent; } /* 87 vertical scrollbar track page transparent */
QMenu { border-radius: 12px; } /* 88 menus rounder */
QMenu::item { font-weight: 600; } /* 89 menu items semibold */
QMenu::item:selected { color: @TEXT@; } /* 90 selected menu item text explicit */
QMenu::separator { border: none; } /* 91 menu separators no border */
QToolTip { background: @CARD_HOVER@; border: 1px solid @ACCENT@; padding: 8px 12px; font-size: 13px; } /* 92 tooltips pop: hover background, orange border, larger padding */
QDialog { border: 1px solid @BORDER@; } /* 93 dialogs bordered */
QMessageBox { border: 1px solid @BORDER@; } /* 94 message boxes bordered */
QStackedWidget { border: none; } /* 95 stacked pages no border */
QScrollBar::sub-page:vertical { background: transparent; } /* 96 vertical scrollbar sub-page transparent */
QScrollBar::add-page:horizontal { background: transparent; } /* 97 horizontal scrollbar page transparent */
QScrollBar::sub-page:horizontal { background: transparent; } /* 98 horizontal scrollbar sub-page transparent */
QMenu::item:disabled { color: #6B675F; } /* 99 disabled menu items dull grey */
QComboBox::down-arrow { border: none; } /* 100 dropdown arrow no border */

/* ============ v1.38.0 Config Editor shapes: buttons 8px, top-bar 10px (supersedes v1.37 pill rule by explicit user choice) ============ */
QPushButton { border-radius: 8px; }
QPushButton:hover, QPushButton:pressed, QPushButton:disabled, QPushButton:checked { border-radius: 8px; }
QPushButton#Primary, QPushButton#Danger, QPushButton#Ghost, QPushButton#Tab, QPushButton#TabClose, QPushButton#IconSq { border-radius: 8px; }
QPushButton#Primary:hover, QPushButton#Primary:pressed, QPushButton#Primary:disabled, QPushButton#Danger:hover, QPushButton#Danger:pressed, QPushButton#Nav:hover, QPushButton#Nav:checked, QPushButton#Nav:pressed, QPushButton#Ghost:hover, QPushButton#Ghost:pressed, QPushButton#Tab:hover, QPushButton#Tab:checked, QPushButton#TitleBtn:hover, QPushButton#CloseBtn:hover, QPushButton#TabClose:hover, QPushButton#IconSq:hover, QPushButton#IconSq:pressed { border-radius: 8px; }
QToolButton { background: @CARD@; border: 1px solid @BORDER@; border-radius: 8px; padding: 8px 16px; color: @TEXT@; }
QToolButton:hover { border-color: @ACCENT@; }
QDialogButtonBox QPushButton { border-radius: 8px; }

QPushButton#Nav, QPushButton#TitleBtn, QPushButton#CloseBtn { border-radius: 10px; }
QPushButton#Nav:hover, QPushButton#Nav:checked, QPushButton#TitleBtn:hover, QPushButton#CloseBtn:hover { border-radius: 10px; }

/* ============ v1.38.0 Config Editor final overrides (last, so they win) ============ */
QFrame#Card { background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,15); border-radius: 0px; }
QFrame#Card:hover { background: rgba(255,255,255,10); border: none; border-bottom: 1px solid rgba(255,255,255,15); }
QFrame#Hero { background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,15); border-radius: 0px; }
QFrame#Hero:hover { background: rgba(255,255,255,10); border: none; border-bottom: 1px solid rgba(255,255,255,15); }
QPushButton#Primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @ACCENT_DARK@, stop:0.5 @ACCENT@, stop:1 @ACCENT_HOVER@); border: none; border-radius: 8px; }
QPushButton#Primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @ACCENT_HOVER@, stop:0.5 @ACCENT@, stop:1 @ACCENT_DARK@); border: none; }
QPushButton#Nav:checked { background: @CARD_HOVER@; color: @TEXT@; border: none; }
QPushButton#Nav:hover { background: @CARD_HOVER@; color: @TEXT@; border: none; }

/* ============ v1.42.0 STEP 1 final overrides (LAST, so they win over v1.36/v1.38) ============ */
/* Black box, every tab: all 8 pages use a QScrollArea (Dashboard, Versions x2, Mods, Host, Backups, Help, Settings, Tools).
   Earlier transparent rules were overridden by v1.36 rules 76-78 (solid @BG@). These last rules re-assert transparent,
   so the photo shows through the center column on every tab, not just Dashboard. Sidebar/details are not scroll areas,
   which is why they already showed the photo while the center did not. */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget { background: transparent; }
QAbstractScrollArea::viewport { background: transparent; }
QStackedWidget { background: transparent; }
QScrollBar:vertical { width: 4px; }
QScrollBar:horizontal { height: 4px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,77); border-radius: 2px; }
QScrollBar::handle:horizontal { background: rgba(255,255,255,77); border-radius: 2px; }
QPushButton#Nav:checked { background: rgba(255,255,255,10); color: #ffffff; border: none; }
QPushButton#Nav:hover { background: rgba(255,255,255,10); color: #cdcdcd; border: none; }
"""
apply_theme("ember")  # initial; main() re-applies the saved theme

# ------------------------------------------------------------------- icons
_ICON_CACHE = {}
def _pt(r, fx, fy): return QPointF(r.x() + r.width() * fx, r.y() + r.height() * fy)
def _poly(p, r, pts): p.drawPolyline([_pt(r, x, y) for x, y in pts])

def _i_dashboard(p, r):
    g = 0.14; s = (1 - g) / 2
    for x, y in [(0, 0), (s + g, 0), (0, s + g), (s + g, s + g)]:
        p.drawRoundedRect(QRectF(r.x() + r.width() * x, r.y() + r.height() * y, r.width() * s, r.height() * s), 2, 2)
def _i_code(p, r): _poly(p, r, [(0.35, 0.22), (0.10, 0.50), (0.35, 0.78)]); _poly(p, r, [(0.65, 0.22), (0.90, 0.50), (0.65, 0.78)])
def _i_book(p, r): p.drawRoundedRect(r, 3, 3); p.drawLine(_pt(r, 0.32, 0.12), _pt(r, 0.32, 0.88))
def _i_users(p, r):
    p.drawEllipse(QRectF(r.x() + r.width() * 0.14, r.y() + r.height() * 0.16, r.width() * 0.34, r.height() * 0.34))
    p.drawArc(QRectF(r.x() + r.width() * 0.06, r.y() + r.height() * 0.56, r.width() * 0.50, r.height() * 0.44), 0, 180 * 16)
def _i_gear(p, r):
    p.drawEllipse(QRectF(r.x() + r.width() * 0.30, r.y() + r.height() * 0.30, r.width() * 0.40, r.height() * 0.40))
    c = _pt(r, 0.5, 0.5)
    for a in range(0, 360, 45):
        t = math.radians(a)
        p1 = QPointF(c.x() + math.cos(t) * r.width() * 0.20, c.y() - math.sin(t) * r.height() * 0.20)
        p2 = QPointF(c.x() + math.cos(t) * r.width() * 0.42, c.y() - math.sin(t) * r.height() * 0.42)
        p.drawLine(p1, p2)
def _i_monitor(p, r):
    p.drawRoundedRect(QRectF(r.x() + r.width() * 0.06, r.y() + r.height() * 0.14, r.width() * 0.88, r.height() * 0.56), 3, 3)
    p.drawLine(_pt(r, 0.5, 0.70), _pt(r, 0.5, 0.86)); p.drawLine(_pt(r, 0.30, 0.88), _pt(r, 0.70, 0.88))
def _i_box(p, r):
    _poly(p, r, [(0.5, 0.06), (0.9, 0.28), (0.5, 0.50), (0.1, 0.28), (0.5, 0.06)])
    _poly(p, r, [(0.1, 0.28), (0.1, 0.70), (0.5, 0.92), (0.9, 0.70), (0.9, 0.28)]); p.drawLine(_pt(r, 0.5, 0.50), _pt(r, 0.5, 0.92))
def _i_trend(p, r): _poly(p, r, [(0.06, 0.78), (0.36, 0.46), (0.54, 0.62), (0.92, 0.24)]); _poly(p, r, [(0.70, 0.24), (0.92, 0.24), (0.92, 0.46)])
def _i_award(p, r):
    p.drawEllipse(QRectF(r.x() + r.width() * 0.30, r.y() + r.height() * 0.10, r.width() * 0.40, r.height() * 0.40))
    _poly(p, r, [(0.38, 0.48), (0.34, 0.90), (0.50, 0.76), (0.66, 0.90), (0.62, 0.48)])
def _i_crown(p, r): _poly(p, r, [(0.10, 0.78), (0.10, 0.34), (0.32, 0.52), (0.50, 0.26), (0.68, 0.52), (0.90, 0.34), (0.90, 0.78), (0.10, 0.78)])
def _i_link(p, r):
    p.drawArc(QRectF(r.x() + r.width() * 0.06, r.y() + r.height() * 0.28, r.width() * 0.44, r.height() * 0.44), 90 * 16, 180 * 16)
    p.drawArc(QRectF(r.x() + r.width() * 0.50, r.y() + r.height() * 0.28, r.width() * 0.44, r.height() * 0.44), 270 * 16, 180 * 16)
    p.drawLine(_pt(r, 0.35, 0.50), _pt(r, 0.65, 0.50))
def _i_play(p, r): _poly(p, r, [(0.30, 0.18), (0.82, 0.50), (0.30, 0.82), (0.30, 0.18)])
def _i_trash(p, r):
    p.drawLine(_pt(r, 0.18, 0.26), _pt(r, 0.82, 0.26))
    _poly(p, r, [(0.40, 0.26), (0.40, 0.14), (0.60, 0.14), (0.60, 0.26)])
    _poly(p, r, [(0.26, 0.26), (0.30, 0.88), (0.70, 0.88), (0.74, 0.26)])
def _i_power(p, r):
    p.drawArc(QRectF(r.x() + r.width() * 0.16, r.y() + r.height() * 0.22, r.width() * 0.68, r.height() * 0.68), 120 * 16, 300 * 16)
    p.drawLine(_pt(r, 0.5, 0.08), _pt(r, 0.5, 0.42))
def _i_save(p, r):
    p.drawRoundedRect(QRectF(r.x() + r.width() * 0.14, r.y() + r.height() * 0.14, r.width() * 0.72, r.height() * 0.72), 3, 3)
    _poly(p, r, [(0.32, 0.14), (0.32, 0.42), (0.68, 0.42), (0.68, 0.14)])
def _i_folder(p, r): _poly(p, r, [(0.08, 0.78), (0.08, 0.26), (0.34, 0.26), (0.44, 0.38), (0.92, 0.38), (0.92, 0.78), (0.08, 0.78)])
def _i_plus(p, r): p.drawLine(_pt(r, 0.5, 0.2), _pt(r, 0.5, 0.8)); p.drawLine(_pt(r, 0.2, 0.5), _pt(r, 0.8, 0.5))
def _i_chev_l(p, r): _poly(p, r, [(0.62, 0.18), (0.34, 0.50), (0.62, 0.82)])
def _i_chev_r(p, r): _poly(p, r, [(0.38, 0.18), (0.66, 0.50), (0.38, 0.82)])
def _i_min(p, r): p.drawLine(_pt(r, 0.22, 0.5), _pt(r, 0.78, 0.5))
def _i_expand(p, r):
    p.drawLine(_pt(r, 0.58, 0.42), _pt(r, 0.86, 0.14)); _poly(p, r, [(0.64, 0.14), (0.86, 0.14), (0.86, 0.36)])
    p.drawLine(_pt(r, 0.42, 0.58), _pt(r, 0.14, 0.86)); _poly(p, r, [(0.14, 0.64), (0.14, 0.86), (0.36, 0.86)])
def _i_restore(p, r):
    p.drawRect(QRectF(r.x() + r.width() * 0.14, r.y() + r.height() * 0.30, r.width() * 0.56, r.height() * 0.56))
    _poly(p, r, [(0.34, 0.30), (0.34, 0.14), (0.86, 0.14), (0.86, 0.66), (0.70, 0.66)])
def _i_close(p, r): p.drawLine(_pt(r, 0.24, 0.24), _pt(r, 0.76, 0.76)); p.drawLine(_pt(r, 0.76, 0.24), _pt(r, 0.24, 0.76))
def _i_search(p, r): p.drawEllipse(QRectF(r.x() + r.width() * 0.14, r.y() + r.height() * 0.14, r.width() * 0.48, r.height() * 0.48)); p.drawLine(_pt(r, 0.52, 0.52), _pt(r, 0.86, 0.86))
def _i_refresh(p, r): p.drawArc(QRectF(r.x() + r.width() * 0.14, r.y() + r.height() * 0.14, r.width() * 0.72, r.height() * 0.72), 40 * 16, 280 * 16); _poly(p, r, [(0.90, 0.14), (0.90, 0.40), (0.64, 0.40)])
def _i_copy(p, r): p.drawRoundedRect(QRectF(r.x() + r.width() * 0.32, r.y() + r.height() * 0.12, r.width() * 0.54, r.height() * 0.58), 2, 2); _poly(p, r, [(0.32, 0.88), (0.14, 0.88), (0.14, 0.34)])
def _i_game(p, r):
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p.drawRoundedRect(QRectF(x + w * 0.10, y + h * 0.26, w * 0.80, h * 0.52), 5, 5)
    p.drawLine(_pt(r, 0.28, 0.44), _pt(r, 0.28, 0.60)); p.drawLine(_pt(r, 0.22, 0.52), _pt(r, 0.34, 0.52))
    p.setBrush(p.pen().color()); d = w * 0.10
    p.drawEllipse(QRectF(x + w * 0.60 - d / 2, y + h * 0.42 - d / 2, d, d))
    p.drawEllipse(QRectF(x + w * 0.72 - d / 2, y + h * 0.56 - d / 2, d, d))
    p.setBrush(Qt.BrushStyle.NoBrush)
def _i_planet(p, r):
    p.setBrush(p.pen().color()); p.drawEllipse(QRectF(r.x() + r.width() * 0.26, r.y() + r.height() * 0.26, r.width() * 0.48, r.height() * 0.48))
    p.setBrush(Qt.BrushStyle.NoBrush)
    ring = QPen(QColor(GOLD)); ring.setWidthF(p.pen().widthF()); ring.setCapStyle(Qt.PenCapStyle.RoundCap); ring.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(ring); p.save(); c = _pt(r, 0.5, 0.5); p.translate(c); p.rotate(-18); p.translate(-c)
    p.drawEllipse(QRectF(r.x() - r.width() * 0.02, r.y() + r.height() * 0.38, r.width() * 1.04, r.height() * 0.24)); p.restore()
def _i_star(p, r):
    pts = [(0.5, 0.05), (0.61, 0.38), (0.95, 0.38), (0.68, 0.59), (0.79, 0.91), (0.5, 0.71), (0.21, 0.91), (0.32, 0.59), (0.05, 0.38), (0.39, 0.38), (0.5, 0.05)]
    p.drawPolygon([_pt(r, x, y) for x, y in pts])
def _i_help(p, r):
    # Bold "?" rendered as text — paths can't draw a clean question mark
    # at 17px, and the painter already carries the icon color via its pen.
    f = QFont("Segoe UI"); f.setBold(True); f.setPixelSize(int(r.height() * 0.98))
    p.setFont(f); p.drawText(r, Qt.AlignmentFlag.AlignCenter, "?")

ICONS = {
    "dashboard": _i_dashboard, "code": _i_code, "book": _i_book, "users": _i_users,
    "gear": _i_gear, "monitor": _i_monitor, "box": _i_box, "trend": _i_trend,
    "award": _i_award, "crown": _i_crown, "link": _i_link, "play": _i_play,
    "trash": _i_trash, "power": _i_power, "save": _i_save, "folder": _i_folder,
    "plus": _i_plus, "chev_l": _i_chev_l, "chev_r": _i_chev_r, "min": _i_min,
    "expand": _i_expand, "restore": _i_restore, "close": _i_close,
    "search": _i_search, "refresh": _i_refresh, "copy": _i_copy, "planet": _i_planet,
    "star": _i_star, "help": _i_help, "game": _i_game
}

def icon(name, size=16, color=None, weight=1.6):
    if color is None:
        color = TEXT  # live theme text color, so icons stay visible on light and dark themes
    key = (name, size, color, weight)
    if key in _ICON_CACHE: return _ICON_CACHE[key]
    dpr = 2; pm = QPixmap(size * dpr, size * dpr); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color)); pen.setWidthF(weight * dpr); pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
    m = weight * dpr + 1; ICONS[name](p, QRectF(m, m, pm.width() - 2 * m, pm.height() - 2 * m))
    p.end(); pm.setDevicePixelRatio(dpr); _ICON_CACHE[key] = pm; return pm

def brand_pixmap(size=32):
    try:
        p = _resource("logo.png")
        if p.exists():
            pm = QPixmap(str(p))
            if not pm.isNull(): return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    except Exception: pass
    return icon("planet", size, "#f2f2f2", 1.8)

def icon_btn(name, text="", size=16, tip=""):
    b = QPushButton(text); b.setIcon(QIcon(icon(name, size))); b.setIconSize(QSize(size, size))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip: b.setToolTip(tip)
    return b

def hair():
    f = QFrame(); f.setObjectName("Hair"); return f

def centered_label(pixmap):
    l = QLabel(); l.setPixmap(pixmap); l.setAlignment(Qt.AlignmentFlag.AlignCenter); return l

def page_header(title, subtitle="", actions=None):
    """Unified page header: big title + muted subtitle, action buttons right."""
    wrap = QWidget()
    h = QHBoxLayout(wrap); h.setContentsMargins(2, 4, 2, 14); h.setSpacing(12)
    col = QVBoxLayout(); col.setContentsMargins(0, 0, 0, 0); col.setSpacing(3)
    t = QLabel(title); t.setObjectName("PageTitle"); col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle); s.setObjectName("PageSub"); s.setWordWrap(True); col.addWidget(s)
    h.addLayout(col, 1)
    for a in (actions or []):
        h.addWidget(a, 0, Qt.AlignmentFlag.AlignBottom)
    return wrap

# ------------------------------------------------------------------ storage
class Store:
    DEFAULTS = {
        "window_size_autosave": True, "window_size": None,
        "sidebar_width": 240, "sidebar_collapsed": False,
        "launch_args": "", "favorites": [], "dlc_excluded": {},
        "servers": [],  # v1.65.0: user-added servers {name, ip, game_port, query_port, cluster, favorite}
        "game_culture": "",  # v1.66.0: "" = Steam default, else a -culture= code appended at Play
        "close_on_launch": False,  # v1.66.0: close the launcher when the game launches
        "steam_path": "", "install_dir": "", "default_dlc_excluded": [],
        "steam_username": "",
        "custom_background": "", "background_opacity": 1.0,
        # v1.20.0
        "profiles": [{"name": "Default", "player_name": "", "build": "",
                      "launch_args": "", "host_preset": ""}],
        "active_profile": "Default",
        "launch_arg_presets": {
            "High FPS": "-sm4 -lowmemory -nomansky",
            "Balanced": "-sm4",
            "Windowed": "-windowed -ResX=1280 -ResY=720",
            "Pretty": "",
        },
        "auto_backup": False,
        "discord_rich_presence": False,
        "discord_client_id": "1561553907270951002",
        "steam_detected_once": False,
        "update_notes": {},
    }
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        saved = {}
        try: saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError): pass
        self.settings = {**self.DEFAULTS, **saved}

    def save(self): SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
    def get(self, key, default=None): return self.settings.get(key, default)
    def set(self, key, value): self.settings[key] = value; self.save()

# ------------------------------------------- CML version engine
STEAM_APP_ID = "346110"
DEPOT_MAP = {
    "base": 346111, "center": 346114, "primitive": 346117, "scorched": 375351,
    "ragnarok": 375354, "aberration": 375357, "extinction": 473851, "valguero": 473854,
    "genesis": 473857, "crystal_isles": 1318685, "lost_island": 1691801, "fjordur": 1887561, "aquatica": 3537070,
}
DLC_NAMES = {
    "center": "The Center", "primitive": "Primitive+", "scorched": "Scorched Earth",
    "ragnarok": "Ragnarok", "aberration": "Aberration", "extinction": "Extinction",
    "valguero": "Valguero", "genesis": "Genesis", "crystal_isles": "Crystal Isles",
    "lost_island": "Lost Island", "fjordur": "Fjordur", "aquatica": "Aquatica",
}
DLC_ORDER = ["center", "primitive", "scorched", "ragnarok", "aberration",
             "extinction", "valguero", "genesis", "crystal_isles", "lost_island", "fjordur", "aquatica"]

def era_art_key(version):
    """Art key for a version card: the latest DLC in DLC_ORDER with a
    manifest (DLC_ORDER is chronological), else 'base' for DLC-free builds."""
    for key in reversed(DLC_ORDER):
        if version.get(key):
            return key
    return "base"

# ARK's own store headers, one per map/DLC, straight from Steam's CDN
# (shared.akamai.steamstatic.com, public, no login). These are NOT
# bundled in the zip — the launcher downloads them on demand, so the
# zip never ships Wildcard's art. Keys match era_art_key()'s keys;
# genesis uses the Genesis Season Pass header (Part 1 + Part 2 share it).
OFFICIAL_HEADERS = {
    "base": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/346110/header.jpg",
    "center": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/473850/header.jpg",
    "primitive": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/508150/header.jpg",
    "scorched": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/512540/header.jpg",
    "ragnarok": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/642250/header.jpg",
    "aberration": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/708770/header.jpg",
    "extinction": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/887380/header.jpg",
    "valguero": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1100810/header.jpg",
    "genesis": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1113410/header.jpg",
    "crystal_isles": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1270830/header.jpg",
    "lost_island": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1691800/header.jpg",
    "fjordur": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1887560/header.jpg",
    "aquatica": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/3537070/82c8febf8513ce7445b4d79994b19655908521ca/header.jpg",
}

def download_official_headers():
    """Download ARK's own headers into art/ (overwriting the generated
    banners). Returns (ok_count, [(key, error), ...]). Each file is
    verified as a real JPEG before it replaces the old one, so a bad
    download never leaves a broken card behind."""
    try:
        ART_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return 0, [(k, str(e)) for k in OFFICIAL_HEADERS]
    ok, failed = 0, []
    for key, url in OFFICIAL_HEADERS.items():
        tmp = ART_DIR / f".{key}.tmp"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LegacyARKLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            if len(data) < 5000 or data[:2] != b"\xff\xd8":
                raise ValueError("not a JPEG")
            tmp.write_bytes(data)
            (ART_DIR / f"{key}.jpg").write_bytes(data)
            try:
                tmp.unlink()
            except OSError:
                pass
            ok += 1
        except Exception as e:
            failed.append((key, str(e)))
            try:
                tmp.unlink()
            except OSError:
                pass
    _ART_CACHE.clear()
    return ok, failed

def slugify(name):
    out = []
    for ch in str(name).lower():
        if ch.isalnum(): out.append(ch)
        elif ch in (" ", "_", "-"): out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug: slug = slug.replace("--", "-")
    return slug or "build"

_MONTHS = {n: i + 1 for i, n in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"])}
_MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
                "nov": 11, "dec": 12})
_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def _version_and_date(name):
    """('v252.96', 'Dec 2016') from 'v252.96 (Dec 2016)'; ('', 'Oct 2016')
    from 'Oct 2016 build'. A version number only exists for verified
    builds — monthly picks are identified by their date."""
    ver = ""
    m = re.search(r"\bv\d[\d.]*", str(name), re.IGNORECASE)
    if m: ver = m.group(0)
    year, month = parse_version_date(name)
    date = f"{_MONTH_ABBR[month]} {year}" if year != 9999 else ""
    return ver, date

# In-memory cache of measured build sizes (version name -> GB), filled
# by _SizeThread off the GUI thread. Dashboard and cards read this —
# nothing on the UI thread ever walks the disk.
_SIZE_CACHE = {}

def _estimate_size_gb(version):
    """Rough download size for a NOT-installed build, in GB. Shown with ~
    on the card — the game grew every year, so the year sets the base."""
    year, _month = parse_version_date(version.get("name", ""))
    base = {2015: 16, 2016: 25, 2017: 40, 2018: 55, 2019: 70, 2020: 80}.get(year, 95)
    n_dlc = sum(1 for k in DLC_ORDER if version.get(k))
    return base + n_dlc * 5

def parse_version_date(name):
    """(year, month) parsed from a build name like 'Apr 2016 build' or
    'v252.96 (Dec 2016)'. Full month names and 3-letter abbreviations,
    case-insensitive. Unparseable names sort last (9999, 12)."""
    m = re.search(
        r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
        r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?"
        r"|nov(?:ember)?|dec(?:ember)?)\s+(\d{4})",
        str(name), re.IGNORECASE)
    if not m:
        return (9999, 12)
    return (int(m.group(2)), _MONTHS.get(m.group(1).lower(), 12))

def load_versions():
    """Read versions.json. Automatically strips trailing spaces from keys/values to prevent KeyErrors."""
    path = _resource("versions.json")
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except OSError: return [], "versions.json not found next to the launcher."
    except ValueError: return [], "versions.json is not valid JSON."
    
    raw_versions = data.get("versions", []) if isinstance(data, dict) else []
    cleaned_versions = []
    for v in raw_versions:
        if isinstance(v, dict):
            # FIX: Strip whitespace from all keys and values dynamically
            cleaned_v = {str(k).strip(): str(val).strip() for k, val in v.items()}
            if cleaned_v.get("base"):
                cleaned_versions.append(cleaned_v)
    return cleaned_versions, ""

def load_descriptions():
    """Optional display-only titles/descriptions per version name.
    Missing/invalid file -> {}. Never blocks the launcher."""
    path = _resource("descriptions.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

def _hidden_flags():
    """creationflags that keep background subprocesses (reg query,
    tasklist, powershell one-liners) from flashing a console window
    on Windows. Never used for SteamCMD — that window is intentionally
    visible so the user can type their password / Guard code in it."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# Steam's install path doesn't move mid-session — detect once, not on
# every call (each detection shells out, which used to flash a console
# on every Versions rebuild, e.g. toggling a favorite).
_STEAM_DIR_CACHE = None

def find_steam():
    global _STEAM_DIR_CACHE
    if _STEAM_DIR_CACHE is not None:
        return _STEAM_DIR_CACHE
    if os.name != "nt":
        _STEAM_DIR_CACHE = ""
        return ""
    queries = [
        (r"HKCU\Software\Valve\Steam", "SteamPath"),
        (r"HKLM\SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (r"HKLM\SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, value in queries:
        try:
            out = subprocess.run(["reg", "query", hive, "/v", value], capture_output=True, text=True, timeout=15,
                                 creationflags=_hidden_flags()).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.startswith(value):
                    parts = line.split()
                    if len(parts) >= 3:
                        cand = " ".join(parts[2:]).replace("/", "\\")
                        if os.path.isfile(os.path.join(cand, "steam.exe")):
                            _STEAM_DIR_CACHE = cand
                            return cand
        except (OSError, subprocess.SubprocessError): continue
    for cand in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isfile(os.path.join(cand, "steam.exe")):
            _STEAM_DIR_CACHE = cand
            return cand
    _STEAM_DIR_CACHE = ""
    return ""

def dir_size_gb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try: total += os.path.getsize(os.path.join(root, f))
            except OSError: pass
    return total / (1 << 30)

def steam_dir_for(store):
    """Steam folder: the Settings override if it points at a real Steam
    install (contains steam.exe), else auto-detect. Never returns a
    bogus folder — bad overrides fall back to detection."""
    override = (store.get("steam_path", "") or "").strip() if store else ""
    if override:
        p = Path(override)
        if p.is_dir() and (p / "steam.exe").is_file():
            return str(p)
    return find_steam()

def install_root_for(store, steam_dir=None):
    """Folder that holds the per-build folders (CML-ARK/<slug>).
    The Settings override if it exists, else Steam's common/CML-ARK.
    Last resort (Steam not found): ~/CML-ARK, so detection never crashes."""
    override = (store.get("install_dir", "") or "").strip() if store else ""
    if override:
        p = Path(override)
        if p.is_dir():
            return p
    if steam_dir is None:
        steam_dir = steam_dir_for(store)
    if steam_dir:
        return Path(steam_dir) / "steamapps" / "common" / "CML-ARK"
    return Path.home() / "CML-ARK"

def game_dir_for(store, version, steam_dir=None):
    return install_root_for(store, steam_dir) / slugify(version.get("name", ""))

def game_exe_for(steam_dir, version, store=None):
    base = install_root_for(store, steam_dir) if store is not None else (
        Path(steam_dir) / "steamapps" / "common" / "CML-ARK")
    return base / slugify(version.get("name", "")) / "ShooterGame" / "Binaries" / "Win64" / "ShooterGame.exe"

_TEK_ARK_CACHE = {}

def _tek_ark_detection(steam_dir):
    """v1.72.0: one-line summary of tek_lib's Steam-library detection
    (TEK Steam/App.cs port): is the *Steam* install of current ARK
    present, where, and with which DLC depots. Cached per Steam path -
    it reads libraryfolders.vdf + appmanifest_346110.acf. Returns ""
    when tek_lib is unavailable. Never raises."""
    if tek_lib is None:
        return ""
    key = steam_dir or ""
    if key in _TEK_ARK_CACHE:
        return _TEK_ARK_CACHE[key]
    txt = ""
    try:
        det = tek_lib.detect_ark_install(steam_dir or None)
        inst = det.get("install")
        libs = det.get("libraries") or []
        if inst is None:
            txt = ("Steam library check: no Steam-installed ARK found — that's fine, "
                   "your old builds live in the CML-ARK folder, not in Steam's library.")
        else:
            n_dlc = len(det.get("dlc_depots") or {})
            txt = (f"Steam library check: current ARK is installed at {inst.install_path} "
                   f"(build {inst.manifest.build_id or '?'}, {n_dlc} DLC depot"
                   f"{'s' if n_dlc != 1 else ''} detected). "
                   f"Your old builds still live in the CML-ARK folder.")
        if len(libs) > 1:
            txt += f" {len(libs)} Steam libraries found."
    except Exception:
        txt = ""
    _TEK_ARK_CACHE[key] = txt
    return txt

def _desktop_path():
    """User's Desktop folder (handles redirected folders)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Environment]::GetFolderPath('Desktop')"],
                           capture_output=True, text=True, timeout=15,
                           creationflags=_hidden_flags())
        p = (r.stdout or "").strip()
        if p and Path(p).is_dir():
            return Path(p)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"

def _write_shortcut(label, exe, args_str=""):
    """(Re)write the desktop shortcut with the custom "A" icon and the
    given launch arguments. Returns the .lnk path, or None on failure."""
    try:
        lnk = _desktop_path() / f"{label}.lnk"
        ico = _resource("logo.ico")
        icon_loc = f"; $s.IconLocation = '{ico}'" if ico.is_file() else ""
        args_ps = str(args_str or "").replace("'", "''")  # escape for PS
        ps = (f"$ws = New-Object -ComObject WScript.Shell; "
              f"$s = $ws.CreateShortcut('{lnk}'); $s.TargetPath = '{exe}'; "
              f"$s.Arguments = '{args_ps}'; "
              f"$s.WorkingDirectory = '{Path(exe).parent}'; $s.Description = 'Legacy ARK'{icon_loc}; $s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=60,
                           creationflags=_hidden_flags())
        return lnk if lnk.is_file() else None
    except (OSError, subprocess.SubprocessError):
        return None

def version_depots(version, excluded=None):
    """Depots for a version, skipping any DLC keys in `excluded`."""
    excluded = set(excluded or [])
    depots = [(DEPOT_MAP["base"], version["base"], "Base game", 5.0)]
    for key in DLC_ORDER:
        if key in excluded:
            continue
        manifest = version.get(key, "")
        if manifest and key in DEPOT_MAP:
            depots.append((DEPOT_MAP[key], manifest, DLC_NAMES[key], 0.3))
    return depots

# ------------------------------------------------------------------ SteamCMD
# Downloads go through SteamCMD (Valve's official CLI) instead of
# driving the Steam client console with keystrokes. The console
# automation failed repeatedly (dropped Ctrl, lost focus, wrong
# window), while steamcmd takes depot commands as plain argv.
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
# Stable home in the data dir — NOT next to the .py/exe, so it survives
# version upgrades (every new zip extracts to a fresh folder, which used
# to make the setup dialog pop up again every single version).
STEAMCMD_DIR = DATA_DIR / "steamcmd"
# v1.72.0: libtek-steamclient-2.dll lives here (downloaded on first
# TEK CM use by tek_steamclient.ensure_dll - never bundled).
TEK_DLL_DIR = DATA_DIR / "tek-steamclient"
STEAMCMD_EXE = STEAMCMD_DIR / "steamcmd.exe"

def _migrate_steamcmd():
    """One-time move from the old next-to-app location, so existing
    users don't have to re-download SteamCMD after this change."""
    try:
        old = _app_dir() / "steamcmd"
        if old.is_dir() and not STEAMCMD_DIR.is_dir():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(STEAMCMD_DIR))
    except OSError:
        pass
_migrate_steamcmd()

def steamcmd_ready():
    """True if steamcmd.exe exists in the data dir."""
    return STEAMCMD_EXE.is_file()

def steamcmd_depot_root():
    """Where steamcmd writes downloaded depots."""
    return STEAMCMD_DIR / "steamapps" / "content" / f"app_{STEAM_APP_ID}"

def setup_steamcmd(progress=None):
    """Download + extract steamcmd.zip into steamcmd/ next to the .py.
    Returns (ok, message). progress(msg) gets status lines.
    Downloads only — never touches any password or login."""
    def log(m):
        if progress:
            progress(m)
    if STEAMCMD_EXE.is_file():
        return True, "SteamCMD is already set up."
    try:
        STEAMCMD_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STEAMCMD_DIR / "steamcmd.zip"
        log("Downloading SteamCMD from Valve...")
        req = urllib.request.Request(STEAMCMD_URL, headers={"User-Agent": "LegacyARKLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        log("Extracting SteamCMD...")
        with zipfile.ZipFile(tmp) as z:
            z.extractall(STEAMCMD_DIR)
        try:
            tmp.unlink()
        except OSError:
            pass
        if STEAMCMD_EXE.is_file():
            return True, "SteamCMD is ready."
        return False, "SteamCMD download finished but steamcmd.exe is missing."
    except Exception as e:
        return False, f"Couldn't set up SteamCMD: {e}"

class _SetupSteamcmdThread(QThread):
    """Runs setup_steamcmd off the GUI thread (Settings button)."""
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def run(self):
        ok, msg = setup_steamcmd(progress=self.progress.emit)
        self.done.emit(ok, msg)

USAGE_PING_BASE = "https://legacy-ark-launcher.netlify.app/usage"
# v1.69.0: counts live in the site's Netlify analytics under "Top
# resources not found" — Web Analytics only counts 200/201/304 HTML
# responses as pageviews, but it still lists 404'd resources with their
# totals, so one ping per user per day reads as user-days per version.
def _send_usage_ping(version):
    """GET the version path; True if the server answered at all (even
    404 — the request was logged, which is the whole point). False only
    on a network failure. Sends nothing but the version in the path."""
    url = USAGE_PING_BASE.rstrip("/") + "/" + urllib.parse.quote(str(version), safe="")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LegacyARKLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=10) as _resp:
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False

PUBLIC_PING_KEY = "legacy-ark-launcher-6frizz-active-users"
PUBLIC_PING_HIT = "https://countapi.mileshilliard.com/api/v1/hit/" + PUBLIC_PING_KEY
PUBLIC_PING_GET = "https://countapi.mileshilliard.com/api/v1/get/" + PUBLIC_PING_KEY
# v1.70.0: public counter (no signup, no key; all keys/values public).
# The website's Active users now shows live presence (MQTT); PUBLIC_PING_GET remains the public daily total series.
# A first hit creates the key; a get on an unknown key 404s, which just
# means zero pings have landed yet. Public by design: anyone who knows
# the key can read the total, and anyone could inflate it — so this is
# a community counter, not an audited headcount.
def _send_public_ping():
    """GET the hit endpoint; True on any HTTP response, False only on
    a network failure. Sends no data at all — the URL itself is the
    count, and the count is a running total of daily check-ins."""
    try:
        req = urllib.request.Request(PUBLIC_PING_HIT, headers={"User-Agent": "LegacyARKLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=10) as _resp:
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False

class DownloadWorker(QThread):
    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int)  # 0-100 determinate progress
    done = pyqtSignal(bool, str)

    def __init__(self, version, excluded=None, steam_dir=None, install_root=None, username=""):
        super().__init__()
        self.version = version
        # Snapshot of DLC keys excluded at download start; never changes mid-run.
        self.excluded = set(excluded or [])
        # Snapshot of paths at download start, so a Settings change mid-run
        # can't redirect a download halfway through.
        self.steam_dir = steam_dir
        self.install_root = install_root
        # Steam username snapshot (username ONLY — the launcher never
        # asks for, stores, or handles the password).
        self.username = (username or "").strip()
        self._cancel = False
        self._proc = None

    def cancel(self):
        """Ask the worker to stop ASAP. Safe to call from the GUI thread."""
        self._cancel = True
        try:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()
        except OSError:
            pass

    def _run_steamcmd(self, depots):
        """Start ONE SteamCMD that downloads every depot sequentially.

        The commands go in as plain argv — no keystrokes, no clicking,
        no clipboard, no focus tricks. If Steam asks for a password or
        Steam Guard code (first login, or after a session expires), the
        user types it themselves in that window. The launcher NEVER
        captures, stores, types, or passes any password, and never
        pipes keystrokes into the window. No password on the command
        line, no password via stdin — only `+login <username>`.
        One window for the whole build (not one per depot), so it opens
        once, downloads everything, then quits.
        Returns the Popen object (or None if it couldn't start) — the
        caller waits on it via _watch_steamcmd, so a crash or early
        exit is detected instead of silently breaking the download."""
        args = [str(STEAMCMD_EXE), "+login", self.username]
        for depot_id, manifest, _dname, _min in depots:
            args += ["+download_depot", STEAM_APP_ID, str(depot_id), str(manifest)]
        args += ["+quit"]
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
        try:
            self._proc = subprocess.Popen(args, creationflags=flags)
            return self._proc
        except OSError as e:
            self.progress.emit(f"Couldn't start SteamCMD: {e}")
            return None

    def _prepare_depot_folders(self, depot_root, depots):
        """v1.68.0: a depot folder survives failed/cancelled downloads
        (partials are kept for resume), and SteamCMD's download_depot
        does NOT purge files from an older manifest. So a folder left
        over from another build used to inflate the progress number AND
        pollute the install with newer files. Track which manifest each
        folder holds in depot_root/.cml-depot-manifests.json (outside any
        depot folder, so it never gets copied into the game):
        - folder holds a different manifest, or no marker at all
          (pre-fix leftovers) -> delete it, log why;
        - folder holds THIS build's manifest -> keep it (resume) and
          log how much is already there, so a nonzero start reads right.
        The marker is written BEFORE SteamCMD runs, so a cancelled
        download still resumes correctly next time."""
        try:
            Path(depot_root).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        marker_file = Path(depot_root) / ".cml-depot-manifests.json"
        markers = {}
        try:
            if marker_file.is_file():
                markers = json.loads(marker_file.read_text()) or {}
                if not isinstance(markers, dict): markers = {}
        except (OSError, ValueError):
            markers = {}
        changed = False
        for depot_id, manifest, dname, _min in depots:
            folder = Path(depot_root) / f"depot_{depot_id}"
            key = str(depot_id); want = str(manifest)
            if folder.is_dir():
                have = markers.get(key)
                if have != want:
                    try:
                        size = dir_size_gb(str(folder))
                        shutil.rmtree(folder)
                        if have is None:
                            self.progress.emit(f"Cleared {size:.1f} GB of old files for {dname} (left over from before the launcher tracked downloads) — they were inflating the size and would have mixed into this build.")
                        else:
                            self.progress.emit(f"Cleared {size:.1f} GB of old files for {dname} (left over from another build) — they were inflating the size and would have mixed into this build.")
                    except OSError as e:
                        self.progress.emit(f"Couldn't clear old files for {dname}: {e}")
                else:
                    try:
                        size = dir_size_gb(str(folder))
                        if size > 0.05:
                            self.progress.emit(f"Resuming {dname}: {size:.1f} GB already downloaded for this same build.")
                    except OSError:
                        pass
            if markers.get(key) != want:
                markers[key] = want; changed = True
        if changed:
            try: marker_file.write_text(json.dumps(markers))
            except OSError: pass

    def _watch_steamcmd(self, proc, depot_root, depots):
        """Wait on a running SteamCMD download. Returns True only if the
        process finished AND every depot folder holds at least its min_gb."""
        folders = [(Path(depot_root) / f"depot_{depot_id}", dname, min_gb)
                   for depot_id, _manifest, dname, min_gb in depots]
        # Phase 1: the download must start (a depot folder appears). Fail
        # fast — 2 min of nothing with a live process means it's stuck on
        # a login prompt; an exited process means it crashed.
        for _ in range(24):
            code = proc.poll()
            if code is not None:
                self.progress.emit(f"SteamCMD closed (code {code}) before the download started.")
                return False
            if any(f.is_dir() and dir_size_gb(str(f)) > 0.05 for f, _n, _m in folders):
                break
            time.sleep(5)
        else:
            self.progress.emit("The download didn't start — if a SteamCMD window is waiting for your password or Steam Guard code, type it in there yourself, then retry.")
            try: proc.kill()
            except OSError: pass
            return False
        # Phase 2: download running — the SteamCMD window stays open
        # showing progress; wait for the process itself to finish.
        # The wait runs as short 5s polls so the log gets a live MB/s
        # readout without changing the 3h total timeout. Each poll also
        # honors cancel() and emits a determinate % (capped at 95 until
        # the install phase — the estimate is the installed size, and
        # the compressed download lands a bit under it).
        self.progress.emit("Downloading — leave the SteamCMD window open until it finishes.")
        def _total_gb():
            total = 0.0
            for f, _n, _m in folders:
                if f.is_dir():
                    total += dir_size_gb(str(f))
            return total
        try:
            total_est = max(1.0, float(_estimate_size_gb(self.version)))
        except Exception:
            total_est = 1.0
        last_size, last_t = _total_gb(), time.time()
        deadline = last_t + 3 * 3600
        code = None
        warned_big = False
        while time.time() < deadline:
            if self._cancel:
                try: proc.kill()
                except OSError: pass
                self.progress.emit("Download cancelled — partial files kept so a retry can resume.")
                return False
            try:
                code = proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.time()
            size = _total_gb()
            dt = now - last_t
            if dt > 0.1:
                mbps = max(0.0, (size - last_size) / dt * 1024.0)
                self.progress.emit(f"Downloading — {size:.1f} GB so far ({mbps:.1f} MB/s) — leave the SteamCMD window open until it finishes.")
                if not warned_big and size > total_est * 2:
                    warned_big = True
                    self.progress.emit(f"Warning: this download is already {size:.1f} GB but {self.version.get('name', '')} was estimated at ~{total_est:.0f} GB — cancel it and report the numbers, the build's download info is probably wrong.")
                try:
                    self.progress_pct.emit(min(95, int(size / total_est * 100)))
                except Exception:
                    pass
            last_size, last_t = size, now
        if self._cancel:
            self.progress.emit("Download cancelled — partial files kept so a retry can resume.")
            return False
        if code is None:
            try: proc.kill()
            except OSError: pass
            self.progress.emit("The download timed out after 3 hours.")
            return False
        if code != 0:
            self.progress.emit(f"SteamCMD exited with code {code} during the download — retrying...")
            return False
        # Phase 3: validate what actually landed. A depot that only
        # served a few MB is broken data, not a real build.
        for folder, dname, min_gb in folders:
            size = dir_size_gb(str(folder)) if folder.is_dir() else 0
            if size < min_gb:
                _extra = ""
                if dname == "Primitive+":
                    _extra = " Primitive+ is a separate free Steam DLC (app 508150) — claim it in Steam first, or exclude Primitive+ and download the rest."
                self.progress.emit(f"Steam only served {size:.2f} GB for {dname} (expected at least {min_gb} GB) — that build's download info looks broken, try another build.{_extra}")
                return False
        return True

    def run(self):
        try: self._run()
        except Exception as e: self.done.emit(False, f"Download failed: {e}")

    def _run(self):
        name = self.version.get("name", "")
        if os.name != "nt":
            self.done.emit(False, "This launcher needs Windows + Steam."); return
        if not self.username:
            self.done.emit(False, "Set your Steam username in Settings → Steam first, then hit Download again. (Username only — the launcher never asks for your password.)"); return
        if not steamcmd_ready():
            # Bootstrap on first download: fetch SteamCMD from Valve.
            self.progress.emit("SteamCMD isn't set up yet — downloading it from Valve...")
            ok, msg = setup_steamcmd(progress=self.progress.emit)
            self.progress.emit(msg)
            if not ok:
                self.done.emit(False, msg); return

        depot_root = steamcmd_depot_root()
        game_dir = (Path(self.install_root) if self.install_root else Path.home() / "CML-ARK") / slugify(name)
        depots = version_depots(self.version, self.excluded)
        # v1.68.0: wipe depot folders left over from other builds before
        # SteamCMD runs (same-build partials still resume).
        self._prepare_depot_folders(depot_root, depots)

        ok = False
        for attempt in range(1, 4):
            if self._cancel: break
            if attempt > 1: self.progress.emit(f"Retrying the SteamCMD download (attempt {attempt})...")
            # One SteamCMD window for the whole build — it stays open
            # until every depot is done. _watch_steamcmd waits on the
            # process itself, so an early close/crash is caught instead
            # of silently breaking the download.
            proc = self._run_steamcmd(depots)
            if proc is None:
                continue
            if self._watch_steamcmd(proc, depot_root, depots):
                ok = True; break
        if self._cancel:
            self.done.emit(False, "Download cancelled — partial files kept so a retry can resume."); return
        if not ok:
            # Manual fallback: the exact steamcmd command so the user
            # can run it themselves in a terminal. They type their
            # own password / Guard code if Steam asks.
            parts = " ".join(f"+download_depot {STEAM_APP_ID} {d} {m}" for d, m, _n, _g in depots)
            prim_hint = ""
            if any(d == DEPOT_MAP.get("primitive") for d, _m, _n, _g in depots):
                prim_hint = ("\n\nPrimitive+ note: Primitive+ is a separate FREE DLC in Steam (app 508150). "
                             "If you have never claimed it in Steam, SteamCMD cannot download depot 346117 even though it is free — "
                             "open Steam, find 'Primitive+ ARK Total Conversion' in the store, add the free DLC to your library, then retry.")
            self.done.emit(False, f"The download didn't finish. If a SteamCMD window asked for your password or Steam Guard code, type it in there yourself and retry. Manual: open a terminal in the launcher's steamcmd/ folder and run: steamcmd +login {self.username} {parts} +quit{prim_hint}")
            return
        self.progress.emit("Download finished.")
        self.progress_pct.emit(96)

        self.progress.emit("Installing files...")
        for depot_id, _manifest, _dname, _min in depots:
            if self._cancel:
                self.done.emit(False, "Download cancelled during install — partial files kept."); return
            src = Path(depot_root) / f"depot_{depot_id}"
            if src.is_dir(): shutil.copytree(src, game_dir, dirs_exist_ok=True)
        self.progress_pct.emit(99)
        
        exe = game_dir / "ShooterGame" / "Binaries" / "Win64" / "ShooterGame.exe"
        if not exe.is_file():
            self.done.emit(False, "Game exe not found after copying - something went wrong."); return

        # Depot builds launched outside the Steam client need
        # steam_appid.txt next to the exe or they die silently right
        # after the loading music (SteamAPI can't init). This is
        # Steam's own documented mechanism — it doesn't bypass
        # ownership; the client still verifies the user owns ARK.
        try:
            (exe.parent / "steam_appid.txt").write_text(str(STEAM_APP_ID))
        except OSError: pass

        label = f"Legacy ARK - {name}"
        _write_shortcut(label, exe)

        # The raw depot downloads stay in steamcmd's content folder after
        # copying — that's a full duplicate of every build. Clean them up
        # now that the install succeeded (a failed download keeps its
        # partial files so a retry can resume).
        freed = 0.0
        for depot_id, _manifest, _dname, _min in depots:
            dp = Path(depot_root) / f"depot_{depot_id}"
            if dp.is_dir():
                try:
                    freed += dir_size_gb(str(dp))
                    shutil.rmtree(dp)
                except OSError: pass
        if freed > 0.01:
            self.progress.emit(f"Cleaned up {freed:.1f} GB of raw download files.")
        
        self.done.emit(True, f"Done - {name} is installed.")

class _ModDownloadThread(QThread):
    """Download one Steam Workshop mod via SteamCMD, then copy it into a
    build's ShooterGame/Content/Mods/<workshop_id>/ folder. Emits
    progress(str) and done(bool, str). Mirrors DownloadWorker's safety
    rules: username only, password typed by the user in Steam's own
    window, never captured or stored."""
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, workshop_id, mod_name, game_dir, username=""):
        super().__init__()
        self.workshop_id = str(workshop_id)
        self.mod_name = mod_name
        self.game_dir = Path(game_dir)
        self.username = (username or "").strip()
        self._cancel = False
        self._proc = None

    def cancel(self):
        self._cancel = True
        try:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()
        except OSError:
            pass

    def run(self):
        try:
            self._run()
        except Exception as e:
            self.done.emit(False, f"Mod download failed: {e}")

    def _run(self):
        if os.name != "nt":
            self.done.emit(False, "This launcher needs Windows + Steam."); return
        if not self.username:
            self.done.emit(False, "Set your Steam username in Settings → Steam first. (Username only — the launcher never asks for your password.)"); return
        if not steamcmd_ready():
            self.progress.emit("SteamCMD isn't set up yet — downloading it from Valve...")
            ok, msg = setup_steamcmd(progress=self.progress.emit)
            self.progress.emit(msg)
            if not ok:
                self.done.emit(False, msg); return
        args = [str(STEAMCMD_EXE), "+login", self.username,
                "+workshop_download_item", STEAM_APP_ID, self.workshop_id,
                "+quit"]
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
        self.progress.emit(f"Downloading {self.mod_name} — leave the SteamCMD window open until it finishes.")
        try:
            self._proc = subprocess.Popen(args, creationflags=flags)
        except OSError as e:
            self.done.emit(False, f"Couldn't start SteamCMD: {e}"); return
        # Wait (up to 30 min) with cancel support.
        deadline = time.time() + 1800
        code = None
        while time.time() < deadline:
            if self._cancel:
                try: self._proc.kill()
                except OSError: pass
                self.done.emit(False, "Mod download cancelled."); return
            try:
                code = self._proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                pass
        if code is None:
            try: self._proc.kill()
            except OSError: pass
            self.done.emit(False, "The mod download timed out."); return
        if code != 0:
            self.done.emit(False, f"SteamCMD exited with code {code} — if it asked for your password or Steam Guard code, type it in there yourself and retry."); return
        src = steamcmd_depot_root().parent.parent / "workshop" / "content" / STEAM_APP_ID / self.workshop_id
        # steamcmd_depot_root() = steamcmd/steamapps/content/app_346110;
        # workshop lands at steamcmd/steamapps/workshop/content/346110/<id>
        if not src.is_dir():
            src = STEAMCMD_DIR / "steamapps" / "workshop" / "content" / STEAM_APP_ID / self.workshop_id
        if not src.is_dir():
            self.done.emit(False, "SteamCMD finished but the mod files didn't land — the Workshop item may not exist or needs a login."); return
        dest = self.game_dir / "ShooterGame" / "Content" / "Mods" / self.workshop_id
        try:
            self.progress.emit("Installing mod files...")
            if dest.is_dir():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
        except OSError as e:
            self.done.emit(False, f"Couldn't copy the mod into the build: {e}"); return
        self.done.emit(True, f"{self.mod_name} installed.")

class _BackupThread(QThread):
    """Zip a build's ShooterGame/Saved folder into the backups dir.
    Emits done(bool, str). Never touches the live Saved folder."""
    done = pyqtSignal(bool, str)

    def __init__(self, saved_dir, dest_zip):
        super().__init__()
        self.saved_dir = Path(saved_dir)
        self.dest_zip = Path(dest_zip)

    def run(self):
        try:
            if not self.saved_dir.is_dir():
                self.done.emit(False, "No Saved folder found for that build yet — play it once first.")
                return
            self.dest_zip.parent.mkdir(parents=True, exist_ok=True)
            # shutil.make_archive appends .zip itself; pass the stem.
            stem = str(self.dest_zip.with_suffix(""))
            shutil.make_archive(stem, "zip", root_dir=str(self.saved_dir.parent), base_dir=self.saved_dir.name)
            self.done.emit(True, f"Backup saved: {self.dest_zip.name}")
        except Exception as e:
            self.done.emit(False, f"Backup failed: {e}")

def _do_backup_now(store, version):
    """Synchronous Saved-folder backup used by auto-backup. Returns
    (ok, message). Never raises, never blocks a download on failure."""
    try:
        saved = _saved_dir_for(store, version)
        if saved is None or not saved.is_dir():
            return False, "no Saved folder yet"
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        dest = BACKUP_DIR / f"{slugify(version.get('name', 'build'))}_{ts}.zip"
        stem = str(dest.with_suffix(""))
        shutil.make_archive(stem, "zip", root_dir=str(saved.parent), base_dir=saved.name)
        return True, dest.name
    except Exception as e:
        return False, str(e)

class TitleBar(QWidget):
    def __init__(self, win):
        # v1.39.0 Config Editor top bar: 80px like his, logo + app name
        # left, action button at right (MainWindow inserts Play OG ARK
        # before the window controls), window controls right. Navigation
        # is NO LONGER here — it moved to the left sidebar below, like
        # his 230px sidebar. nav_widget is kept empty for compatibility
        # with code that references titlebar.nav_layout.
        super().__init__(win); self.win = win; self.setFixedHeight(80)
        h = QHBoxLayout(self); h.setContentsMargins(16, 16, 16, 16); h.setSpacing(10); self.h = h
        logo = QLabel(); logo.setPixmap(brand_pixmap(48)); logo.setFixedSize(48, 48); h.addWidget(logo)
        self.brand_text = QLabel(APP_NAME); self.brand_text.setObjectName("Brand"); self.brand_text.setMinimumWidth(0); h.addWidget(self.brand_text)
        # v1.71.3: Active users next to the title. When presence is
        # live (Usage Counting on), it shows launchers online right
        # now; otherwise it falls back to the public daily total
        # (plain GET, no data sent). MainWindow refreshes the fallback
        # (thread + 60s timer); failures show a dash, never a popup.
        self.active_users_label = QLabel("Active users: —"); self.active_users_label.setObjectName("Muted")
        self.active_users_label.setToolTip("Live total of daily check-ins from opted-in launchers.")
        h.addWidget(self.active_users_label)
        h.addSpacing(16)
        self.nav_widget = QWidget(); self.nav_layout = QHBoxLayout(self.nav_widget); self.nav_layout.setContentsMargins(0, 0, 0, 0); self.nav_layout.setSpacing(4); h.addWidget(self.nav_widget)
        h.addStretch(1)
        # v1.41.0 centered profile pill, like his centered preset pill:
        # a single dark pill with "Profile:" + the active profile name.
        # It sits between two stretches so it stays centered, not left.
        # Clicking it opens Settings (where profiles actually live).
        self.profile_pill = QFrame(); self.profile_pill.setObjectName("VersionPill"); self.profile_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        _pl = QHBoxLayout(self.profile_pill); _pl.setContentsMargins(14, 6, 14, 6); _pl.setSpacing(8)
        _plbl = QLabel("Profile:"); _plbl.setObjectName("Muted"); _pl.addWidget(_plbl)
        self.profile_name_label = QLabel("Default"); self.profile_name_label.setObjectName("RowTitle"); _pl.addWidget(self.profile_name_label)
        # Clicking the pill opens Settings (where profiles live). Lookup
        # at click time, because _nav_index does not exist yet here.
        def _pill_click(_e, _win=win):
            try: _win.show_page(_win._nav_index["Settings"])
            except Exception: pass
        self.profile_pill.mousePressEvent = _pill_click
        h.addWidget(self.profile_pill)
        h.addStretch(1)
        
        self.min_b = QPushButton(); self.min_b.setObjectName("TitleBtn"); self.min_b.setFixedSize(42, 30)
        self.min_b.setIcon(QIcon(icon("min", 12))); self.min_b.clicked.connect(win.showMinimized)
        
        self.max_b = QPushButton(); self.max_b.setObjectName("TitleBtn"); self.max_b.setFixedSize(42, 30)
        self.max_b.setIcon(QIcon(icon("expand", 12))); self.max_b.clicked.connect(win.toggle_max)
        
        self.close_b = QPushButton(); self.close_b.setObjectName("CloseBtn")
        self.close_b.setFixedSize(42, 30); self.close_b.setIcon(QIcon(icon("close", 12))); self.close_b.clicked.connect(win.close)
        
        for b in (self.min_b, self.max_b, self.close_b): b.setCursor(Qt.CursorShape.PointingHandCursor); h.addWidget(b)
        self._drag = None

    def sync_max_icon(self): self.max_b.setIcon(QIcon(icon("restore" if self.win.isMaximized() else "expand", 12)))
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self._drag = e.globalPosition().toPoint() - self.win.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._drag and not self.win.isMaximized(): self.win.move(e.globalPosition().toPoint() - self._drag)
    def mouseReleaseEvent(self, e): self._drag = None
    def mouseDoubleClickEvent(self, e): self.win.toggle_max()

class NavButton(QPushButton):
    def __init__(self, icon_name, title):
        super().__init__(); self.setObjectName("Nav"); self.icon_name = icon_name; self.title = title
        self.setCheckable(True); self.setFixedHeight(46); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(17, 17)); self.setText(title); self.toggled.connect(self._sync); self._sync(False)

    def _sync(self, on): self.setIcon(QIcon(icon(self.icon_name, 17, TEXT if on else MUTED)))
    def set_collapsed(self, on):
        self.setText("" if on else self.title)
        # Collapsed: center the icon, or it stays at the 16px left
        # padding and never lines up with the centered logo above it.
        # Expanded: clear the inline style so the QSS left alignment
        # (icon + label) comes back.
        self.setStyleSheet("text-align: center; padding: 12px 0px;" if on else "")
    def paintEvent(self, e):
        # v1.30.0: no orange left bar — the checked Nav pill in QSS
        # (rounded, subtle background) is the selection state now.
        super().paintEvent(e)

class DashboardPage(QWidget):
    """Overview + Recently Played quick-launch. Full version management
    lives on the Versions page."""

    def __init__(self, main):
        super().__init__(); self.main = main
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(32, 28, 32, 32); v.setSpacing(22)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Hero: status at a glance + primary actions.
        hero = QFrame(); hero.setObjectName("Hero")
        hh = QHBoxLayout(hero); hh.setContentsMargins(22, 20, 22, 20); hh.setSpacing(18)
        logo = QLabel(); logo.setPixmap(brand_pixmap(48)); logo.setFixedSize(48, 48)
        hh.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        hcol = QVBoxLayout(); hcol.setContentsMargins(0, 0, 0, 0); hcol.setSpacing(4)
        ht = QLabel("Ark Survival Evolved"); ht.setObjectName("HeroTitle"); hcol.addWidget(ht)
        hsub = FlowLayout(); hsub.setContentsMargins(0, 0, 0, 0); hsub.setSpacing(10)
        self.profile_label = QLabel(""); self.profile_label.setObjectName("Muted"); hsub.addWidget(self.profile_label)
        self.ver_label = QLabel(VERSION); self.ver_label.setObjectName("Muted"); hsub.addWidget(self.ver_label)
        hsub.addStretch(1)
        hcol.addLayout(hsub)
        hh.addLayout(hcol, 1)
        self.stat_labels = {}
        for key, label in [("installed", "Builds"), ("favorites", "Favorites"), ("disk", "Disk used")]:
            sc = QVBoxLayout(); sc.setContentsMargins(0, 0, 0, 0); sc.setSpacing(2)
            sc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val = QLabel("—"); val.setObjectName("HeroStat"); val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sc.addWidget(val)
            lab = QLabel(label); lab.setObjectName("Muted"); lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sc.addWidget(lab)
            hh.addLayout(sc)
            self.stat_labels[key] = val
        abox = QVBoxLayout(); abox.setContentsMargins(0, 0, 0, 0); abox.setSpacing(8)
        self.play_b = QPushButton("▶  Play OG ARK"); self.play_b.setObjectName("Primary")
        self.play_b.setMinimumHeight(40); self.play_b.clicked.connect(self._on_hero_play)
        abox.addWidget(self.play_b)
        hh.addLayout(abox)
        v.addWidget(hero)

        # v1.29.2 Dashboard mission: plain-English explanation of what
        # this is and what we are bringing back, plus one-button OG play.
        mission = QFrame(); mission.setObjectName("Card")
        ml = QVBoxLayout(mission); ml.setContentsMargins(22, 18, 22, 18); ml.setSpacing(10)
        mt = QLabel("Old ARK is back"); mt.setObjectName("CardHead"); ml.addWidget(mt)
        m1 = QLabel("What is this? This launcher brings back old ARK — classic ARK: Survival Evolved builds from 2015 to 2024, starting with The Island at launch and including Scorched Earth, Ragnarok, Aberration, Extinction, Valguero, Genesis, and more. Not just 2015, and not modern Ascended. Download any old build here, hit Play, and you are playing ARK the way it was.")
        m1.setObjectName("Muted"); m1.setWordWrap(True); ml.addWidget(m1)
        m2 = QLabel("What we are bringing back: old-school taming, building, and PvP, across every old era — not just one year. Host your own old-ARK server from the Host tab, or play solo. The goal is simple: old ARK, playable again, for everyone who misses it.")
        m2.setObjectName("Muted"); m2.setWordWrap(True); ml.addWidget(m2)
        m3 = QLabel("How to play, in 3 steps: 1) Pick any old build on Versions, 2015 to 2024. 2) Hit Download (one time, it is a big game). 3) Hit Play OG ARK at the top. That is it.")
        m3.setObjectName("Muted"); m3.setWordWrap(True); ml.addWidget(m3)
        mrow = FlowLayout(); mrow.setSpacing(10)
        # v1.34.0: no more duplicate "Play OG ARK" here — hero at the
        # top already has it. Mission card keeps only Browse, so
        # Play OG ARK appears once on Dashboard (hero), not twice.
        self.browse_og_b = QPushButton("Browse old builds"); self.browse_og_b.clicked.connect(self._browse_og_ark); mrow.addWidget(self.browse_og_b)
        mrow.addStretch(1); ml.addLayout(mrow)
        v.addWidget(mission)

        # v1.31.0 new home layout: 3 large action tiles, not just a
        # button row buried in text. Play / Browse / Host, one tap each.
        tiles = FlowLayout(); tiles.setSpacing(14)
        for _title, _sub, _short, _fn in [
            ("Play old ARK", "Launch an installed old build, one tap.", "Play", self._on_hero_play),
            ("Browse old builds", "All 97 old builds, 2015 to 2024, with search and filters.", "Browse", self._browse_og_ark),
            ("Host a server", "Turn an installed build into a dedicated server for friends.", "Host", lambda: self.main.show_page(self.main._nav_index["Host"])),
        ]:
            _card = QFrame(); _card.setObjectName("Card")
            _cl = QVBoxLayout(_card); _cl.setContentsMargins(18, 16, 18, 16); _cl.setSpacing(6)
            _tt = QLabel(_title); _tt.setObjectName("CardHead"); _cl.addWidget(_tt)
            _ss = QLabel(_sub); _ss.setObjectName("Muted"); _ss.setWordWrap(True); _cl.addWidget(_ss)
            # v1.44.0: short button text ("Play", not "Play old ARK") — the tile title already
            # says the full thing, and the short button fits narrow tiles instead of clipping.
            _bb = QPushButton(_short); _bb.setObjectName("Primary"); _bb.setMinimumHeight(40); _bb.clicked.connect(_fn); _cl.addWidget(_bb, 0, Qt.AlignmentFlag.AlignLeft)
            tiles.addWidget(_card, 1)
        v.addLayout(tiles)

        # Recently played — one-click Play for your last 3 builds.
        v.addWidget(self._header("RECENTLY PLAYED"))
        self.recent_box = QVBoxLayout(); self.recent_box.setSpacing(10)
        v.addLayout(self.recent_box)

        # Installed builds (click one to open it on Versions)
        v.addWidget(self._header("INSTALLED BUILDS"))
        self.builds_box = QVBoxLayout(); self.builds_box.setSpacing(10)
        v.addLayout(self.builds_box)


        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)

    @staticmethod
    def _header(title):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(2, 10, 2, 2); h.setSpacing(12)
        t = QLabel(title.title().replace("Dlc", "DLC")); t.setObjectName("SectionHeader"); h.addWidget(t); h.addWidget(hair(), 1); return w

    def _on_hero_play(self):
        """Play OG ARK, easy path: most-recently-played installed
        old build, else first installed old build, else open Versions
        showing all old builds."""
        try:
            store = self.main.store
            versions = getattr(self.main.versions, "versions", []) or []
            by_name = {v.get("name", ""): v for v in versions}
            steam = steam_dir_for(store)
            def _installed(v):
                try:
                    exe = game_exe_for(steam, v, store)
                    return bool(exe and Path(exe).is_file())
                except Exception:
                    return False
            # v1.30.0: not 2015-only — any old build counts. Recent first.
            for name in (store.get("recently_played", []) or []):
                v = by_name.get(name)
                if v and _installed(v):
                    self.main.versions.play_version(v); return
            self._browse_og_ark()
        except Exception:
            pass

    def _browse_og_ark(self):
        """Open Versions showing all old builds (Era: All, not 2015 only)."""
        try:
            self.main.show_page(self.main._nav_index["Versions"])
            vp = self.main.versions
            if hasattr(vp, "era_combo"):
                vp.era_combo.setCurrentText("Era: All")
            vp._reflow_grid(force=True)
        except Exception:
            pass

    def _open_version(self, v):
        self.main.versions._select_version(v)
        self.main.show_page(1)

    def refresh(self):
        store = self.main.store
        self.profile_label.setText(f"Profile: {store.get('active_profile', 'Default')}")
        versions = getattr(self.main.versions, "versions", [])
        steam = steam_dir_for(store)
        installed = []
        total_gb = 0.0
        for v in versions:
            exe = game_exe_for(steam, v, store)
            if exe and Path(exe).is_file():
                name = v.get("name", "")
                # Cached size only — measuring walks tens of GB and must
                # never run on the UI thread (it froze every click).
                size = _SIZE_CACHE.get(name, 0.0)
                installed.append((v, size))
                total_gb += size
        # Kick off a background measurement so real numbers fill in.
        try:
            self.main.versions._measure_sizes()
        except Exception:
            pass
        self.stat_labels["installed"].setText(str(len(installed)))
        favs = store.get("favorites", [])
        self.stat_labels["favorites"].setText(str(len(favs) if isinstance(favs, list) else 0))
        self.stat_labels["disk"].setText(f"{total_gb:.1f} GB")

        while self.builds_box.count():
            item = self.builds_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        # Recently played row (max 3, only ones still installed).
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        recent = store.get("recently_played", []) or []
        by_name = {v.get("name", ""): v for v in versions}
        shown = 0
        for name in recent:
            v = by_name.get(name)
            if not v: continue
            exe = game_exe_for(steam, v, store)
            if not exe or not Path(exe).is_file(): continue
            row = QFrame(); row.setObjectName("Card")
            h = FlowLayout(row); h.setContentsMargins(16, 10, 16, 10); h.setSpacing(12)
            lab = QLabel(name); lab.setObjectName("RowTitle"); h.addWidget(lab, 1)
            pb = QPushButton("Play"); pb.setObjectName("Primary")
            pb.clicked.connect(lambda _c=False, _v=v: self.main.versions.play_version(_v))
            h.addWidget(pb)
            self.recent_box.addWidget(row)
            shown += 1
            if shown >= 3: break
        if shown == 0:
            hint = QLabel("Nothing yet — hit Play on a build and it'll show up here."); hint.setObjectName("Muted")
            self.recent_box.addWidget(hint)
        if not installed:
            steps = QFrame(); steps.setObjectName("Card")
            sl = QVBoxLayout(steps); sl.setContentsMargins(18, 16, 18, 16); sl.setSpacing(10)
            st = QLabel("Get started in 3 steps:"); st.setObjectName("RowTitle"); sl.addWidget(st)
            for i, txt in [("1", "Pick any old build on the Versions tab — 2015 to 2024, all of them are old ARK."),
                           ("2", "Hit Download and wait (it's a big game, one time)."),
                           ("3", "Hit Play. That's it — you're in old-school ARK.")]:
                row = FlowLayout(); row.setSpacing(10)
                num = QLabel(i); num.setStyleSheet(f"color: {GOLD}; font-weight: 700; font-size: 14px;")
                row.addWidget(num)
                lab = QLabel(txt); lab.setObjectName("Muted"); lab.setWordWrap(True); row.addWidget(lab, 1)
                sl.addLayout(row)
            go_b = QPushButton("Browse versions"); go_b.setObjectName("Primary")
            go_b.clicked.connect(lambda: self.main.show_page(1))
            sl.addWidget(go_b, 0, Qt.AlignmentFlag.AlignLeft)
            self.builds_box.addWidget(steps)
            return
        descs = getattr(self.main.versions, "descriptions", {}) or {}
        for v, size in installed:
            name = v.get("name", "Unnamed build")
            entry = descs.get(name, {}) if isinstance(descs, dict) else {}
            title = entry.get("title", "") if isinstance(entry, dict) else ""
            row = ClickableCard(); row.setObjectName("Card")
            h = QHBoxLayout(row); h.setContentsMargins(16, 12, 16, 12); h.setSpacing(12)
            col = QVBoxLayout(); col.setSpacing(2)
            t = QLabel(title or name); t.setObjectName("RowTitle"); col.addWidget(t)
            s = QLabel(name); s.setObjectName("Muted"); col.addWidget(s)
            h.addLayout(col, 1)
            sz = QLabel(f"{size:.1f} GB"); sz.setObjectName("Muted"); h.addWidget(sz)
            go = QLabel("Open →"); go.setStyleSheet(f"color: {GOLD}; font-weight: 700;"); h.addWidget(go)
            row.clicked.connect(lambda vv=v: self._open_version(vv))
            self.builds_box.addWidget(row)

class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__(); self.main = main; self.store = main.store
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(28, 24, 28, 28); v.setSpacing(14); v.setAlignment(Qt.AlignmentFlag.AlignTop)

        v.addWidget(page_header("Settings", "Tune the launcher to your liking. Every row below explains what it does in plain English — read the small text under each name. A green toggle is ON, a grey toggle is OFF. Most changes apply instantly; nothing here deletes a build unless the row says Delete."))
        # v1.47.0 guide card (user: most Settings things were missing info).
        # Plain-English, step-by-step: what Settings is, how toggles work,
        # where settings are saved, and how to undo a bad change.
        _guide = QFrame(); _guide.setObjectName("Card")
        _gv = QVBoxLayout(_guide); _gv.setContentsMargins(18, 16, 18, 16); _gv.setSpacing(8)
        _gt = QLabel("How to use Settings — read this first"); _gt.setObjectName("RowTitle"); _gv.addWidget(_gt)
        for _line in [
            "1) Find what you want to change, read the small text under its name, then flip the toggle or type in the box. Your change saves itself right away — you do not need a Save button.",
            "2) Green toggle = ON, grey toggle = OFF. Example: green Always on Top means the launcher stays above other windows; grey means it behaves normally.",
            "3) If something looks wrong after a change, flip that toggle back, or use Restart, or at the bottom use Clear Settings to put everything back to the defaults. Clear Settings does NOT delete your downloaded ARK builds.",
            "4) Your settings live in a file on your PC (~/.cml-launcher/settings.json). Export Settings makes a backup copy you can keep; Import Settings loads one back.",
        ]:
            _gl = QLabel(_line); _gl.setObjectName("Muted"); _gl.setWordWrap(True); _gv.addWidget(_gl)
        v.addWidget(_guide)
        v.addWidget(self._header("GAME LAUNCH"))
        _sg = QLabel("These are the things used when you hit Play. Player Profile = who you are in-game and which build you prefer. Default Launch Arguments = extra commands added to the game every time you launch — leave it alone unless a guide tells you to add something."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        # Player profiles: switcher + CRUD. Switching applies the profile's
        # preferred build + launch args.
        prof_lay = FlowLayout(); prof_lay.setContentsMargins(0, 0, 0, 0); prof_lay.setSpacing(8)
        self.profile_combo = QComboBox(); self.profile_combo.setMinimumWidth(150)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_switched)
        prof_lay.addWidget(self.profile_combo, 1)
        new_b = QPushButton("New"); new_b.clicked.connect(self._on_profile_new); prof_lay.addWidget(new_b)
        ren_b = QPushButton("Rename"); ren_b.clicked.connect(self._on_profile_rename); prof_lay.addWidget(ren_b)
        del_b = QPushButton("Delete"); del_b.setObjectName("Danger"); del_b.setMinimumHeight(40); del_b.clicked.connect(self._on_profile_delete); prof_lay.addWidget(del_b)
        v.addWidget(self._row("Player Profile", "A profile is a saved set of your choices: your in-game player name, your preferred ARK build, your launch arguments, and your host preset. Use the dropdown to switch profiles — switching instantly applies that profile's build and arguments, so you do not have to retype them every time. Most players only need the Default profile.", prof_lay))
        self.args_input = QLineEdit()
        self.args_input.setPlaceholderText("-useallavailablecores -sm4 -log (Space separated)")
        self.args_input.setText(self.store.get("launch_args", ""))
        self.args_input.textChanged.connect(lambda t: self.store.set("launch_args", t))
        v.addWidget(self._row("Default Launch Arguments", "Added to the game automatically every time you hit Play. Example: -lowmemory or -nomansky. Leave it empty for normal play — most players never need to change this, and a wrong argument can stop the game starting.", self.args_input))

        # v1.60 Discord Rich Presence, restored (see functions above).
        # Toggle OFF by default — turn it on here, then hit Test. Test
        # shows the exact failure reason, it never silently does nothing.
        v.addWidget(self._header("DISCORD"))
        _sg = QLabel("Discord Rich Presence shows Legacy ARK Launcher + the build you are playing as your Discord status. This needs the Discord desktop app open on your PC, and pypresence installed (build-exe.bat and start-launcher.bat install it). To show a logo instead of Discord's \"?\" placeholder next to the status: go to discord.com/developers/applications, open the Legacy ARK Launcher app, upload logo.png as the App Icon AND as a Rich Presence Art Asset named exactly \"logo\" — the code already sends large_image=\"logo\", but Discord can only show it after you upload that asset. If you have a different custom logo, send it to Muse and he will swap logo.png/logo.ico to it. The JOIN DISCORD button at the top is separate — that is just a link to join the community, it is not presence."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        self.discord_t = ToggleSwitch(bool(self.store.get("discord_rich_presence")))
        self.discord_t.toggled.connect(self._on_discord_toggled)
        self.discord_hint = QLabel(""); self.discord_hint.setObjectName("Muted"); self.discord_hint.setWordWrap(True)
        disc_lay = QVBoxLayout(); disc_lay.setContentsMargins(0, 0, 0, 0); disc_lay.setSpacing(6)
        disc_lay.addWidget(self.discord_t); disc_lay.addWidget(self.discord_hint)
        v.addWidget(self._row("Rich Presence", "Show Legacy ARK Launcher + the build you are playing as your Discord status. OFF by default — turn it on, then hit Test below to prove it works before you trust it.", disc_lay))
        self.discord_id_input = QLineEdit(); self.discord_id_input.setPlaceholderText("Discord Application ID")
        self.discord_id_input.setText(self.store.get("discord_client_id", ""))
        self.discord_id_input.textChanged.connect(lambda t: self.store.set("discord_client_id", t.strip()))
        id_lay = QHBoxLayout(); id_lay.setContentsMargins(0, 0, 0, 0); id_lay.setSpacing(8)
        id_lay.addWidget(self.discord_id_input, 1)
        test_b = QPushButton("Test"); test_b.clicked.connect(self._on_discord_test); id_lay.addWidget(test_b)
        v.addWidget(self._row("Discord Client ID", "From your app at discord.com/developers/applications (named Legacy ARK Launcher). Pre-filled with the old app ID — change it only if you made a new app, or if Test says the ID looks wrong.", id_lay))
        self._sync_discord_hint()

        v.addWidget(self._header("STEAM"))
        _sg = QLabel("Steam is how the launcher downloads old ARK builds. Steam Folder = where Steam itself is installed. Install Location = where your old builds get saved. Steam Username = your Steam login name only — never type your password here, SteamCMD asks for that itself in its own window when it downloads."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        self.steam_input = QLineEdit(); self.steam_input.setPlaceholderText("Leave blank to auto-detect")
        self.steam_input.setText(self.store.get("steam_path", ""))
        self.steam_input.textChanged.connect(lambda t: self.store.set("steam_path", t))
        v.addWidget(self._row("Steam Folder", "Where Steam itself is installed on your PC (the folder with steam.exe in it). Leave it blank and the launcher finds Steam by itself. Only fill this in if the launcher cannot find Steam on its own.", self._path_control(self.steam_input, "steam_path")))
        self.steam_resolved = QLabel(""); self.steam_resolved.setObjectName("Muted"); self.steam_resolved.setWordWrap(True)
        v.addWidget(self.steam_resolved)
        self.steam_library_label = QLabel(""); self.steam_library_label.setObjectName("Muted"); self.steam_library_label.setWordWrap(True)
        v.addWidget(self.steam_library_label)

        self.install_input = QLineEdit(); self.install_input.setPlaceholderText("Leave blank for Steam's CML-ARK folder")
        self.install_input.setText(self.store.get("install_dir", ""))
        self.install_input.textChanged.connect(lambda t: self.store.set("install_dir", t))
        v.addWidget(self._row("Install Location", "Where your old ARK builds get downloaded to. Leave it blank and they go into the default Steam folder. Fill this in only if you want builds on a different drive or folder with more space.", self._path_control(self.install_input, "install_dir")))
        self.install_resolved = QLabel(""); self.install_resolved.setObjectName("Muted"); self.install_resolved.setWordWrap(True)
        v.addWidget(self.install_resolved)

        self.steam_user_input = QLineEdit(); self.steam_user_input.setPlaceholderText("Your Steam account name")
        self.steam_user_input.setText(self.store.get("steam_username", ""))
        self.steam_user_input.textChanged.connect(lambda t: self.store.set("steam_username", t.strip()))
        v.addWidget(self._row("Steam Username", "Your Steam login name only — the name you type to sign into Steam. NEVER type your password here. SteamCMD, Valve's download tool, asks for your password and Steam Guard code itself in its own window when it downloads a build you own.", self.steam_user_input))

        self.steamcmd_status = QLabel(""); self.steamcmd_status.setObjectName("Muted"); self.steamcmd_status.setWordWrap(True)
        sc_lay = FlowLayout(); sc_lay.setContentsMargins(0, 0, 0, 0); sc_lay.setSpacing(8)
        sc_lay.addWidget(self.steamcmd_status, 1)
        sc_b = QPushButton("Set up SteamCMD"); sc_b.clicked.connect(self._setup_steamcmd)
        sc_lay.addWidget(sc_b)
        cache_b = QPushButton("Clear download cache"); cache_b.clicked.connect(self._clear_steamcmd_cache)
        sc_lay.addWidget(cache_b)
        v.addWidget(self._row("SteamCMD", "SteamCMD is Valve's official tool for downloading games from Steam — it is what actually downloads old ARK builds for you. The launcher downloads SteamCMD once into a steamcmd/ folder next to the app, and you never need to run it yourself. Raw, unfinished downloads pile up under steamcmd/steamapps/content — Tools > Clear download cache wipes those unfinished files only, your finished installed builds are untouched.", sc_lay))



        v.addWidget(self._header("APPEARANCE"))
        _sg = QLabel("How the launcher looks. Theme recolors everything instantly. Custom Background = your own photo behind the launcher; leave it blank to keep the ARK dino photo. Background Opacity = how bright that photo is — higher means the photo shows more, lower means it is dimmer and text is easier to read."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        self.bg_input = QLineEdit(); self.bg_input.setPlaceholderText("Path to an image file...")
        self.bg_input.setText(self.store.get("custom_background", ""))
        self.bg_input.textChanged.connect(self._on_bg_changed)
        bg_lay = FlowLayout(); bg_lay.setContentsMargins(0, 0, 0, 0); bg_lay.setSpacing(8)
        bg_lay.addWidget(self.bg_input, 1)
        bg_b = QPushButton("Browse"); bg_b.clicked.connect(self._browse_background)
        bg_lay.addWidget(bg_b)
        v.addWidget(self._row("Custom Background", "Pick your own photo to show behind the launcher. Leave this blank to keep the default ARK dino photo (the one in art/ark-background.png). Use the Browse button to pick a picture from your PC. Opacity (below) controls how bright it is: 100% is the normal dimmed-photo look, 0% turns the photo off completely for a plain dark background.", bg_lay))

        self.bg_opacity = QSlider(Qt.Orientation.Horizontal); self.bg_opacity.setRange(0, 100)
        self.bg_opacity.setValue(int(float(self.store.get("background_opacity", 1.0)) * 100))
        self.bg_opacity.valueChanged.connect(self._on_bg_opacity)
        self.bg_opacity_label = QLabel(""); self.bg_opacity_label.setObjectName("Muted")
        op_lay = FlowLayout(); op_lay.setContentsMargins(0, 0, 0, 0); op_lay.setSpacing(8)
        op_lay.addWidget(self.bg_opacity, 1); op_lay.addWidget(self.bg_opacity_label)
        v.addWidget(self._row("Background Opacity", "How bright the background photo is. Higher (toward 100%) = photo shows more, like the original look. Lower = photo is dimmer and the text on top is easier to read. 100% is the normal look.", op_lay))
        self._sync_bg_opacity_label()

        # ---- theme ----
        theme_lay = FlowLayout(); theme_lay.setContentsMargins(0, 0, 0, 0); theme_lay.setSpacing(8)
        self.theme_combo = QComboBox()
        # v1.62: only Ember + Custom, always — Custom is available even
        # if no custom accent has been picked yet (Pick color... below
        # creates it). Old saved themes are migrated to Ember in main(),
        # and if one somehow slips through here, it falls back to Ember
        # instead of showing a blank selection.
        for key, t in THEMES.items():
            self.theme_combo.addItem(t["name"], key)
        self.theme_combo.addItem("Custom", "custom")
        cur = self.store.get("theme", "ember")
        if cur not in ("ember", "custom"):
            cur = "ember"; self.store.set("theme", cur)
        idx = self.theme_combo.findData(cur)
        if idx >= 0: self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_lay.addWidget(self.theme_combo, 1)
        custom_b = QPushButton("Pick color..."); custom_b.clicked.connect(self._on_custom_color)
        theme_lay.addWidget(custom_b)
        v.addWidget(self._row("Theme", "Recolor the whole launcher — background, buttons, and accents. It changes right away when you pick a theme, you do not need to restart. Pick the one that is easiest for you to read.", theme_lay))

        v.addWidget(self._header("DEFAULT DLC EXCLUSIONS"))
        _sg = QLabel("These toggles are the default DLC list for builds you have not customized yet. Turning a DLC off here means new downloads will NOT include that map by default. To change one single build, go to Versions, pick that build, and toggle its own DLC list there — that build then keeps its own list."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        sub = QLabel("Applies to builds you haven't customized. Toggling a DLC on the Versions tab saves that build's own list."); sub.setObjectName("Muted"); sub.setWordWrap(True)
        v.addWidget(sub)
        dlc_frame = QFrame(); dlc_frame.setObjectName("Card")
        dg = FlowLayout(dlc_frame); dg.setContentsMargins(16, 12, 16, 12); dg.setSpacing(8)
        self.dlc_checks = {}
        for i, key in enumerate([k for k in DLC_ORDER if k != "aquatica"]):
            cb = QCheckBox(DLC_NAMES[key])
            cb.setChecked(key in (self.store.get("default_dlc_excluded", []) or []))
            cb.toggled.connect(lambda on, k=key: self._toggle_default_dlc(k, on))
            self.dlc_checks[key] = cb
            dg.addWidget(cb)
        v.addWidget(dlc_frame)

        v.addWidget(self._header("APP"))
        _sg = QLabel("How the launcher itself behaves. Read each row: green = ON, grey = OFF. None of these change your ARK builds, they only change the launcher window, the cards, and what confirmations pop up."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        self.top_t = ToggleSwitch(bool(self.store.get("always_on_top")))
        self.top_t.toggled.connect(lambda on: (self.store.set("always_on_top", on), main.apply_always_on_top()))
        v.addWidget(self._row("Always on Top", "ON (green): the launcher window stays on top of other windows, even when you click another app. OFF (grey): it behaves like a normal window and other windows can cover it. Turn it on if you want to watch downloads while doing something else.", self.top_t))

        self.tray_t = ToggleSwitch(bool(self.store.get("minimize_to_tray")))
        self.tray_t.toggled.connect(self._on_tray_toggled)
        v.addWidget(self._row("Minimize to Tray", "ON: clicking the X always hides the launcher to the little icons by the clock (system tray) instead of quitting, so downloads keep going. OFF: clicking X quits — UNLESS a download is running, then it hides to tray until that download finishes, so closing mid-download does not break the install. Right-click the tray icon to Show it again, or Quit to cancel a download (partial files are kept, so you can resume by hitting Download again).", self.tray_t))

        self.startup_combo = QComboBox()
        for tab in ["Dashboard", "Versions", "Mods", "Host", "Backups", "Help", "Settings", "Tools"]:
            self.startup_combo.addItem(tab, tab)
        cur_tab = (self.store.get("startup_tab", "") or "").strip() or "Dashboard"
        idx = self.startup_combo.findData(cur_tab)
        if idx >= 0: self.startup_combo.setCurrentIndex(idx)
        self.startup_combo.currentIndexChanged.connect(lambda: self.store.set("startup_tab", self.startup_combo.currentData()))
        v.addWidget(self._row("Startup Tab", "Which tab you land on when the launcher opens. Example: pick Dashboard to see your builds first, or Versions to go straight to downloading. This only changes the first tab you see, it does not change anything else.", self.startup_combo))

        self.est_t = ToggleSwitch(bool(self.store.get("show_estimates", True)))
        self.est_t.toggled.connect(lambda on: self.store.set("show_estimates", on))
        v.addWidget(self._row("Show Size Estimates", "ON: each version card shows roughly how big that build is (like ~15 GB) before you download it, so you know how much space you need. OFF: those size numbers are hidden and the cards look cleaner.", self.est_t))
        self.conf_t = ToggleSwitch(bool(self.store.get("confirm_delete", True)))
        self.conf_t.toggled.connect(lambda on: self.store.set("confirm_delete", on))
        v.addWidget(self._row("Confirm Before Delete", "ON (recommended): the launcher asks Are you sure? before it deletes a build, so a misclick cannot wipe a big download. OFF: deleting happens immediately with no second chance — only turn this off if you delete builds a lot and are sure every time.", self.conf_t))
        self.tabref_t = ToggleSwitch(bool(self.store.get("refresh_on_tab", True)))
        self.tabref_t.toggled.connect(lambda on: self.store.set("refresh_on_tab", on))
        v.addWidget(self._row("Refresh On Tab Switch", "ON: every time you switch tabs, that tab re-checks what is installed and downloaded, so it is always up to date. OFF: tabs switch faster, but a tab might show old info until you refresh it yourself.", self.tabref_t))
        self.dino_t = ToggleSwitch(bool(self.store.get("show_dino_play", True)))
        self.dino_t.toggled.connect(lambda on: self.store.set("show_dino_play", on))
        v.addWidget(self._row("Show Dino Play Button", "ON: while a build is downloading, a little Dino Runner game button appears so you have something to play while you wait. OFF: no game button during downloads. This is just for fun, it does not change downloads.", self.dino_t))
        self.carddates_t = ToggleSwitch(bool(self.store.get("show_card_dates", True)))
        self.carddates_t.toggled.connect(lambda on: (self.store.set("show_card_dates", on), main.versions._populate()))
        v.addWidget(self._row("Show Card Dates", "ON: each version card shows its date (like Jun 2015) under the name, so you can tell builds apart at a glance. OFF: the date line is hidden and cards are a bit shorter.", self.carddates_t))
        self.compact_t = ToggleSwitch(bool(self.store.get("compact_cards", False)))
        self.compact_t.toggled.connect(lambda on: (self.store.set("compact_cards", on), main.versions._populate()))
        v.addWidget(self._row("Compact Cards", "ON: version cards get shorter banners (80 pixels tall instead of 120), so more cards fit on screen at once. OFF: cards keep their full tall banners with more art showing.", self.compact_t))
        self.hideinst_t = ToggleSwitch(bool(self.store.get("hide_installed_badge", False)))
        self.hideinst_t.toggled.connect(lambda on: (self.store.set("hide_installed_badge", on), main.versions._populate()))
        v.addWidget(self._row("Hide Installed Badge", "ON: the little Installed badge is hidden, even on builds you already have. OFF (normal): installed builds show an Installed badge so you can see at a glance which ones you do not need to download again.", self.hideinst_t))
        self.confq_t = ToggleSwitch(bool(self.store.get("confirm_before_queue", False)))
        self.confq_t.toggled.connect(lambda on: self.store.set("confirm_before_queue", on))
        v.addWidget(self._row("Confirm Before Queue", "ON: the launcher asks Are you sure? before it adds a build to the download queue. OFF: clicking Download queues it straight away. Keep it ON if you sometimes click Download by accident.", self.confq_t))
        self.autosel_t = ToggleSwitch(bool(self.store.get("auto_select_first_build", True)))
        self.autosel_t.toggled.connect(lambda on: self.store.set("auto_select_first_build", on))
        v.addWidget(self._row("Auto-Select First Build", "ON: when the launcher opens, it automatically selects the first build in the list, so Play and Download are ready right away. OFF: nothing is selected until you click a build yourself.", self.autosel_t))
        self.remember_t = ToggleSwitch(bool(self.store.get("remember_last_tab", False)))
        self.remember_t.toggled.connect(lambda on: self.store.set("remember_last_tab", on))
        v.addWidget(self._row("Remember Last Tab", "ON: when you reopen the launcher, it goes back to the tab you were last on (for example Settings, if you closed it there). OFF: it always opens on the Startup Tab you picked above, no matter where you were last time.", self.remember_t))
        self.maxstart_t = ToggleSwitch(bool(self.store.get("start_maximized", False)))
        self.maxstart_t.toggled.connect(lambda on: self.store.set("start_maximized", on))
        v.addWidget(self._row("Start Maximized", "ON: the launcher opens filling your whole screen (maximized). OFF: it opens at its normal window size. Maximized is best if you want to see as many builds as possible at once.", self.maxstart_t))
        self.toolhint_t = ToggleSwitch(bool(self.store.get("show_tool_hints", True)))
        self.toolhint_t.toggled.connect(lambda on: self.store.set("show_tool_hints", on))
        v.addWidget(self._row("Show Tools Hints", "ON: the Tools tab shows a short tip line at the top explaining what Tools does. OFF: that tip line is hidden. Tools itself still works either way.", self.toolhint_t))
        self.statusontab_t = ToggleSwitch(bool(self.store.get("show_status_on_tab", True)))
        self.statusontab_t.toggled.connect(lambda on: self.store.set("show_status_on_tab", on))
        v.addWidget(self._row("Show Status On Tab Switch", "ON: the little status line at the bottom updates every time you switch tabs, telling you what that tab is for. OFF: the status line stays as it was and does not change on tab switches.", self.statusontab_t))
        win_b = QPushButton("Reset window size"); win_b.clicked.connect(lambda: main.reset_window_size())
        v.addWidget(self._row("Reset Window Size", "Restores the launcher to its starting size (1360x860, or smaller if your monitor is small). The window can grow bigger from there, but it cannot shrink below its starting size — that stops rows and labels breaking when the window gets too small.", win_b))
        res = QPushButton("Restart"); res.clicked.connect(main.restart_app)
        v.addWidget(self._row("Restart App", "Closes the launcher and opens it again. Use this after changing a setting that says it needs a restart, or if the launcher looks stuck. Your downloads and builds are not affected by restarting the launcher.", res))

        v.addWidget(self._header("UPDATE"))
        _sg = QLabel("Check for a newer version of this launcher. The Update Check URL is only needed if you host your own version file — leave it empty and the check is simply off. It never updates ARK itself, only the launcher app."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        upd = QFrame(); upd.setObjectName("Card"); uh = QHBoxLayout(upd); uh.setContentsMargins(16, 12, 16, 12); uh.setSpacing(14)
        uv = QVBoxLayout(); uv.setSpacing(2)
        ut = QLabel(f"{APP_NAME} {VERSION}"); ut.setObjectName("RowTitle"); uv.addWidget(ut)
        us = QLabel("Check for a newer launcher build."); us.setObjectName("Muted"); us.setWordWrap(True); uv.addWidget(us)
        uh.addLayout(uv, 1)
        ub = QPushButton("Check for updates"); ub.clicked.connect(self._check_updates)
        uh.addWidget(ub)
        v.addWidget(upd)
        self.update_url = QLineEdit()
        self.update_url.setPlaceholderText("https://your-site.com/launcher/version.json")
        self.update_url.setText(self.store.get("update_url", ""))
        self.update_url.textChanged.connect(lambda t: self.store.set("update_url", t.strip()))
        v.addWidget(self._row("Update Check URL",
            "Advanced, leave empty unless you host your own launcher updates. If you fill it in, it must be a link to a version.json file with a version, a download url, and notes. Empty = no update check at all, which is fine for normal use. This never updates ARK itself, only the launcher app.",
            self.update_url))
        self.update_status = QLabel(""); self.update_status.setObjectName("Muted"); self.update_status.setWordWrap(True)
        v.addWidget(self.update_status)

        v.addWidget(self._header("USAGE COUNTING"))
        _sg = QLabel("Off by default. When on, the launcher sends one anonymous ping per day containing only the launcher version — no Steam username, no game data, nothing that identifies you. Counts show up in the site's Netlify analytics (per version) and as a public daily total. While the launcher is open it also holds a live presence mark (an anonymous install ID only), so the website's Active users shows launchers online right now — closing the launcher clears it within seconds, and a crash clears it too. The public total is just a number, and anyone who finds the counter address could inflate it, so treat it as a community counter, not an exact headcount. Turn it off any time and the pings stop."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        self.usage_ping_cb = QCheckBox("Help count launcher users (anonymous, version only)")
        self.usage_ping_cb.setChecked(bool(self.store.get("usage_ping")))
        def _on_usage_ping(checked):
            self.store.set("usage_ping", bool(checked))
            if checked:
                try: main._maybe_usage_ping()
                except Exception: pass
            try: main._update_presence()
            except Exception: pass
        self.usage_ping_cb.toggled.connect(_on_usage_ping)
        v.addWidget(self.usage_ping_cb)

        v.addWidget(self._header("DATA"))
        _sg = QLabel("Back up, move, or wipe your launcher settings. Export saves a copy of all your settings to a file you pick. Import loads one back. Clear Settings puts every setting back to the defaults — it does NOT delete your downloaded ARK builds, but it does forget favorites, paths, and launch arguments, so export first if you are not sure."); _sg.setObjectName("Muted"); _sg.setWordWrap(True); v.addWidget(_sg)
        self.delete_combo = QComboBox()
        del_lay = FlowLayout(); del_lay.setContentsMargins(0, 0, 0, 0); del_lay.setSpacing(8)
        del_lay.addWidget(self.delete_combo, 1)
        del_b = QPushButton("Delete build"); del_b.setObjectName("Danger"); del_b.setMinimumHeight(40); del_b.clicked.connect(self._delete_build)
        del_lay.addWidget(del_b)
        v.addWidget(self._row("Delete a Build", "Deletes one build you pick, permanently, including its whole folder — that download is gone and you would need to download it again. The launcher will ask you to confirm first (unless you turned Confirm Before Delete OFF above), so do not pick this unless you are sure.", del_lay))

        exp_b = QPushButton("Export settings"); exp_b.clicked.connect(self._export_settings)
        v.addWidget(self._row("Export Settings", "Makes a backup copy of ALL your launcher settings (profiles, paths, launch arguments, toggles) as one file you pick. Keep that file somewhere safe — if you ever need to reset, Import Settings can load it back.", exp_b))
        imp_b = QPushButton("Import settings"); imp_b.clicked.connect(self._import_settings)
        v.addWidget(self._row("Import Settings", "Loads a settings file you saved with Export Settings. Only settings the launcher recognizes are applied, anything else is ignored, so a bad file cannot break the launcher. Your ARK builds are not touched.", imp_b))
        clear_b = QPushButton("Clear settings"); clear_b.clicked.connect(self._clear_settings)
        v.addWidget(self._row("Clear Settings", "Puts EVERY launcher setting back to how it was when you first installed it — favorites, exclusions, paths, and launch arguments are all forgotten. It does NOT delete your downloaded ARK builds. Export your settings first if you might want them back.", clear_b))

        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)
        self._sync_path_labels()
        self._sync_steamcmd_label()
        self._refresh_delete_combo()

    @staticmethod
    def _header(title):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(2, 10, 2, 2); h.setSpacing(12)
        t = QLabel(title.title().replace("Dlc", "DLC")); t.setObjectName("SectionHeader"); h.addWidget(t); h.addWidget(hair(), 1); return w

    @staticmethod
    def _row(title, subtitle, control):
        f = QFrame(); f.setObjectName("Card"); h = QHBoxLayout(f); h.setContentsMargins(16, 12, 16, 12); h.setSpacing(16)
        v = QVBoxLayout(); v.setSpacing(2)
        t = QLabel(title); t.setObjectName("RowTitle"); s = QLabel(subtitle); s.setObjectName("Muted"); s.setWordWrap(True)
        v.addWidget(t); v.addWidget(s); h.addLayout(v, 1)
        if isinstance(control, QWidget): h.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        else: h.addLayout(control, 1)
        return f

    # ---- discord ----
    def _sync_discord_hint(self):
        if not discord_available():
            self.discord_hint.setText("pypresence isn't installed — install it with:  pip install pypresence  — then restart the launcher to enable Rich Presence.")
            self.discord_t.setEnabled(False)
        else:
            self.discord_t.setEnabled(True)
            if self.store.get("discord_rich_presence"):
                self.discord_hint.setText("On — your Discord status should now show Legacy ARK Launcher / Browsing builds while the launcher is open. If your profile still shows nothing, check Discord > Settings > Activity Privacy > Display current activity = ON, and that Discord desktop is open as the same account you are checking.")
            else:
                self.discord_hint.setText("Off.")
    def _on_discord_toggled(self, on):
        if on and not discord_available():
            self.discord_t.blockSignals(True); self.discord_t.setChecked(False); self.discord_t.blockSignals(False)
            self._sync_discord_hint()
            return
        self.store.set("discord_rich_presence", on)
        if on:
            ok, reason = discord_set_idle(self.store.get("discord_client_id", ""))
            if not ok:
                self.discord_hint.setText(f"Presence failed: {reason}")
            else:
                self._sync_discord_hint()
        else:
            try: discord_clear()
            except Exception: pass
            self._sync_discord_hint()
    def _on_discord_test(self):
        if not discord_available():
            QMessageBox.information(self, APP_NAME, "pypresence isn't installed.\n\nRun:  pip install pypresence\nThen restart the launcher and test again.")
            return
        cid = (self.discord_id_input.text() or "").strip()
        if not cid:
            QMessageBox.information(self, APP_NAME, "Paste your Discord Application ID first.")
            return
        ok, reason = discord_set_playing(cid, "test build")
        if ok:
            try:
                import datetime as _dt
                _now = _dt.datetime.now().strftime("%H:%M")
                self.discord_hint.setText(f"Test worked at {_now} — check your Discord profile NOW, test presence stays 15 seconds. Turn the Rich Presence toggle ON above to keep it as Browsing builds permanently. If your profile still shows nothing, check Discord > Settings > Activity Privacy > Display current activity as a status message = ON.")
            except Exception: pass
            QMessageBox.information(self, APP_NAME, "Rich Presence works — check your Discord profile NOW, it should show Legacy ARK Launcher / Playing ARK test build.\n\nTest presence stays 15 seconds (was 3 seconds before, which is why you missed it).\n\nAfter 15 seconds, if the Rich Presence toggle above is ON, it will switch to Browsing builds and stay. If the toggle is OFF, it will clear and your profile will go empty again — turn the toggle ON to keep presence.\n\nAlso check: Discord > Settings > Activity Privacy > Display current activity as a status message must be ON, or even a working presence will not show on your profile.")
            def _after_test():
                try:
                    if self.store.get("discord_rich_presence"):
                        discord_set_idle(self.store.get("discord_client_id", ""))
                    else:
                        discord_clear()
                except Exception: pass
            QTimer.singleShot(15000, _after_test)
        else:
            try: self.discord_hint.setText(f"Test failed: {reason}")
            except Exception: pass
            QMessageBox.warning(self, APP_NAME, f"Couldn't connect to Discord.\n\n{reason}")

    def _path_control(self, line_edit, key):
        lay = FlowLayout(); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        lay.addWidget(line_edit, 1)
        b = QPushButton("Browse"); b.clicked.connect(lambda: self._browse(line_edit, key))
        lay.addWidget(b)
        return lay

    # ---- player profiles ----
    def _profiles(self):
        p = self.store.get("profiles", []) or []
        return [x for x in p if isinstance(x, dict) and x.get("name")]

    def _sync_profile_combo(self):
        profiles = self._profiles()
        active = (self.store.get("active_profile", "") or "").strip()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in profiles:
            self.profile_combo.addItem(p["name"], p["name"])
        idx = self.profile_combo.findData(active)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

    def _on_profile_switched(self, idx):
        if idx < 0: return
        name = self.profile_combo.itemData(idx)
        if name:
            self.main.apply_profile(name)

    def _on_profile_new(self):
        dlg = ProfileDialog(self, self.store)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, player = dlg.values()
        if not name:
            return
        profiles = self._profiles()
        if any(p["name"].lower() == name.lower() for p in profiles):
            QMessageBox.information(self, APP_NAME, "A profile with that name already exists.")
            return
        sel = getattr(self.main.versions, "selected", None)
        profiles.append({"name": name, "player_name": player,
                         "build": sel.get("name", "") if sel else "",
                         "launch_args": self.store.get("launch_args", ""),
                         "host_preset": ""})
        self.store.set("profiles", profiles)
        self._sync_profile_combo()
        self.main.apply_profile(name)

    def _on_profile_rename(self):
        name = self.profile_combo.currentData()
        if not name: return
        if name == "Default":
            QMessageBox.information(self, APP_NAME, "The Default profile can't be renamed — make a new one instead.")
            return
        dlg = ProfileDialog(self, self.store, existing=name)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_name, player = dlg.values()
        if not new_name: return
        profiles = self._profiles()
        for p in profiles:
            if p["name"] == name:
                p["name"] = new_name; p["player_name"] = player
        if (self.store.get("active_profile", "") or "") == name:
            self.store.set("active_profile", new_name)
        self.store.set("profiles", profiles)
        self._sync_profile_combo()

    def _on_profile_delete(self):
        name = self.profile_combo.currentData()
        if not name: return
        profiles = [p for p in self._profiles() if p["name"] != name]
        if not profiles:
            profiles = [{"name": "Default", "player_name": "", "build": "",
                         "launch_args": "", "host_preset": ""}]
        ans = QMessageBox.question(self, APP_NAME, f"Delete profile \"{name}\"?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.store.set("profiles", profiles)
        if (self.store.get("active_profile", "") or "") == name:
            self.store.set("active_profile", profiles[0]["name"])
        self._sync_profile_combo()

    def _browse(self, line_edit, key):
        start = line_edit.text().strip() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        if d:
            line_edit.setText(d)  # textChanged saves it
            self._sync_path_labels()
            self._refresh_delete_combo()

    def _on_bg_changed(self, t):
        self.store.set("custom_background", t.strip())
        self.main.repaint()

    def _browse_background(self):
        start = self.bg_input.text().strip() or str(Path.home())
        f, _ = QFileDialog.getOpenFileName(self, "Choose background image", start,
                                           "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
        if f:
            self.bg_input.setText(f)  # textChanged saves it + repaints

    def _on_bg_opacity(self, v):
        self.store.set("background_opacity", v / 100.0)
        self._sync_bg_opacity_label()
        self.main.repaint()

    def _sync_bg_opacity_label(self):
        try: pct = int(float(self.store.get("background_opacity", 1.0)) * 100)
        except (TypeError, ValueError): pct = 30
        self.bg_opacity_label.setText(f"{pct}%")

    def _on_tray_toggled(self, on):
        self.store.set("minimize_to_tray", on)
        try:
            if on and getattr(self.main, "tray", None) is not None:
                self.main.tray.show()
            elif not on and getattr(self.main, "tray", None) is not None:
                self.main.tray.hide()
        except Exception:
            pass

    def _on_theme_changed(self):
        key = self.theme_combo.currentData() or "ember"
        self.store.set("theme", key)
        apply_theme(key, self.store)
        self.main.setStyleSheet(QSS)
        # Inline card-selection styles bake in the old accent — re-mark so
        # the selected version card picks up the new theme immediately.
        try:
            if hasattr(self.main.versions, "_mark_selected_card"):
                self.main.versions._mark_selected_card()
        except Exception:
            pass
        self.main.repaint()

    def _on_custom_color(self):
        from PyQt6.QtWidgets import QColorDialog
        cur = QColor((self.store.get("custom_accent", "") or "").strip() or ACCENT)
        color = QColorDialog.getColor(cur, self, "Pick an accent color")
        if not color.isValid(): return
        hexcol = color.name()
        self.store.set("custom_accent", hexcol)
        self.store.set("theme", "custom")
        if self.theme_combo.findData("custom") < 0:
            self.theme_combo.addItem("Custom", "custom")
        self.theme_combo.setCurrentIndex(self.theme_combo.findData("custom"))
        apply_theme("custom", self.store)
        self.main.setStyleSheet(QSS)
        self.main.repaint()

    def _sync_path_labels(self):
        steam = steam_dir_for(self.store)
        self.steam_resolved.setText(f"Using: {steam}" if steam else "Steam not found — install Steam and log in.")
        self.install_resolved.setText(f"Builds install to: {install_root_for(self.store, steam)}")
        try:
            self.steam_library_label.setText(_tek_ark_detection(steam))
        except Exception:
            pass

    def _sync_steamcmd_label(self):
        self.steamcmd_status.setText("SteamCMD ready." if steamcmd_ready() else "Not set up yet — hit Set up SteamCMD to download it.")

    def _setup_steamcmd(self):
        if getattr(self, "_setup_thread", None) and self._setup_thread.isRunning():
            return
        self.steamcmd_status.setText("Downloading SteamCMD...")
        self._setup_thread = _SetupSteamcmdThread()
        self._setup_thread.progress.connect(lambda m: self.steamcmd_status.setText(m))
        self._setup_thread.done.connect(self._setup_steamcmd_done)
        self._setup_thread.start()

    def _setup_steamcmd_done(self, ok, msg):
        self.steamcmd_status.setText(msg)
        if not ok:
            QMessageBox.warning(self, APP_NAME, msg)

    def _clear_steamcmd_cache(self):
        root = steamcmd_depot_root()
        if not root.is_dir():
            QMessageBox.information(self, APP_NAME, "Nothing cached yet."); return
        size = dir_size_gb(str(root))
        if size < 0.01:
            QMessageBox.information(self, APP_NAME, "Download cache is already empty."); return
        if QMessageBox.question(self, APP_NAME, f"Delete {size:.1f} GB of raw SteamCMD downloads?\n\nYour installed builds are untouched — this only clears the raw download files.") != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(root)
            QMessageBox.information(self, APP_NAME, f"Cleared {size:.1f} GB.")
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't clear the cache: {e}")

    def _toggle_default_dlc(self, key, on):
        lst = list(self.store.get("default_dlc_excluded", []) or [])
        if on and key not in lst: lst.append(key)
        if not on and key in lst: lst.remove(key)
        self.store.set("default_dlc_excluded", lst)

    def _installed_for_delete(self):
        out = []
        steam = steam_dir_for(self.store)
        for v in getattr(self.main.versions, "versions", []):
            exe = game_exe_for(steam, v, self.store)
            if exe and Path(exe).is_file():
                out.append(v)
        return out

    def _refresh_delete_combo(self):
        self.delete_combo.blockSignals(True)
        self.delete_combo.clear()
        steam = steam_dir_for(self.store)
        for v in self._installed_for_delete():
            name = v.get("name", "")
            # Cached size only — never walk the disk on the UI thread.
            size = _SIZE_CACHE.get(name, 0.0)
            self.delete_combo.addItem(f"{name} ({size:.1f} GB)", name)
        self.delete_combo.blockSignals(False)

    def _delete_build(self):
        name = self.delete_combo.currentData()
        if not name:
            return
        d = game_dir_for(self.store, {"name": name}, steam_dir_for(self.store))
        if self.store.get("confirm_delete", True):
            ans = QMessageBox.question(self, APP_NAME,
                f"Delete '{name}'?\n\nThis permanently removes its folder:\n{d}\n\nThis can't be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        try:
            shutil.rmtree(d)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't delete the folder: {e}")
            return
        self.main.versions._populate(); self.main.versions._refresh_details()
        self.main.refresh_all()

    def _check_updates(self):
        url = (self.store.get("update_url", "") or "").strip()
        if not url:
            self.update_status.setText("Set an update check URL above first.")
            return
        self.update_status.setText("Checking...")
        self._update_thread = _UpdateCheckThread(url)
        self._update_thread.done.connect(self._on_update_checked)
        self._update_thread.start()

    def _on_update_checked(self, ok, info):
        if not ok:
            self.update_status.setText(f"Couldn't check: {info}")
            return
        remote = (info.get("version", "") or "").strip()
        if not remote or remote == VERSION:
            self.update_status.setText(f"You're on the latest ({VERSION}).")
            return
        notes = (info.get("notes", "") or "").strip()
        dl_url = (info.get("url", "") or "").strip()
        if notes:
            self.store.set("update_notes", {"version": remote, "notes": notes, "fetched_at": time.time()})
        msg = f"A new version is available: {remote} (you have {VERSION})."
        if notes: msg += f"\n\n{notes}"
        if dl_url:
            msg += "\n\nDownload it now?"
            ans = QMessageBox.question(self, APP_NAME, msg)
            if ans == QMessageBox.StandardButton.Yes:
                self._download_update(dl_url, remote)
        else:
            QMessageBox.information(self, APP_NAME, msg)

    def _download_update(self, url, remote):
        try:
            dest = Path(_app_dir()) / f"Legacy-ARK-Launcher-{remote}.zip"
        except Exception:
            dest = Path.home() / f"Legacy-ARK-Launcher-{remote}.zip"
        self.update_status.setText(f"Downloading {remote}...")
        self._dl_thread = _UpdateDownloadThread(url, str(dest))
        self._dl_thread.done.connect(lambda ok, msg: self._on_update_downloaded(ok, msg, str(dest)))
        self._dl_thread.start()

    def _on_update_downloaded(self, ok, msg, dest):
        if not ok:
            self.update_status.setText(f"Download failed: {msg}")
            return
        self.update_status.setText(f"Downloaded to {dest}")
        QMessageBox.information(self, APP_NAME,
            f"New version downloaded:\n{dest}\n\nClose the launcher, extract the zip over your launcher folder, and start it again.")

    def _export_settings(self):
        dest, _ok = QFileDialog.getSaveFileName(self, "Export settings", "launcher-settings.json", "JSON files (*.json)")
        if dest:
            Path(dest).write_text(json.dumps(self.store.settings, indent=2), encoding="utf-8")
            self.update_status.setText(f"Settings exported to {dest}")
    def _import_settings(self):
        src, _ok = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON files (*.json)")
        if not src:
            return
        try:
            data = json.loads(Path(src).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not a settings object")
            for k, v in data.items():
                if isinstance(k, str):
                    self.store.set(k, v)
            self.update_status.setText(f"Settings imported from {src} ({len(data)} keys).")
            self.refresh()
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not import settings: {e}")
    def _clear_settings(self):
        ans = QMessageBox.question(self, APP_NAME,
            "Reset ALL launcher settings to defaults?\n\nThis clears favorites, DLC exclusions, paths, and launch arguments.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.store.settings = copy.deepcopy(Store.DEFAULTS)
        self.store.save()
        # Settings applied at startup (always-on-top, sidebar width)
        # don't re-read on their own — re-apply them now so the
        # reset takes effect without a restart.
        self.main.apply_always_on_top()
        self.main.apply_sidebar_width(Store.DEFAULTS["sidebar_width"], collapsed=False)
        self.main.versions._populate()
        self.main.refresh_all()

    def refresh(self):
        try:
            self.est_t.setChecked(bool(self.store.get("show_estimates", True)))
            self.conf_t.setChecked(bool(self.store.get("confirm_delete", True)))
            self.tabref_t.setChecked(bool(self.store.get("refresh_on_tab", True)))
            self.dino_t.setChecked(bool(self.store.get("show_dino_play", True)))
        except Exception:
            pass
        self.top_t.setChecked(bool(self.store.get("always_on_top")))
        try:
            self.carddates_t.setChecked(bool(self.store.get("show_card_dates", True))); self.compact_t.setChecked(bool(self.store.get("compact_cards", False))); self.hideinst_t.setChecked(bool(self.store.get("hide_installed_badge", False))); self.confq_t.setChecked(bool(self.store.get("confirm_before_queue", False))); self.autosel_t.setChecked(bool(self.store.get("auto_select_first_build", True))); self.remember_t.setChecked(bool(self.store.get("remember_last_tab", False))); self.maxstart_t.setChecked(bool(self.store.get("start_maximized", False))); self.toolhint_t.setChecked(bool(self.store.get("show_tool_hints", True))); self.statusontab_t.setChecked(bool(self.store.get("show_status_on_tab", True)))
        except Exception:
            pass
        self.args_input.setText(self.store.get("launch_args", ""))
        self._sync_profile_combo()
        self.steam_input.setText(self.store.get("steam_path", ""))
        self.install_input.setText(self.store.get("install_dir", ""))
        self.steam_user_input.setText(self.store.get("steam_username", ""))
        self.bg_input.blockSignals(True); self.bg_input.setText(self.store.get("custom_background", "")); self.bg_input.blockSignals(False)
        self.bg_opacity.blockSignals(True); self.bg_opacity.setValue(int(float(self.store.get("background_opacity", 1.0)) * 100)); self.bg_opacity.blockSignals(False)
        self._sync_bg_opacity_label()
        defaults = self.store.get("default_dlc_excluded", []) or []
        for key, cb in self.dlc_checks.items():
            cb.blockSignals(True); cb.setChecked(key in defaults); cb.blockSignals(False)
        self._sync_path_labels()
        self._sync_steamcmd_label()
        self._refresh_delete_combo()

class HelpPage(QWidget):
    """Static FAQ — no network fetches. Concise Q/A rows, same card styling."""

    FAQ = [
        ("How do I get a build?",
         "Pick a version on the Versions tab, hit Download, then Play once it says Installed. First download: a SteamCMD window may pop up asking you to log in — type your password there yourself."),
        ("What is SteamCMD?",
         "Valve's official command-line Steam tool. The launcher downloads it once into a steamcmd/ folder next to the app and uses it to download old ARK builds. It never touches your password."),
        ("SteamCMD asks for a password / Steam Guard code",
         "That's Steam asking you to log in — type your password and Guard code in the SteamCMD window yourself. The launcher never sees, stores, or types your password. If it asks again later, your saved login expired — just log in again."),
        ("Windows SmartScreen warning",
         "The launcher is unsigned, so SmartScreen warns on first run. Click “More info” → “Run anyway”."),
        ("Primitive+ does not work / does not show up",
         "Primitive+ is NOT a map and NOT a normal mod — it is a Total Conversion. (1) It did not exist before Jul 2016, so Jun 2015–Jun 2016 builds have no Primitive+ at all — pick Jul 2016 or later. (2) It is a separate FREE DLC in Steam (app 508150) — if you never claimed it in Steam, SteamCMD cannot download it even though it is free; add it to your Steam library first, then Download again. (3) Even with it downloaded, Play still launches vanilla ARK — in ARK's main menu, before Host/Local, pick Total Conversion → Primitive Plus (the game restarts). Most normal mods will not work with it, and it is the least-supported official DLC."),
        ("Download stuck or slow",
         "Big builds take a while. The launcher watches the download folder and waits for it to stop growing. Make sure SteamCMD is set up (Settings → Steam), your Steam username is filled in, and no SteamCMD window is waiting for you to type a password. Check free disk space, then retry."),
        ("What if I close the app while downloading?",
         "It does NOT break anything permanently, and it does NOT delete what you already downloaded. Closing the window while a download runs just hides the launcher to the system tray (by the clock) and the download keeps going normally — reopen it from the tray when it finishes, and it will say Installed. If you quit for real from tray > Quit, or hit Cancel, the download stops but partial files are kept, so hitting Download again resumes instead of starting over. Do NOT close the SteamCMD window itself mid-download — that stops SteamCMD, and you will need to hit Download again to resume."),
        ("Discord button in the top bar",
         "Click JOIN DISCORD at the top right — it opens the community Discord invite in your browser, so you can join the community. You need a Discord account to join. That button is just a link — it does not show your Discord status. Rich Presence (showing Legacy ARK Launcher + the build you are playing as your status) is separate, in Settings > Discord, with a Test button."),
        ("Not enough disk space",
         "Each build is tens of GB. Free up space, or delete an old build in Settings → Data."),
        ("Play does nothing / game won't launch",
         "Make sure the build finished downloading — the Versions tab should say Installed. Then try Play again."),
        ("Black screen with music / game window won't show",
         "Old builds sometimes fail at fullscreen on modern PCs. In Settings → Default Launch Arguments put: -sm4 -windowed -ResX=1280 -ResY=720 then hit Play again. (-sm4 = the old graphics path, -windowed avoids the fullscreen problem.) If the game seems stuck, end ShooterGame.exe in Task Manager first."),
        ("Play launches but where's the server?",
         "Play only opens the game to the main menu — it never auto-joins. Join a server from the Servers tab, or from the in-game browser."),
        ("How do Servers work?",
         "Add a server on the Servers tab with its IP, game port (usually 7777), and query port (usually 27015). The launcher asks the server for its name, map, player count, PvE/PvP, and cluster — servers sharing a ClusterId group together. Join opens it in Steam; Join with build launches one of your timecapsule builds straight into it. Only servers you add are listed — there are no sponsored or community servers. You must own ARK on Steam to join."),
    ]

    def __init__(self, main):
        super().__init__(); self.main = main
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(28, 24, 28, 28); v.setSpacing(14); v.setAlignment(Qt.AlignmentFlag.AlignTop)

        v.addWidget(page_header("Help", "Answers to the usual questions."))
        about = QFrame(); about.setObjectName("Card")
        av = QVBoxLayout(about); av.setContentsMargins(16, 12, 16, 12); av.setSpacing(8)
        at = QLabel(f"About Legacy ARK Launcher {VERSION}"); at.setObjectName("RowTitle"); av.addWidget(at)
        ad = QLabel("Old ARK builds, 2015 to 2024 — downloaded through your own Steam account, only builds you own. "
                    "Made for the OG Ark community."); ad.setObjectName("Muted"); ad.setWordWrap(True); av.addWidget(ad)
        au = QLabel("Usage counting is off unless you turn it on in Settings → Usage Counting. When on, the launcher sends one anonymous ping per day with only the launcher version — no username, no game data. The website's Active users shows launchers online right now (live presence); the same live count shows in the header when presence is on, and the daily total otherwise."); au.setObjectName("Muted"); au.setWordWrap(True); av.addWidget(au)
        arow = FlowLayout(); arow.setSpacing(10)
        for _txt, _url in [("Website", "https://legacy-ark-launcher.netlify.app/"), ("Discord", DISCORD_INVITE_URL), ("GitHub", "https://github.com/6frizz/Legacy-ARK-Launcher")]:
            _b = QPushButton(_txt); _b.clicked.connect(lambda _c=False, _u=_url: _open_url(_u)); arow.addWidget(_b)
        arow.addStretch(1); av.addLayout(arow)
        v.addWidget(about)
        for q, a in self.FAQ:
            v.addWidget(self._qa(q, a))


        v.addWidget(SettingsPage._header("WHERE BUILDS INSTALL"))
        self.install_label = QLabel(""); self.install_label.setObjectName("Muted"); self.install_label.setWordWrap(True)
        v.addWidget(self.install_label)


        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)

    @staticmethod
    def _qa(q, a):
        f = QFrame(); f.setObjectName("Card"); lay = QVBoxLayout(f); lay.setContentsMargins(16, 12, 16, 12); lay.setSpacing(4)
        t = QLabel(q); t.setObjectName("RowTitle"); lay.addWidget(t)
        s = QLabel(a); s.setObjectName("Muted"); s.setWordWrap(True); lay.addWidget(s)
        return f

    def refresh(self):
        steam = steam_dir_for(self.main.store)
        root = install_root_for(self.main.store, steam)
        self.install_label.setText(f"Builds install to:\n{root}")


# ------------------------------------------------------------------ helpers
def _fetch_json(url, timeout=10):
    """GET a JSON document. Raises on any failure — callers decide the fallback."""
    req = urllib.request.Request(url, headers={"User-Agent": "LegacyARKLauncher/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))

class _SizeThread(QThread):
    """Measure installed build sizes off the GUI thread — walking tens of
    GB on the UI thread freezes every click, so cards show the estimate
    first and this fills in the real numbers when ready."""
    sized = pyqtSignal(str, float)

    def __init__(self, jobs):
        super().__init__(); self.jobs = jobs  # [(name, game_dir_str)]

    def run(self):
        for name, gdir in self.jobs:
            try:
                self.sized.emit(name, dir_size_gb(gdir))
            except Exception:
                pass

class _UpdateCheckThread(QThread):
    """Check a version.json URL off the GUI thread. Emits (ok, dict-or-error)."""
    done = pyqtSignal(bool, object)

    def __init__(self, url):
        super().__init__(); self.url = url

    def run(self):
        try:
            data = _fetch_json(self.url, timeout=10)
            if not isinstance(data, dict) or not data.get("version"):
                self.done.emit(False, "bad version file")
                return
            self.done.emit(True, data)
        except Exception as e:
            self.done.emit(False, str(e))

class _UpdateDownloadThread(QThread):
    """Download the update zip off the GUI thread. Emits (ok, msg)."""
    done = pyqtSignal(bool, str)

    def __init__(self, url, dest):
        super().__init__(); self.url = url; self.dest = dest

    def run(self):
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "LegacyARKLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(self.dest, "wb") as f:
                shutil.copyfileobj(resp, f, length=1024 * 256)
            self.done.emit(True, "ok")
        except Exception as e:
            self.done.emit(False, str(e))

def _strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


# ------------------------------------------------------------------ DLC / version artwork
# Official ARK header art shipped next to this file in art/<key>.jpg.
# Missing files (e.g. Aquatica, or a folder shipped without art/) fall back
# to the drawn icons — never crash, never show a broken image.
ART_DIR = _resource("art")
_ART_CACHE = {}

def art_pixmap(key, width, height):
    """Header art for `key` (e.g. 'ragnarok'), center-cropped to exactly
    width x height, or None if the file is missing/unreadable."""
    cache_key = (key, width, height)
    if cache_key in _ART_CACHE:
        return _ART_CACHE[cache_key]
    pm = None
    try:
        p = ART_DIR / f"{key}.jpg"
        if p.is_file():
            raw = QPixmap(str(p))
            if not raw.isNull():
                scaled = raw.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation)
                x = max(0, (scaled.width() - width) // 2)
                y = max(0, (scaled.height() - height) // 2)
                pm = scaled.copy(x, y, width, height)
    except Exception:
        pm = None
    _ART_CACHE[cache_key] = pm
    return pm

def art_label(key, width, height, fallback_icon):
    """Centered label showing header art, or the drawn fallback icon.
    v1.58: the art pixmap is masked to a rounded rect (8px) with
    transparent corners, so it cannot poke out past a rounded card —
    art_label is a plain QLabel, and plain QLabels ignore QSS
    border-radius, which is why a sharp art image could stick out
    even when its card was rounded. This covers DLC cards (120x56)
    and the version-card fallback (150x68)."""
    pm = art_pixmap(key, width, height)
    if pm is not None:
        try:
            out = QPixmap(pm.size()); out.fill(Qt.GlobalColor.transparent)
            _p = QPainter(out); _p.setRenderHint(QPainter.RenderHint.Antialiasing)
            _path = QPainterPath(); _path.addRoundedRect(QRectF(out.rect()), 8.0, 8.0)
            _p.setClipPath(_path); _p.drawPixmap(0, 0, pm); _p.end()
            pm = out
        except Exception:
            pass
        lbl = QLabel()
        lbl.setPixmap(pm)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFixedSize(width, height)
        return lbl
    return centered_label(icon(fallback_icon, 22, "#f2f2f2", 1.8))

def art_pixmap_full(key):
    """Full-resolution header art for `key`, or None. Used by the
    full-bleed card banner, which crops to the card's actual width."""
    try:
        pth = ART_DIR / f"{key}.jpg"
        if pth.is_file():
            pm = QPixmap(str(pth))
            return pm if not pm.isNull() else None
    except Exception:
        pass
    return None

class FullBleedBanner(QLabel):
    """A banner that fills its whole width, edge to edge, like a
    Steam library tile: the image is scaled to COVER the widget
    (center-cropped, never stretched), so there is no padding,
    no border and no letterboxing around it.
    fit=True (details banner only, v1.56): show the WHOLE image, no
    crop, centered on a dark background — used when cover-cropping
    would clip important text at the image edge (e.g. "PRIMITIVE+").
    v1.57: (1) ALL banners clip to a rounded rect (12px, matching the
    cards) — before, QLabel paint ignored QSS border-radius, so the
    image's sharp corners poked out past the card's rounded pill on
    every banner, not just one build. (2) fit mode no longer fills
    the sides with solid black (#0b0d14) — that was the "black boxes"
    in the screenshot: the fit image is narrower than the banner, so
    the empty sides were solid dark. Now the sides are a blurred,
    darkened copy of the same image, filling the width, with the sharp
    uncropped image centered on top — no black boxes, no crop."""
    def __init__(self, pixmap=None, height=120, fit=False, round_all=None):
        super().__init__()
        self._pm = pixmap
        self._fit = bool(fit)
        self._round_all = bool(fit) if round_all is None else bool(round_all)
        self.setFixedHeight(height)
        self.setMinimumWidth(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    def setPixmapFull(self, pixmap):
        self._pm = pixmap
        self.update()
    def paintEvent(self, e):
        if self._pm is None or self._pm.isNull():
            super().paintEvent(e)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Clip to rounded corners, 12px like the cards. Without this,
        # QLabel paint draws a sharp rectangle over the card's rounded
        # pill, so the image corners stick out — on every banner, since
        # every banner is this class. Details (fit) = all 4 corners
        # rounded (standalone pill). Version cards (cover) = top corners
        # only rounded, bottom square, because the text block sits
        # directly underneath the banner inside the same card.
        r = QRectF(self.rect())
        path = QPainterPath()
        if getattr(self, "_fit", False) or getattr(self, "_round_all", False):
            path.addRoundedRect(r, 12.0, 12.0)
        else:
            path.moveTo(r.left(), r.bottom())
            path.lineTo(r.left(), r.top() + 12.0)
            path.quadTo(r.left(), r.top(), r.left() + 12.0, r.top())
            path.lineTo(r.right() - 12.0, r.top())
            path.quadTo(r.right(), r.top(), r.right(), r.top() + 12.0)
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
        p.setClipPath(path)
        if getattr(self, "_fit", False):
            # Blurred background fill, NOT solid black: shrink the image
            # to 1/16 size then scale it back up — that is a cheap blur
            # — cover the whole banner with it, darken it so the sharp
            # foreground stands out, then draw the sharp fit image
            # centered on top, uncropped.
            try:
                small = self._pm.scaled(max(1, self.width() // 16), max(1, self.height() // 16), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                blurred = small.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                bx = max(0, (blurred.width() - self.width()) // 2)
                by = max(0, (blurred.height() - self.height()) // 2)
                p.drawPixmap(0, 0, blurred.copy(bx, by, self.width(), self.height()))
                p.fillRect(self.rect(), QColor(0, 0, 0, 110))
            except Exception:
                p.fillRect(self.rect(), QColor(11, 13, 20))
            scaled = self._pm.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            x = max(0, (self.width() - scaled.width()) // 2)
            y = max(0, (self.height() - scaled.height()) // 2)
            p.drawPixmap(x, y, scaled)
        else:
            scaled = self._pm.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            x = max(0, (scaled.width() - self.width()) // 2)
            y = max(0, (scaled.height() - self.height()) // 2)
            p.drawPixmap(0, 0, scaled.copy(x, y, self.width(), self.height()))
        p.end()

class ClickableCard(QFrame):
    """A QFrame that emits clicked on left mouse press, for card-grid UIs."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ------------------------------------------------------------------ dino runner
# The REAL Chrome T-Rex Runner sprites, from Chromium's open-source
# offline game (BSD-style license, (c) The Chromium Authors).
# The sprite sheet below is Chromium's 100-offline-sprite.png (1233x68),
# embedded as base64 so the launcher stays a single .py / exe with no
# extra files to bundle. No WebEngine, no browser, just QPixmap crops
# from that sheet, at Chrome's exact 600x150 canvas size.
# Sprite coordinates are Chromium's: trex 848,2 44x47, duck 1112,19
# 59x30, ptero 134,2 46x40, cactus small 228,2, cactus large 332,2,
# cloud 86,2, horizon 2,54 / 602,54, moon 484,2, stars 645,2,
# numbers 655,2, game over 655,15. Restart icon is Chromium's
# 1x-restart.png, also embedded. Night mode uses an inverted copy
# of the same sheet, like Chrome's invert after 700 points.
# Controls: Space / Up / W / click = jump, Down / S = duck (Down in
# the air = fast-drop), R = restart after game over.

_DINO_SHEET_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAABNEAAABECAAAAACKI/xBAAAAAnRSTlMAAHaTzTgAAAoOSURBVHgB"
    "7J1bdqS4FkSDu7gPTYSh2AOATw1Pn6kBVA2FieiTrlesq6po8lgt0pj02b06E58HlRhXOCQBBcdx"
    "HMdxHOfDMeA7BfcIOI4VwISDKQhvK0O4H9iAobeFZSx8WIK0dqz4ztQRg1XdECNfX/CTGUDmNjJD"
    "P6MzuMnKKsQ0Y+Amyxnirurmx1KghAvWXoARAErEPUpAB/KzvK6YcAIl8lD2AtsCbENPS1XGwqMT"
    "SnvHhNOYgBV3mKlklKDqPUshMUIzsuzlOXFGW9AQS0C/lv/QMWrahOMoiKZL41HyUCRAdcKyDR0t"
    "VRkLD0+oV7Q7yLofm6w6rKbdrmNUL6NOyapMtGcUuixZ2WSHbsl+M97BoUX8TrpyrfGbJJ+saBQ0"
    "W9I6jnxF/ZO+4nqo66GQneo325keUjth7bFpX38MO6lbM+ZMaeOYETISzYzN9Wiy7shuyj4dI96J"
    "SQXuOMSlWcqkgQ2DSlVdUSIbWbVs2vJ41CvadDs0jTE63Y9NWO26r3x9MU3AzDGk1mQWZu2Bht6V"
    "aPzEXrl21gjyZRXNPnKFI8+TJnRKLEED24JNpaqqKBGx/C5oWLSlBR0+Pp4J5yM27YVydp8sX4p+"
    "SUGe661TuWE5Y78dtcDSX3u+oqWINjLmRm+wTsBUJWpK06pKaXZpJdbmhoH/LcByq6Rq+LMC+7Dl"
    "+OFjvzj2ObRJY/tOa1r/uUvDy9d9QaPz4utMP6ZDysxsPeScf3yly6bOfRbcemtPYESvpAn20GSS"
    "0efVKOGc4aNQgojj1ZnzvTEnkxqzOVfGllP3y9qnZ0S3pM2mK5jMwQcpiMb1ZVqdkBANl1aCFbBb"
    "dOR6Pvwgtjiu9vkx60jrXNpq15E8ywhz/2tbzGQQwQ4b59Zfe7aipVrSEhCP8mZG1UlzZ20tOgw9"
    "Hw6hrzCLZiyObqCkVauZFC0OPL8nqUrk/zHN1gopOfkzngH3fv8SQau20jtMQ09VUSmxQUS1OsZS"
    "DAWSwKNFq5SylzA6PhFf+Oo4x3m0pEuYKXb4s5WLAAaT1lwfc3Kr6CDZ6JD6hrUCWVhmjHFrzNk1"
    "7pxWjdGl/Yi9AuBrBqAbusmvGNNCyWpbhvPU82j1aDMi9Q04p8aLaQtiw7plXZ0A7TwDSojO/GsC"
    "iAnE6qAGhg45/eAu7csrunGcEUpEN5NsXYDlUY6Mie67UGPTPiiO1xl0vgLYvXt83glmvkux7ke6"
    "WdGzz7mKmiSQM2ufmPEoQUv9d2fu3jEazGqc79JUQjRxghoZT9FoiJnjzvbYtDJGOXOcoxUt4hMy"
    "bAucE3nloJPOSJh5v6cm8gwFWrnn72aj1txnvR+5RrzoXy8kBOAStWBtw/foGvd1NnyX+h2a+LXQ"
    "UH2XKAFT0uLpi9byzXg2vrzy9Z6eAZmqIUnHoaJ9PlIofwaAYQMWu6XituAE6vWBgifhla/Xp3Cl"
    "qjpFESRdt5Z+WCIkQ68vHNBAXysZH3CmuufhInRurCagvLk6QNXpbwMDNvouu+Vn/fLeVo3rA084"
    "PzAYiwDtzB1jIB3Jmvuc0YqzQRk6W0d8LhIQ9gPkNhSpEGjr2HKW4XyOuznthx/M+8V/W5+7/vRZ"
    "9yARQ4L5a18IIBetJbN18/oGYNjRHwyHt6qiJSj9R25zZ55M7Uiq6u3qglDF2KmBCqqTVqhNO0bQ"
    "Sp+gxRJkV9fi68uP/z8TzgYd3tyw9bQOqBUtpmdd9wwlGoGKGzDstMR7LR1EtENp582d1z5jL3yG"
    "rc79y83pSsbBZHquNluXZd5DfteKbbhaLc+Ongp1tUslUUvDve1drSPuSFoE2o/8AIL6rspChrbq"
    "Zkkb0N5yhNa2E3B95Bm2vN+8m/me3lE9WaGp3LbPPDc/u9VZoJFbZ+uoCvaMhAJEDTS2xOO/Tdzp"
    "+Xs6C3mG7fXhnXlR4gnx4rXU7dma/FTl0YS29beOjztTx6NOUF2aVrNEe/bZa4m6+nmuEJUAbnFP"
    "15xH+/7fHU/FYG6LG+SmVL5bmnFZ/Ho0J4WP4NK4KMCtS7u0p/Bo9ngnXbfWXnVu/DcNdGf9rRgf"
    "eab6sWfR1KXZ1Z0kY7+l3rIToQCImiD2U9y4FepFaHm44jpJjDTGlOmfxVbGHMc92nkEW/PrrRSK"
    "JiqjF4CiHaqBNqEuLPxDLsGL/+xcvFavbLph6W89TdHCw5wZCW2zXggfe4Sqcc2oBhYYSAc+EY4z"
    "GhM5/teid0osBSaaBC3F/vPAjvpxsdDx5Dp1jjsnI7Y+95hT5z+erpZkzB/dpY2wJS0FPfLH0/ws"
    "j/AhJS0FJuTaWOPbHWFbN/9VdCUSwtPW5g81j2aMZULDkbtLE+GSBKOCdGiCURtVTXFpp7KCuEtz"
    "l3braVVFQ+g/8n6eQil/X24MmjAIe+oYJNqwK2M8uU5mXc8652rXOY6vdZ6NvdyoiXZ1jBqNcC7o"
    "0tKVaw2XlltdGs0VUwsYGTpbxwPO1JXcU7gTGLYfrx0tx6tjsW/PsjHd14p2l+YOzXGPdirBDAwd"
    "Le9sAf54IEh86zLA2qQj64SGYp9EM674Dk9Rqy4tY58B2MRqVRZOIr2t44FnymfRzlyJSOHBLg2r"
    "OzSnn5vxjI3O1hHXxyVNb8zqt2mNi6OrGzR9egPfH1QLREQgFSDs17Ky/zOoS+O7wVJNfN1axjh1"
    "08L93G8dH3umelx7gGMTCuLbbfJEQZEYha6KGTbN9l2r+zNn2xkwLnzorNWqsLVP0eaGXMZ74pLW"
    "DNXLL0N7+GRnAmdqwgNqE4O7tQkREQmp+zMoudWlATcMaIRN28ErA5nv9pF/6PtEnak/1r8H53lR"
    "R6bcfuYe0DrCcZxL3vdk19PHBZQz73u6AT0ODZWGbTAY33Ud0nEcZ3hg64gmZjiO81YiCkK1dXyt"
    "BauO/wwzsmxBqc3VIhP6DVNw5FhFywDS24/cKeHRCdLfoTiO3zMw58+uYUX/HYD2BLETinY4Z5Bk"
    "6+jaFo79DFm3LG4Q+pr6r97I5pH7pRsllgiQUEJ7QsSRCdN2aYfjuEczNDnollPLSKm/7EhQ6pgQ"
    "2yUKpx3OaQTZOra2gf7P0M/Q3+ScTJlLX6KgECb49h02lFLudPzVzn0lNQwEURQdrfGuc9anX34A"
    "Izk21c/xHjLYCo/JU2W1kLTm/7BeP7kkSZIkZbj0JhHZgDdAg5UeAA6f9f8Ar//eMZqUxs8ggs7B"
    "hAEarPQAsPm+hwFus4SnG6Mx3pI0xwEX/syoMMDteO0x17QlCd5m/CbX0STs9m3RDggXBLpKWv5S"
    "83eSF787y1Wd5apuCcXDHFu0HL1wPGbhz6lL2WL2VYrtE6NPZW7usXAEy1WZ5epGInCMMLhTBsCQ"
    "5erTyhXVlAASQROIjO0FvHBFh+evzparEMvVsp8XMGZ5HuHL3cZGzpu884kxZtN/1HLVynL1uiRJ"
    "kvQFUg1OaKSaqSkAAAAASUVORK5CYII="
)
_DINO_SHEET_NIGHT_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAABNEAAABECAYAAACvSKOdAAAR/UlEQVR4nO3dTXakuBKAUejzJrkR"
    "L8W1AHuYy8uhvYDyUryR6hlvUEfVpAqBfkJShPTdSXfZpAhhICEIoXXbtgUAAAAAAABA2D+9AwAA"
    "AAAAAAC0+9/RD2+3W5fytF+/fq091mvVy8vL09/p+/ub7VfI7fsa98X9cZkbn0Qb67r+aWPbtm5x"
    "aOnLkaNzqPQ+xTp06dkP/7vAyf1OsNpeiPa4tbTne3193b6+vk7b+vz8fIrh7e0tavmj5fy2Qu2e"
    "LRfbtlsmta3Q8rHtXS2bu132y4S2VW6f0Zb0PVjt7yHiJd49a/ECuf5Kot1ut+3xePSIZbndbhsH"
    "y7Gri+WXl5fNLUMybTz+cZlzrEi0sa7r9vHx8fTv1OTTSH2Jia0kRtZhg6Z+cP6fx/5vnZpYlHCU"
    "jAklya4SNzG/z0nuxCS1NLXlb79a2wUAAOR7SqL1TKAty7I8Ho9mNx2WMuUxyTE/mcaNVBq3P7j9"
    "X1NF2tFxmXqsSLThJ52WZVk+Pj6Skk8j9SU2ttwYWUfZOiQqFWPXU3tb+aQTJmft5XyX1EjolLQp"
    "XbWd214o6aUlvlwpVVgp7YXaPEvQlSSUUj4bs2xs9Zz0cjlxkYjrz78vKb0fu9/vRZ+/QrzEu2ct"
    "Xl/p9xfn0Pn8SaL1TqA5tRNplg7y/YVwykV6jyfSQE0S5wSpSjPoJ1GpaIm1hyZW4t0/nOodyxXp"
    "qrTX19fN/fdoSGcoueV+7ldIXSXaUocx+stcfX4f21VbR3HFJupi4jj6PTdgAADYcfhONOgh8a4U"
    "KzcsmmisSDsjVRnkt+HeGRabfJJIVPlxuIRISR9d5VlKfCTdbJKoVNRqtgq0Wskr6Vcf5LR3lqDr"
    "FZ9LnJ39/OodaaViqwH85VKHQabEEzM0NZQEy+1P7bagl1RBQ6vrWOIl3qP1SLVTO17J74ploSJt"
    "JtMm0awd5KmO3pV29HvYJ5FkOmpjP+Rx/wL+kJxE1VUc+4SI+3lqm/t+uPhiPzN6Iq3VkEfI4xyO"
    "kNyqtH2CrGXiLEatYZqlya/cGEKVcbHLYR7v7+/Lsvy+foE8a9vXaryO9ritxYt+RJJo9/tdLCnV"
    "i/TTy1ylT97996Ed3WhJPt33kxpWbsRjkzFak6TOUZKp5CX9ro1///336Yvj4+Pjry+WvaNEVcmE"
    "A7kJMwkSfbFgtiGPpXomHEeqQItpv9XwydgKrdjXJIxSkbYsvxNnMbNzSkqp8ApVh8VWjpUMoTx6"
    "p5jfXuoQzn07/udqzmQKALW5a+qz+whNrMWLPsQq0UZIpPUmccEc+1mGe2JkJITOjTzkMVbJZBYz"
    "bSfgisQ7vXKGKkoMm5FurwUSY3OhEqYua9vXWrzAqESHc1pOpLW6KLl6mt0ioSXxAmJ/Nkv/51pv"
    "MENxuwki3H+PEgz7z9fuX613nPXQOg6J4a0YW8o+0jPh2PodY6nfP1begRa73t7vSAv1X0N8vqth"
    "hqUJqRqf15wwyx0Noa0fAOCzVtFlLV70kZxEu5qN8iiRtv+M1SSbBOkLYSla45pVrXec9dA6Di1D"
    "QqGXxBDonjhPI0XJDKPrer6r+bNxup/5y4WGU+7bifnM29vberROf5nToCP6cNRezfWGfu/+X2J9"
    "ezl/DwDIYa1yzlq86OeflIWvEmgxy8W2MSptN0Df399rSky3221zN6GWEqJScbvPu/YEQ1yWRSYJ"
    "pCWRpCUOzdx+VHPb1G5/vw7+xoBtP378ODyGQz8HAACYTXQlWkry6ypJYXnYZ4p9hVfopcFakmou"
    "Ri3xAKNr8Z6t/TpqDUVu9b4w7UPFY8VMUCA9o3JMFVJK+6MM4/T1HjZ5NYFBSXxHFWlH7f38+fOw"
    "7dDPY6qWpJbJWTbmc7HtSccoud6UvlFpBgBAmax3oqUO13Q/m6kKzb84PbrojZ3xS4PQu8R82maz"
    "TI07dh/V1k+0VTpTY8x7tqTX8Xg8xM/BLfrhr8fa8Ms9JiiAFa7y7MePH1sogQYAADAj0YkFZqgu"
    "i5Xy5Ll2LIAE3hPwW+sKslrraEGiH0fJQIvbgxlRoV3MUM6jhNrVy/BrzNwp2WaNSQhSJghoWRlW"
    "azII69szpn1tFXzWChOIty5r8QLWiSXRRk2gzX5Siq3kuvp8LKmbydK4Y1GRNpcWiZBRki2j9KOl"
    "UGVy7sMW7cMutVZi9x7WWbO9owr4o/auEmcAAACzEkmijZpAA2a1bdu6rutG9RkAzOfnz59rzFDO"
    "2rM6+u3vZ8iUWt9+ZtGUiqdYGiqYYirFzmZY1aR2fKnbx39YnFNtnRNn6N7LPfwPxUG8cYg3jvSE"
    "Un68b29vks2L036+RD2iwzlrsnZSsq60kqu0cq3k3Ukl67eUEJaI9ayNlom0ltudxOBYqAIF5IQS"
    "Z/7PWyfP/P+vkfSpkUADAADjMZNEA3Dufr8vv379WkueCrk23L9dIs39u1UCSqIve+/v7yTPBpQ6"
    "4YD0E1NgNKmzcwKz8h/aprz+5ei7KPZhYu5rZoiXeI/WaSVeR+rhSexDk9z17O+d9rZtG+67dKa+"
    "7qlPolk9yEeRuh1KK4r8d4ylOpoRMGW9uXLjlqqe8ZNfkm24k2DoJCmdnJLoy94+/qtYSbTZEZpw"
    "ILS8pSpTQINtS/8arjEJgHWhm7VRt0vt4bEttyfViQBGEbqPy6U5Sdair+qTaACO7ROcuUkniTZ8"
    "7+/vy7ZtSVVkNeLw5VTVub7UiAf9+QlbJj0AyuyHW0q1WTuRsY+5RvyjJsv2jrabvw2ltkPt7Vkr"
    "EVzyYD9GjVnC/Z8Rrxzifdbi2qtHUtzda7y/vy/L8ndyx7/HkE7+HK2jlpn6uiyZSTTNVVojHOQa"
    "9HonmZP6eX+fzH1nXuu4r97ndNVeTD8l2oh1lnRqGUfIVVXd3qwJtFmGPB4l0FJnD51lW2Eur6+v"
    "29fX1xr6NwAAsMG/5ykddRNKkmlQu6/7+8LoJNrj8RBLnjGsBjjm3gNWcoxItJHCnWCW5fnkUqMv"
    "tfsU6sssRj43nyXa/X0sJpE28rbC3L6+vtbX19dtWcIJtJov+A+ta2/UWTStCw3htLRtQ1V1V32I"
    "fa2H9MPa3Hsz4o37PPGery93PU5uvLHfO6XfFVIVtX4y5yoRJfF6mf09TUuz9DWpEk0ikdbq3VNa"
    "DvLZ+O8kk77RDP0dSquYNMVtMZEWSjiN1JeRtN6mWsxSSQzkcImzs5/7CbV90oT3Rx272i4tEkxH"
    "Sc9acRwNj5XUanv6CcHayWIAqEnqvc/+sE2NWvQ1eTjnbDddQA/+zJQ5x51EGxIk+3L2Wc5NaWZN"
    "pKViO2EW/hDOo58DOBeaCE3qO8S1K9Ue8T4jXlvxhpLbUg91arwnc1naTGR2tY5afUuNo8U6avTV"
    "7MQC1g5yyKhdIVirIi0n7tyZRqXbkCDdl5i/i/QsnyOaOUEU++4zt9ys2wnzcUM4/f+Glq9RmXPV"
    "Zuk6e7ffS8u4JNdVO+5Q+1r/jgCAvswm0QAghARavBkTRLGTCPjLzbadMCc/YUYlGpCu9neF9ENk"
    "4n1GvLbibTWLcyo3DLBFNVYq6W02U1+XZYAkmrWDHHlqvQstRKoirXXcM9tv6x7bN7bKrqQar9Y6"
    "/CG3y3K9z/eubsx1NIlA7HJH28n9XsL39/e6LMvy8vLytI6Xl5fN/U6iPen4tLQnJWdbW2nvaFtL"
    "xwcAADAy80k0AHB6JSdjkyhny7nquVBSp3QdV9V5/myVOevYr+esjRYJx1r8bRgTY2gZKiahGRVo"
    "gF7WvjuIty7i1cVNUuZmpNRcpVVqpr7ukUS7MPpB3ltspV+vv4PUO8XYj3CmdjKlVbImZj1SyUCN"
    "CbYjuUlNAAAAAPr8SaJped8LNxYAtKpxnvTPedLr6JlAu9/vokPuR/l+uOrH0TBH9/+1hnWmDBkd"
    "dVhn72GXV/1nGCegR62JqGoh3rqIt41WM0pKmalKa6a+LotXidY7kXZ0Y2H1IMc5V4Fm5YbYSpyo"
    "T/I8GUqmlKzDr+7slUBLnU01Zx0+C98PoyQCAQDtWLtuJt66iLcuZubFlb+Gc/YcJqPhwLJ2kANo"
    "LzfJlZLgKkmk1T5/tejH1Tp6P/SJJZ3ULKlIw3x6V/cBo7P2sJ946yLeNqhIq8fFlmuWvh6+E01j"
    "AsnqQY5nJCkxityZGlP2/dqzQZbI6Udq3FfrsJJIyz3ftR42mToL6CjDOnsP41yW8z5riA8AAAC/"
    "MbEAAGTKmalR4zpaOEoISiS/rCTSAADjqvWwP3YCrlTE+xvx/mYtXke6Iq32MM4eVVp+tdXVukK/"
    "99txfQkZva/mkmhWD3IgV6gaSaKiKaWNbdtWdyL0f94yDi19Qbr930gyGejvE6Ml1FpWfOUMF7Va"
    "kaahwosKNAAAAFvMJdGAGUkMf5VoQyLJNFJfoIf/gOVsuX3l2lHCzf+ZxskA9skXS8mR1CGjGlh7"
    "r5i1eIGRSD3sbzVJEPE+tyuNeJ/braW0Iq31RAL7e5B1XbcWVVp+ZVhpOznLj9RXs0k0qwf5rHgX"
    "GgAtUoaAakqgzVqRJtmm326v9qhAAwAAJY5ejO+SU6UTBGijra9mk2gAAOQ6S6TtH65oSaCdsVaV"
    "ZmWGUUsVXZZiBWbivk9CD22uft/aqPE6R1Xo9/v9qYq95vd+KN5QnL1Z2x+uKtI0z+oZSgjFvrcr"
    "loaROLF92i+XkzCr2ddhkmjWDvLR+ZWCFm5EAcxl/y41/7tB8znLTz6VJlDO2stJ0EnH57eZ2p6W"
    "yq5Q3FriAwAAbZQONXRCQxf9pJP7fY8kmlRfQ3r0VX0SrXWmuHR9rcdUAwDyhSaqsMpaVRryUX0G"
    "6HX1nk7/NSe9H+jMEu/ZRHI1Yw/F4VfGuZ+Hij+0b1+tDyT9+3OLFWmO+7mGijIpoT7VTr6VUJ9E"
    "u0pKvb29LcsyzkE+GrYrANSlvZJJe3ut1qO9PQAA0IbUy+99oeRbz6TbiH1Vn0QDAAAAAOusTbQ1"
    "Srxa4r+qjIudabwXa/uDpRFiV+/6GrkCLSTUVw0VasMm0awd5AAAAAAAAClGSq5d0dBXs0k0jWOY"
    "AQAAAOCIe53M1cRbscvVNmq8vaXGpaVf1vYHly+4qkiLXa6G2Gor9660nhMESMuZcVMLs0k0fye/"
    "3+9PO5q1gxzAXG6321b7fMM6dBmlHwAAAMCszCbRNPn8/NwsjbkGIMclRlLeX3G73bbH4xGdVBll"
    "HTlarKOFUfoBAEh3NitkznK1jRqvNVr6ZW1/iL0vt3D/brFK68oIfVKfRPOHbV7t7D0OcgsHIAB5"
    "+8SIP+PvGZesik1ujbAOt57URF1oHT2TUZL9AAAAAGCH+iRabIIq9saEGxgAUvaJkdSZlFLOWSOs"
    "IzdRd7QOiaqu3M9K9gMAMDZr9yejxmuNln5Z2x9GMsI7z3wj9Ul9Eg0ANHMXDlcXECWJnxHWkZqo"
    "O1vHWVVXqP39sn4f/M+c9UuyHwAAAABsWbeNSS4BoIVRXsI/wjpaJbZIoAEAAADjIIkGAAAAAAAA"
    "XPindwAAAAAAAACAdrwTDQAAAGjIn33eYcZ3ADOofQ7kHIuaSKIBAAAAjbibO/9m7vPzc/v8/Ny4"
    "yQMwsrNzoIX2Ad6JBgAAAFS2v4ELJcpCN38AYF3tcyDnWLRCEg0AAACoKPXGjRs9ACOpeQ7MOV9y"
    "jkWJP0k0yhsBAACAOlJv1iSvzVNuRAGghprnwNLKNdjTMwFKJRoAAAAwqJiKC6oyAACIQxINAAAA"
    "GFhMxQUJNAAArk2RRIt5ySDq8S/c+BuEsa/Oi+MEaI/jrgzfWX2x/8ZjX50XxwnQ3ujH3WUSbfQN"
    "UJPENOWU15fRsP16Tlffc93WaNhXrkj+PWe4oZihj471vvr7du7xaGk7cH2Vj+ur/jRsP66vbNCw"
    "r1zh+irNDH10rPd1xuurFqaoRAMs40LtGdvDLgsX0trV3v+5SAIwC64nnrE97OL6qhzXV0hhKonW"
    "4+QufVKy/OTZwgk6dh/hRBZH6umF//mSNgBtLJwb8R9uFP/G9VVfFs4hXF/J4voKuGbh3Ij/zHR9"
    "9SeJlnvxoWXntnzx1NJMOzfQAheu5VLP35zH+tLyvd9L6v7H9dUcOC8Bsri+Ksf1lS1avvd7sbT/"
    "mapEAwAAAAAAAHr4p3cAAAAAAAAAgHb/B2+BdqY4ClVbAAAAAElFTkSuQmCC"
)
_DINO_RESTART_B64 = "iVBORw0KGgoAAAANSUhEUgAAACQAAAAgCAQAAADQmBIFAAAAZklEQVR4Xu3WMQoAIAxDUe/Y+58jYwV1CwQJWQT5o/DAoaWjV2i/LRym/A5FjEsR41LPQchByEHwIVAEC4gZpghmSDP8egXpr/hQZaAKQFQe+pBOQAblDC336qrlPpSg0MEjInbWTLFFmwc8TpTAAAAAAElFTkSuQmCC"
_DINO_RESTART_NIGHT_B64 = "iVBORw0KGgoAAAANSUhEUgAAACQAAAAgCAYAAAB6kdqOAAAA10lEQVR4nO2YTQrEIAyFY5lFDvmOl0Nm11kURcowiRirFN9K+hO/5qmxJqrEzCdNkKqm3C4NZj5FZAYPAShQx2wYIiIRKe6k2TC1AFwZWknvAgIQxVHUnaFoqBDLIqE+UZ0CoPtsrd/xzmRXhrwZ+PecN4YJ1GKHlQVPLLdlvzq0LMnXWj4qZFBHrvTdQNFlpwtoRA18V+kYoQ1kqWkdGlHd7zIzFDmTPLFclkVAeWO4LXtq373coN5AljaQpUNV0xMLnqX8f38QXacPM6Hqw4ZU31jhOOYLpM5TVvBJRHkAAAAASUVORK5CYII="

def _dino_pixmap(b64str):
    import base64 as _b64
    pm = QPixmap()
    pm.loadFromData(_b64.b64decode(b64str))
    return pm

class DinoGame(QWidget):
    W, H = 600, 150
    GROUND_BOTTOM = 140
    HORIZON_Y = 127
    DINO_X = 50

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setFixedSize(self.W, self.H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._sheet = _dino_pixmap(_DINO_SHEET_B64)
        self._sheet_night = _dino_pixmap(_DINO_SHEET_NIGHT_B64)
        self._restart = _dino_pixmap(_DINO_RESTART_B64)
        self._restart_night = _dino_pixmap(_DINO_RESTART_NIGHT_B64)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._reset()

    # ---- state ----
    def _reset(self):
        self.dino_y = 93  # top of standing trex, ground bottom 140 - 47
        self.vy = 0.0
        self.jumping = False
        self.ducking = False
        self.speed_drop = False
        self.obstacles = []  # cactus / ptero dicts
        self.clouds = [{"x": 150 + i * 220, "y": 30 + (i * 37) % 40} for i in range(3)]
        self.stars = [{"x": i * 130 + 40, "y": 20 + (i * 29) % 50, "k": i % 3} for i in range(5)]
        self.horizon_x = [0, 600]
        self.horizon_src = [2, 602]
        self.spawn_in = 60
        self.score = 0
        self.hi = int(self.store.get("dino_high", 0) or 0)
        self.dead = False
        self.anim = 0
        self.flash = 0
        self.paused = False
        self.jumps = 0
        self.dodged = 0
        self.slow = False

    # ---- loop ----
    def showEvent(self, e):
        self._timer.start(16)
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _tick(self):
        if self.paused:
            self.update()
            return
        if not self.dead:
            self.score += 1
            if self.score % 100 == 0:
                self.flash = 30
            if self.flash > 0:
                self.flash -= 1
            self.anim += 1
            speed = min(13.0, 6.0 + self.score * 0.001) * (0.5 if self.slow else 1.0)
            # trex physics: Chrome jump -10, gravity 0.6
            if self.jumping:
                self.dino_y += self.vy
                self.vy += 0.6 * (3 if self.speed_drop else 1)
                if self.dino_y >= 93:
                    self.dino_y = 93
                    self.jumping = False
                    self.vy = 0.0
                    self.speed_drop = False
            # obstacles
            for o in self.obstacles:
                o["x"] -= speed
                if not o.get("counted") and o["x"] + o["w"] < self.DINO_X:
                    o["counted"] = True
                    self.dodged += 1
            self.obstacles = [o for o in self.obstacles if o["x"] + o["w"] > -10]
            self.spawn_in -= 1
            if self.spawn_in <= 0:
                import random as _r
                if self.score > 450 and _r.random() < 0.25:
                    y = _r.choice([100, 75, 50])  # low=jump, mid=jump, high=duck/run
                    self.obstacles.append({"kind": "ptero", "x": self.W + 10, "w": 46, "h": 40, "y": y})
                else:
                    large = _r.random() < 0.4
                    count = _r.choice([1, 1, 2, 3])
                    if large and speed < 6:
                        count = 1
                    if not large and speed < 3:
                        count = 1
                    w = (25 if large else 17) * count
                    h = 50 if large else 35
                    y = 90 if large else 105
                    self.obstacles.append({"kind": "cactus", "x": self.W + 10, "w": w, "h": h, "y": y, "count": count, "large": large})
                self.spawn_in = _r.randint(45, 95)
            # clouds + horizon scroll
            for c in self.clouds:
                c["x"] -= 1.0
                if c["x"] < -60:
                    import random as _r
                    c["x"] = self.W + 20
                    c["y"] = _r.randint(30, 70)
            for s in self.stars:
                s["x"] -= 0.5
                if s["x"] < -10:
                    s["x"] = self.W + 20
            for i in range(2):
                self.horizon_x[i] -= speed
                if self.horizon_x[i] <= -600:
                    import random as _r
                    self.horizon_x[i] += 1200
                    self.horizon_src[i] = _r.choice([2, 602])
            # collision (shrunk boxes, like Chrome's collision boxes)
            if self.ducking and not self.jumping:
                dx0, dx1 = self.DINO_X + 2, self.DINO_X + 57
                dy0, dy1 = 112, 138
            else:
                dx0, dx1 = self.DINO_X + 5, self.DINO_X + 40
                dy0, dy1 = self.dino_y + 5, self.dino_y + 42
            for o in self.obstacles:
                ox0, ox1 = o["x"] + 3, o["x"] + o["w"] - 3
                oy0, oy1 = o["y"] + 3, o["y"] + o["h"] - 3
                if dx0 < ox1 and dx1 > ox0 and dy0 < oy1 and dy1 > oy0:
                    self.dead = True
                    try:
                        self.store.set("dino_last", self.score)
                    except Exception:
                        pass
                    if self.score > self.hi:
                        self.hi = self.score
                        try:
                            self.store.set("dino_high", self.hi)
                        except Exception:
                            pass
                    try:
                        self.store.set("dino_games", int(self.store.get("dino_games", 0) or 0) + 1)
                        self.store.set("dino_total_jumps", int(self.store.get("dino_total_jumps", 0) or 0) + self.jumps)
                        if self.dodged > int(self.store.get("dino_best_dodged", 0) or 0):
                            self.store.set("dino_best_dodged", self.dodged)
                    except Exception:
                        pass
                    break
        self.update()

    # ---- input ----
    def _jump(self):
        if self.dead:
            self._reset()
        elif not self.jumping:
            self.jumping = True
            self.jumps += 1
            self.vy = -10.0
            self.speed_drop = False

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Space, Qt.Key.Key_Up, Qt.Key.Key_W):
            self._jump()
        elif k in (Qt.Key.Key_Down, Qt.Key.Key_S):
            self.ducking = True
            if self.jumping:
                self.speed_drop = True
        elif k == Qt.Key.Key_P:
            self.paused = not self.paused
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.paused:
            self.paused = False
        elif k in (Qt.Key.Key_R, Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.dead:
            self._reset()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_S):
            self.ducking = False
        else:
            super().keyReleaseEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.dead and (self.W - 36) // 2 <= e.position().x() <= (self.W + 36) // 2 and 80 <= e.position().y() <= 112:
                self._reset()
            else:
                self._jump()
        super().mousePressEvent(e)

    # ---- drawing: real Chrome sprites, 1:1, no scaling ----
    def _draw_sprite(self, p, sheet, sx, sy, sw, sh, dx, dy):
        p.drawPixmap(dx, dy, sheet, sx, sy, sw, sh)

    def paintEvent(self, e):
        night = (self.score // 700) % 2 == 1
        sheet = self._sheet_night if night else self._sheet
        bg = QColor("#121212") if night else QColor("#FFFFFF")
        fg = QColor("#E8E8E8") if night else QColor("#535353")
        p = QPainter(self)
        p.fillRect(self.rect(), bg)
        # moon + stars at night, clouds by day
        if night:
            phase = (self.score // 700) % 7
            mx = 484
            mw = 20
            for i in range(phase):
                mw = 40 if i == 3 else 20
                mx += mw
            mw = 40 if phase == 3 else 20
            self._draw_sprite(p, sheet, mx, 2, mw, 40, 450, 15)
            for s in self.stars:
                self._draw_sprite(p, sheet, 645, 2 + s["k"] * 9, 9, 9, int(s["x"]), int(s["y"]))
        else:
            for c in self.clouds:
                self._draw_sprite(p, sheet, 86, 2, 46, 14, int(c["x"]), int(c["y"]))
        # horizon line, two 600px segments scrolling
        for i in range(2):
            self._draw_sprite(p, sheet, self.horizon_src[i], 54, 600, 12, int(self.horizon_x[i]), self.HORIZON_Y)
        # obstacles
        for o in self.obstacles:
            if o["kind"] == "ptero":
                frame = 0 if (self.anim // 6) % 2 == 0 else 46
                self._draw_sprite(p, sheet, 134 + frame, 2, 46, 40, int(o["x"]), int(o["y"]))
            else:
                if o["large"]:
                    sx = 332 + ((2 ** (o["count"] - 1) - 1) * 25)
                    self._draw_sprite(p, sheet, sx, 2, 25 * o["count"], 50, int(o["x"]), int(o["y"]))
                else:
                    sx = 228 + ((2 ** (o["count"] - 1) - 1) * 17)
                    self._draw_sprite(p, sheet, sx, 2, 17 * o["count"], 35, int(o["x"]), int(o["y"]))
        # trex: jumping / crashed / ducking / running, exact Chrome frames
        if self.dead:
            self._draw_sprite(p, sheet, 848 + 5 * 44, 2, 44, 47, self.DINO_X, int(self.dino_y))
        elif self.jumping:
            self._draw_sprite(p, sheet, 848, 2, 44, 47, self.DINO_X, int(self.dino_y))
        elif self.ducking:
            frame = 0 if (self.anim // 5) % 2 == 0 else 59
            self._draw_sprite(p, sheet, 1112 + frame, 19, 59, 30, self.DINO_X, 110)
        else:
            frame = 88 if (self.anim // 5) % 2 == 0 else 132
            self._draw_sprite(p, sheet, 848 + frame, 2, 44, 47, self.DINO_X, int(self.dino_y))
        # speed + NEW BEST (100-pack)
        p.setPen(fg); p.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        _spd = min(13.0, 6.0 + self.score * 0.001) * (0.5 if self.slow else 1.0)
        p.drawText(10, 20, f"Speed {_spd:.1f}  Jumps {self.jumps}  Dodged {self.dodged}  Time {int(self.score / 60)}s")
        if not self.dead and self.score > self.hi and self.hi > 0:
            p.drawText(10, 38, "NEW BEST!")
        if self.paused:
            p.setFont(QFont("Consolas", 20, QFont.Weight.Bold))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "PAUSED — P to resume")
        # score (Chrome flashes it at each 100)
        if not (self.flash > 0 and (self.flash // 5) % 2 == 0):
            p.setPen(fg)
            p.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
            p.drawText(self.W - 200, 28, f"HI {self.hi:05d}  {self.score:05d}")
        # game over: real GAME OVER sprite + real restart icon
        if self.dead:
            self._draw_sprite(p, sheet, 655, 15, 191, 11, (self.W - 191) // 2, 50)
            rp = self._restart_night if night else self._restart
            p.drawPixmap((self.W - 36) // 2, 80, rp)
            p.setPen(fg); p.setFont(QFont("Segoe UI", 11))
            p.drawText(QRect(0, 120, self.W, 20), Qt.AlignmentFlag.AlignCenter, f"Score {self.score} · Jumps {self.jumps} · Dodged {self.dodged} · Enter / R to retry")
        p.end()


class DinoDialog(QDialog):
    """Non-modal real-Chrome dino runner — the download keeps running behind it."""

    def __init__(self, parent, store):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Dino Runner — Chrome, play while you wait")
        self.setMinimumSize(640, 240)
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(10)
        t = QLabel("DINO RUNNER"); t.setObjectName("SectionHeader"); v.addWidget(t)
        self.game = DinoGame(store, self)
        v.addWidget(self.game, 0, Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Space / ↑ / W or click = jump · ↓ / S = duck · P = pause · Enter / R = restart")
        self.stats_label = QLabel(""); self.stats_label.setObjectName("Muted"); self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(self.stats_label)
        slow_cb = QCheckBox("Slow mode"); slow_cb.toggled.connect(lambda on: setattr(self.game, "slow", on)); v.addWidget(slow_cb, 0, Qt.AlignmentFlag.AlignCenter)
        hint.setObjectName("Muted"); hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(hint)

    def showEvent(self, e):
        super().showEvent(e)
        try:
            self.setWindowTitle(f"Dino Runner — Chrome, play while you wait (HI {self.game.hi:05d})")
            s = self.store
            self.stats_label.setText(f"Games: {int(s.get('dino_games', 0) or 0)} · Total jumps: {int(s.get('dino_total_jumps', 0) or 0)} · Best dodged: {int(s.get('dino_best_dodged', 0) or 0)} · Last: {int(s.get('dino_last', 0) or 0)}")
        except Exception:
            pass
        self.game.setFocus()


class VersionsPage(QWidget):
    GRID_COLS = 3

    def __init__(self, main):
        super().__init__(); self.main = main
        self.versions, self.load_error = load_versions()
        self.descriptions = load_descriptions()
        self.worker = None; self.selected = None
        self.queue = []
        self.version_cards = []
        self.dlc_cards = []
        self._dlc_note = None
        self._grid_cols = 3
        self._dlc_cols = 3
        # Debounce resize-driven grid reflows: rapid resizes restart the
        # 100ms single-shot timer instead of rebuilding the grids on
        # every resize event.
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow_now)
        # Real install sizes are measured off the GUI thread (see
        # _SizeThread) — this maps version name -> (count QLabel, n_dlc)
        # so the labels update when the numbers land.
        self._size_labels = {}
        self._size_thread = None

        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        toph = QWidget(); th = QHBoxLayout(toph); th.setContentsMargins(16, 20, 16, 4); th.setSpacing(0)
        th.addWidget(page_header("Versions", "Download and manage old ARK builds, 2015 to 2024."))
        outer.addWidget(toph)
        body = QHBoxLayout(); body.setContentsMargins(16, 0, 16, 16); body.setSpacing(12)

        # ---- left: search + version card grid ----
        left = QVBoxLayout(); left.setSpacing(10)
        top_left = FlowLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search versions..."); self.search.textChanged.connect(self._apply_filter)
        top_left.addWidget(self.search, 1)

        self.fav_btn = QPushButton(); self.fav_btn.setFixedSize(38, 38)
        self.fav_btn.setIcon(QIcon(icon("star", 18, "#9A958C"))); self.fav_btn.setToolTip("Toggle Favorite")
        self.fav_btn.clicked.connect(self._toggle_favorite)
        top_left.addWidget(self.fav_btn)
        left.addLayout(top_left)
        # v1.29.1 layout fix: the old single filter row squeezed
        # 2 combos + 2 checkboxes + a label + 3 buttons into one line,
        # so "Sort: Date" clipped to "Sort: D", "Installed only" to
        # "Installed or", "Copy info" to "Copy infc", etc. Split into
        # two rows so every label reads in full, even on narrow windows.
        filt = FlowLayout(); filt.setSpacing(8)
        self.sort_combo = QComboBox(); self.sort_combo.setMinimumWidth(140); self.sort_combo.addItems(["Sort: Date", "Sort: Name", "Sort: DLC count", "Sort: Size est", "Sort: Favorites first"])
        self.sort_combo.currentIndexChanged.connect(self._resort_cards); filt.addWidget(self.sort_combo)
        self.era_combo = QComboBox(); self.era_combo.setMinimumWidth(110); self.era_combo.addItems(["Era: All", "Era: 2015", "Era: 2016", "Era: 2017", "Era: 2018", "Era: 2019", "Era: 2020", "Era: Unknown"])
        self.era_combo.currentIndexChanged.connect(lambda _i: self._reflow_grid(force=True)); filt.addWidget(self.era_combo)
        filt.addStretch(1); left.addLayout(filt)
        # v1.42.0 STEP 2: checkboxes on their own row — the old single row (2 combos + 2 checkboxes)
        # clipped at narrow window widths, same as the v1.29.1 filt3 bug.
        filt_checks = FlowLayout(); filt_checks.setSpacing(8)
        self.installed_cb = QCheckBox("Installed only"); self.installed_cb.toggled.connect(lambda _c: self._reflow_grid(force=True)); filt_checks.addWidget(self.installed_cb)
        self.favonly_cb = QCheckBox("Favorites only"); self.favonly_cb.toggled.connect(lambda _c: self._reflow_grid(force=True)); filt_checks.addWidget(self.favonly_cb)
        filt_checks.addStretch(1); left.addLayout(filt_checks)
        filt_label_row = FlowLayout(); filt_label_row.setSpacing(8)
        self.filter_label = QLabel(""); self.filter_label.setObjectName("Muted"); filt_label_row.addWidget(self.filter_label, 1)
        left.addLayout(filt_label_row)
        # v1.42.0 STEP 2: buttons on their own row, so "Copy info / Random / Clear filters" never
        # squeeze to "opy inf / andon / ear filt" when the window is sized down.
        filt_actions = FlowLayout(); filt_actions.setSpacing(8)
        copy_b = QPushButton("Copy info"); copy_b.setToolTip("Copy the selected build's info to the clipboard"); copy_b.clicked.connect(self._copy_version_info); filt_actions.addWidget(copy_b)
        rand_b = QPushButton("Random"); rand_b.setToolTip("Pick a random build"); rand_b.clicked.connect(self._pick_random); filt_actions.addWidget(rand_b)
        clear_b = QPushButton("Clear filters"); clear_b.clicked.connect(self._clear_filters); filt_actions.addWidget(clear_b)
        filt_actions.addStretch(1); left.addLayout(filt_actions)
        # v1.31.0: "Pick a build below" hint removed at user's order.
        # 101-200: extra filters (137-139, 149)
        filt2 = FlowLayout(); filt2.setSpacing(8)
        # v1.31.0: Prim+ only checkbox removed at user's order.
        # (reflow code uses getattr, so a missing primonly_cb is safe.)
        self.baseonly_cb = QCheckBox("Base only"); self.baseonly_cb.toggled.connect(lambda _c: self._reflow_grid(force=True)); filt2.addWidget(self.baseonly_cb)
        self.dlc5_cb = QCheckBox("5+ DLC"); self.dlc5_cb.toggled.connect(lambda _c: self._reflow_grid(force=True)); filt2.addWidget(self.dlc5_cb)
        self.hideinst_cb = QCheckBox("Hide installed"); self.hideinst_cb.toggled.connect(lambda _c: self._reflow_grid(force=True)); filt2.addWidget(self.hideinst_cb)
        filt2.addStretch(1); left.addLayout(filt2)
        # v1.29.1: filt3 removed at user's order — the 16 extra-action
        # buttons squeezed into one row and clipped to single letters.
        # The underlying _copy_dlc_list_131 etc. methods remain in code
        # but are no longer shown; Copy info / Random / Clear filters
        # below cover the common cases.

        self.count_label = QLabel("0 Builds"); self.count_label.setObjectName("Count")
        left.addWidget(self.count_label)

        self.grid_scroll = QScrollArea(); self.grid_scroll.setWidgetResizable(True)
        self.grid_inner = QWidget()
        self.grid_layout = QGridLayout(self.grid_inner)
        self.grid_layout.setContentsMargins(0, 0, 0, 0); self.grid_layout.setSpacing(10)
        for c in range(self.GRID_COLS):
            self.grid_layout.setColumnStretch(c, 1)
        self.grid_scroll.setWidget(self.grid_inner)
        left.addWidget(self.grid_scroll, 1)
        body.addLayout(left, 2)

        # ---- right: details panel ----
        right = QVBoxLayout(); right.setSpacing(8)

        # Main game card (big): name, status, folder, action buttons.
        # v1.55.0 full-width banner (user choice, Nov 1 01:30): the tiny
        # 90x44 side thumbnail is gone. A FullBleedBanner — same class as
        # version cards, 120px tall, center-cropped, never stretched —
        # sits on TOP of the details panel, full panel width, edge to
        # edge, and updates per build in _refresh_details. It lives in
        # the right column, BEFORE main_card, not inside it, so it is
        # not shrunk by main_card's 10px margins. Text below it is now
        # full width too (no side thumbnail squeezing it into wrapped
        # lines). Cost, accepted by choosing banner: the panel is taller
        # than the v1.48 compact version, so DLCs need a bit more scroll.
        # DLC card art itself stays 120x56, unchanged.
        self.main_banner = FullBleedBanner(art_pixmap_full("base"), height=120, fit=True)
        self.main_art = self.main_banner  # old name, kept for compatibility
        right.addWidget(self.main_banner)
        self.main_card = QFrame(); self.main_card.setObjectName("Card")
        mc = QVBoxLayout(self.main_card); mc.setContentsMargins(10, 10, 10, 10); mc.setSpacing(6)
        header_text = QVBoxLayout(); header_text.setSpacing(2)
        self.name_label = QLabel("Pick a version"); self.name_label.setObjectName("CardHead"); header_text.addWidget(self.name_label)
        self.title_label = QLabel(""); self.title_label.setObjectName("Muted"); self.title_label.setWordWrap(True); header_text.addWidget(self.title_label)
        self.desc_label = QLabel(""); self.desc_label.setObjectName("Muted"); self.desc_label.setWordWrap(True); header_text.addWidget(self.desc_label)
        self.status_label = QLabel(""); self.status_label.setObjectName("Muted"); header_text.addWidget(self.status_label)
        self.folder_label = QLabel(""); self.folder_label.setObjectName("Muted"); self.folder_label.setWordWrap(True); header_text.addWidget(self.folder_label)
        self.mods_label = QLabel(""); self.mods_label.setObjectName("Muted"); self.mods_label.setWordWrap(True); header_text.addWidget(self.mods_label)
        self.prim_label = QLabel(""); self.prim_label.setObjectName("Muted"); self.prim_label.setWordWrap(True); header_text.addWidget(self.prim_label)
        mc.addLayout(header_text)

        btns = FlowLayout(); btns.setSpacing(10)
        self.download_b = QPushButton("Download"); self.download_b.setObjectName("Primary"); self.download_b.setMinimumHeight(34); self.download_b.clicked.connect(self._on_download)
        self.queue_b = QPushButton("Queue"); self.queue_b.setToolTip("Download after the current one finishes")
        self.queue_b.clicked.connect(self._on_queue)
        self.verify_b = QPushButton("Verify"); self.verify_b.setToolTip("Re-check files and repair if needed")
        self.verify_b.clicked.connect(self._on_verify)
        self.verify_b.setEnabled(False)
        self.play_b = QPushButton("Play"); self.play_b.setEnabled(False); self.play_b.clicked.connect(self._on_play)
        self.folder_b = QPushButton("Open Folder"); self.folder_b.setEnabled(False); self.folder_b.clicked.connect(self._on_open_folder)

        self.copyfolder_b = QPushButton("Copy folder"); self.copyfolder_b.setToolTip("Copy the selected build's folder path"); self.copyfolder_b.clicked.connect(self._copy_folder)
        self.viewmods_b = QPushButton("View mods for this build"); self.viewmods_b.setToolTip("Open the Mods tab filtered to mods compatible with this build"); self.viewmods_b.clicked.connect(self._view_mods_for_build)
        # v1.56.0 SLIM details (user choice, Nov 1 01:39): the details panel
        # now shows ONLY Download, Play, Queue as main buttons. Everything
        # else is NOT deleted — it lives in a collapsed "More actions"
        # frame below, one click away, so the panel is short by default
        # and DLCs + log fit on screen, but Verify / Open Folder / Copy
        # folder / View mods / per-build Launch args / Presets are still
        # there when you need them. Button objects keep their same names
        # and signals, so _refresh_details / _on_finished enable/disable
        # logic is unchanged — hidden buttons still get enabled/disabled
        # correctly, they are just not visible until More is opened.
        # Clear log / Save log stay with the log below (they are log
        # controls, not build actions, and were not part of the slim ask).
        for _b in (self.queue_b, self.verify_b, self.play_b, self.folder_b, self.copyfolder_b, self.viewmods_b):
            try: _b.setMinimumHeight(32)
            except Exception: pass
        try: self.play_b.setMinimumHeight(34)
        except Exception: pass
        main_btns = FlowLayout(); main_btns.setSpacing(10)
        main_btns.addWidget(self.download_b); main_btns.addWidget(self.play_b); main_btns.addWidget(self.queue_b); main_btns.addStretch(1)
        mc.addLayout(main_btns)
        self.more_b = QPushButton("More actions \u25be"); self.more_b.setToolTip("Show Verify, Open Folder, Copy folder, View mods, and per-build Launch args")
        mc.addWidget(self.more_b)
        self.advanced_frame = QFrame(); self.advanced_frame.setVisible(False)
        adv = QVBoxLayout(self.advanced_frame); adv.setContentsMargins(0, 0, 0, 0); adv.setSpacing(6)
        adv_btns1 = FlowLayout(); adv_btns1.setSpacing(10)
        adv_btns1.addWidget(self.verify_b); adv_btns1.addWidget(self.folder_b); adv_btns1.addStretch(1)
        adv.addLayout(adv_btns1)
        adv_btns2 = FlowLayout(); adv_btns2.setSpacing(10)
        adv_btns2.addWidget(self.copyfolder_b); adv_btns2.addWidget(self.viewmods_b); adv_btns2.addStretch(1)
        adv.addLayout(adv_btns2)
        # Per-build launch profile: custom args saved per version + named presets.
        prof_row = FlowLayout(); prof_row.setSpacing(8)
        prof_lab = QLabel("Launch args:"); prof_lab.setObjectName("Muted")
        prof_row.addWidget(prof_lab)
        self.profile_edit = QLineEdit()
        self.profile_edit.setPlaceholderText("Custom args for this build (empty = use Settings default)")
        self.profile_edit.textChanged.connect(self._on_profile_changed)
        prof_row.addWidget(self.profile_edit, 1)
        adv.addLayout(prof_row)
        # v1.44.0: preset combo + Presets button on their own row, so the
        # launch-args row does not force the details panel wider than
        # its allocated width at narrow window sizes.
        prof_row2 = FlowLayout(); prof_row2.setSpacing(8)
        self.preset_combo = QComboBox(); self.preset_combo.setMinimumWidth(90)
        self.preset_combo.setToolTip("Apply a named preset to this build's launch args")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_picked)
        prof_row2.addWidget(self.preset_combo)
        manage_b = QPushButton("Presets"); manage_b.setToolTip("Add, edit or delete launch arg presets")
        manage_b.clicked.connect(self._on_manage_presets)
        prof_row2.addWidget(manage_b); prof_row2.addStretch(1)
        adv.addLayout(prof_row2)
        mc.addWidget(self.advanced_frame)
        def _toggle_more(_c=False, _f=self.advanced_frame, _b=self.more_b):
            _vis = not _f.isVisible()
            _f.setVisible(_vis)
            try: _b.setText("Less actions \u25b4" if _vis else "More actions \u25be")
            except Exception: pass
        self.more_b.clicked.connect(_toggle_more)
        self._toggle_more = _toggle_more
        right.addWidget(self.main_card)

        # DLC cards (little) below the main game card
        self.dlc_header = QLabel("DLC"); self.dlc_header.setObjectName("SectionHeader"); right.addWidget(self.dlc_header); right.addWidget(hair())
        self.dlc_scroll = QScrollArea(); self.dlc_scroll.setWidgetResizable(True)
        self.dlc_inner = QWidget()
        self.dlc_layout = QGridLayout(self.dlc_inner)
        self.dlc_layout.setContentsMargins(0, 0, 0, 0); self.dlc_layout.setSpacing(10)
        for c in range(self.GRID_COLS):
            self.dlc_layout.setColumnStretch(c, 1)
        self.dlc_scroll.setWidget(self.dlc_inner)
        right.addWidget(self.dlc_scroll, 1)

        prow = FlowLayout(); prow.setSpacing(10)
        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0); self.progress_bar.setVisible(False); self.progress_bar.setFixedHeight(14)
        prow.addWidget(self.progress_bar, 1)
        self.game_b = QPushButton("🎮 Play"); self.game_b.setVisible(False)
        self.game_b.setToolTip("Play dino runner while you wait")
        self.game_b.clicked.connect(self._on_play_game)
        prow.addWidget(self.game_b)
        self.cancel_b = QPushButton("Cancel"); self.cancel_b.setVisible(False)
        self.cancel_b.clicked.connect(self._on_cancel)
        prow.addWidget(self.cancel_b)
        right.addLayout(prow)
        # v1.44.0: Clear/Save log on their own row, so they do not force the details panel wide.
        prow2 = FlowLayout(); prow2.setSpacing(10)
        clearlog_b = QPushButton("Clear log"); clearlog_b.clicked.connect(lambda: (self.log.clear(), self.log.setVisible(False))); prow2.addWidget(clearlog_b)
        savelog_b = QPushButton("Save log"); savelog_b.clicked.connect(self._save_log); prow2.addWidget(savelog_b); prow2.addStretch(1)
        right.addLayout(prow2)

        self.progress_label = QLabel(""); self.progress_label.setObjectName("StatusText"); self.progress_label.setWordWrap(True); right.addWidget(self.progress_label)
        self.queue_label = QLabel(""); self.queue_label.setObjectName("StatusText"); self.queue_label.setWordWrap(True); self.queue_label.setVisible(False)
        right.addWidget(self.queue_label)
        self.log = QPlainTextEdit(); self.log.setObjectName("Log"); self.log.setReadOnly(True); self.log.setMaximumBlockCount(500); self.log.setMinimumHeight(180); self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth); self.log.setVisible(False); right.addWidget(self.log, 1)
        body.addLayout(right, 1)
        outer.addLayout(body)

        self._populate()
        if not self.selected and self.version_cards and self.main.store.get("auto_select_first_build", True):
            self.selected = self.version_cards[0][1]
            self._refresh_details()
        if self.load_error: self._log(self.load_error)
        if not ART_DIR.is_dir() or not any(ART_DIR.glob("*.jpg")):
            self._log("No art images in the art/ folder next to the launcher — cards use drawn icons. The v1.26 zip includes generated art/*.jpg banners; if you run from source, copy the art folder next to the .py.")

    def _log(self, msg):
        # Log box stays hidden until the first message, so it isn't
        # an empty box on screen for no reason.
        self.log.appendPlainText(msg)
        if not self.log.isVisible():
            self.log.setVisible(True)

    # ---- version card grid ----
    def _build_version_card(self, v, steam_dir, is_fav):
        # v1.28.13: parent immediately — a parentless card is a
        # top-level window until _reflow_grid adds it, and Windows
        # showed those as flashing 216x244 windows before main show.
        card = ClickableCard(self)
        card.setObjectName("Card")
        # Full-bleed layout: banner touches every edge of the card's top,
        # text lives in its own padded block underneath. No 12px frame
        # around the image anymore — that inset is what made the old
        # cards look small even when the art was there.
        lay = QVBoxLayout(card); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        # Era-specific banner: art of the latest DLC in this build, falling
        # back to base art, then to the drawn icon.
        era_key = era_art_key(v)
        full = art_pixmap_full(era_key)
        if full is None:
            full = art_pixmap_full("base")
        if full is not None:
            lay.addWidget(FullBleedBanner(full, height=(80 if self.main.store.get("compact_cards") else 120)))
        else:
            lay.addWidget(art_label("base", 150, 68, "planet"))
        text = QWidget(); tl = QVBoxLayout(text); tl.setContentsMargins(12, 10, 12, 12); tl.setSpacing(6)
        lay.addWidget(text)
        lay = tl
        card.setMinimumWidth(170)
        name = v.get("name", "Unnamed build")
        entry = self.descriptions.get(name, {}) if isinstance(self.descriptions, dict) else {}
        title = entry.get("title", "") if isinstance(entry, dict) else ""
        t = QLabel(title or name); t.setObjectName("RowTitle"); t.setWordWrap(True)
        lay.addWidget(t)
        ver, date = _version_and_date(name)
        if not self.main.store.get("show_card_dates", True):
            date = ""
        # Date only, like every other card — the version number (when a
        # build has a verified one) lives in the details panel.
        sub = QLabel(date or ver); sub.setObjectName("Muted"); sub.setWordWrap(True)
        if not self.main.store.get("show_card_dates", True):
            sub.setVisible(False)
        lay.addWidget(sub)
        lay.addStretch(1)
        bottom = FlowLayout(); bottom.setSpacing(6)
        n_dlc = sum(1 for k in DLC_ORDER if v.get(k))
        exe = game_exe_for(steam_dir, v, self.main.store) if steam_dir else None
        installed = bool(exe and Path(exe).is_file())
        # Show the estimate immediately — the real size is measured in a
        # background thread (_SizeThread) so the UI never freezes.
        size_txt = f"~{_estimate_size_gb(v):.0f} GB" if self.main.store.get("show_estimates", True) else "Size hidden"
        count = QLabel(f"{n_dlc} DLC{'s' if n_dlc != 1 else ''} · {size_txt}" if n_dlc else f"Base only · {size_txt}")
        count.setObjectName("Muted")
        bottom.addWidget(count)
        if installed:
            self._size_labels[name] = (count, n_dlc)
        bottom.addStretch(1)
        # Star badge always exists — toggled via setVisible so a favorite
        # flip never rebuilds the card (rebuilding all 97 cards flickers).
        star = QLabel("★"); star.setStyleSheet(f"color: {GOLD}; font-weight: 700;")
        star.setVisible(is_fav)
        bottom.addWidget(star)
        card._star = star
        card._installed = installed
        if installed and not self.main.store.get("hide_installed_badge", False):
            badge = QLabel("Installed"); badge.setStyleSheet(f"color: {SUCCESS}; font-weight: 700;")
            bottom.addWidget(badge)
        lay.addLayout(bottom)
        card.clicked.connect(lambda _c=False, vv=v: self._select_version(vv))
        return card

    def _populate(self):
        # Selection-preserving rebuild (adapted from the old list's restore_row):
        # the selected version dict stays selected; cards are rebuilt around it
        # and the matching card is re-highlighted, so a favorite toggle never
        # jumps the selection.
        prev = self.selected.get("name", "") if self.selected else ""
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.version_cards = []
        self._size_labels = {}
        favs = self.main.store.get("favorites", [])

        # Sort: favorites first (chronological among themselves), then the
        # rest chronologically — a timeline, oldest to newest.
        sorted_versions = sorted(
            self.versions,
            key=lambda v: (
                v.get("name", "") not in favs,
                *parse_version_date(v.get("name", "")),
                v.get("name", ""),
            ),
        )

        steam_dir = steam_dir_for(self.main.store)
        for v in sorted_versions:
            name = v.get("name", "Unnamed build")
            card = self._build_version_card(v, steam_dir, name in favs)
            self.version_cards.append((card, v))
        self._reflow_grid(force=True)

        if prev:
            for card, v in self.version_cards:
                if v.get("name", "") == prev:
                    self.selected = v
                    break
        self._mark_selected_card()
        self.count_label.setText(f"{len(self.versions)} Builds Loaded")
        self._measure_sizes()

    def _measure_sizes(self):
        """Measure real install sizes off the GUI thread — the cards show
        the estimate until the numbers land via _on_sized. Safe to call
        often; a running worker is left alone and its results land via
        _on_sized, which re-triggers this for anything still uncached."""
        try:
            if self._size_thread is not None and self._size_thread.isRunning():
                return
        except Exception:
            pass
        steam_dir = steam_dir_for(self.main.store)
        jobs = []
        for v in self.versions:
            name = v.get("name", "Unnamed build")
            if name in _SIZE_CACHE:
                continue  # already measured this session
            exe = game_exe_for(steam_dir, v, self.main.store) if steam_dir else None
            if exe and Path(exe).is_file():
                gdir = game_dir_for(self.main.store, v, steam_dir)
                if gdir.is_dir():
                    jobs.append((name, str(gdir)))
        if jobs:
            self._size_thread = _SizeThread(jobs)
            self._size_thread.sized.connect(self._on_sized)
            self._size_thread.start()

    def _on_sized(self, name, gb):
        _SIZE_CACHE[name] = gb
        entry = self._size_labels.get(name)
        if entry:
            label, n_dlc = entry
            try:
                label.setText(f"{n_dlc} DLC{'s' if n_dlc != 1 else ''} · {gb:.1f} GB" if n_dlc else f"Base only · {gb:.1f} GB")
            except RuntimeError:
                pass  # card was rebuilt while measuring
        # Dashboard reads the same cache — refresh it now that a real
        # number landed (its refresh does zero disk I/O).
        try:
            self.main.dashboard.refresh()
        except Exception:
            pass

    def _reflow_grid(self, force=False):
        """Responsive version grid: pick a column count from the panel's
        actual width so cards never get clipped. 2 cols minimum, 4 max."""
        if not force:
            # Debounced: resize events restart the timer; the reflow runs
            # 100ms after resizes settle.
            self._reflow_timer.start(100)
            return
        self._do_reflow_grid(force=True)

    def _do_reflow_grid(self, force=False):
        """Responsive version grid: pick a column count from the panel's
        actual width so cards never get clipped. 2 cols minimum, 4 max."""
        if not hasattr(self, "grid_layout") or not hasattr(self, "grid_scroll"):
            return
        avail = self.grid_scroll.viewport().width()
        if avail and avail > 0:
            # v1.44.0: min 1 col, not 2 — at narrow windows 2 cols (2x200=400px)
            # forced the whole page wider than the window and cut the right
            # details panel off-screen. 1 col lets the left shrink first.
            cols = max(1, min(4, avail // 200))
        else:
            cols = 3
        if not force and getattr(self, "_grid_cols", 3) == cols and self.grid_layout.count() > 0:
            return
        self._grid_cols = cols
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)
        for c in range(4):
            self.grid_layout.setColumnStretch(c, 1 if c < cols else 0)
        row = col = 0
        # Filter from the search text, NOT from widget visibility:
        # a fresh card reports isHidden()==True AND isVisible()==False
        # before it is ever placed, so visibility checks skip every card.
        # Visibility is set explicitly every reflow: matching cards show
        # and join the grid, non-matching ones hide (takeAt() alone
        # leaves them painted over the grid as orphans).
        query = self.search.text().lower() if hasattr(self, "search") else ""
        favs = self.main.store.get("favorites", []) or []
        era = ""
        if hasattr(self, "era_combo"):
            era = self.era_combo.currentText().replace("Era: ", "")
        inst_only = bool(getattr(self, "installed_cb", None) and self.installed_cb.isChecked())
        fav_only = bool(getattr(self, "favonly_cb", None) and self.favonly_cb.isChecked())
        prim_only = bool(getattr(self, "primonly_cb", None) and self.primonly_cb.isChecked())
        base_only = bool(getattr(self, "baseonly_cb", None) and self.baseonly_cb.isChecked())
        dlc5_only = bool(getattr(self, "dlc5_cb", None) and self.dlc5_cb.isChecked())
        hide_inst = bool(getattr(self, "hideinst_cb", None) and self.hideinst_cb.isChecked())
        shown = 0
        for card, v in self.version_cards:
            matches = True
            if query and not search_match(v, query, self.descriptions):
                matches = False
            if era and era != "All":
                y = version_year(v)
                if era == "Unknown" and y != 0:
                    matches = False
                elif era != "Unknown" and str(y) != era:
                    matches = False
            if inst_only and not getattr(card, "_installed", False):
                matches = False
            if fav_only and v.get("name", "") not in favs:
                matches = False
            if prim_only and not v.get("primitive"):
                matches = False
            if base_only and count_dlcs(v) != 0:
                matches = False
            if dlc5_only and count_dlcs(v) < 5:
                matches = False
            if hide_inst and getattr(card, "_installed", False):
                matches = False
            if matches:
                shown += 1
            card.setVisible(matches)
            if not matches:
                continue
            self.grid_layout.addWidget(card, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1

        try:
            self.filter_label.setText(f"{shown} of {len(self.version_cards)} shown")
        except Exception:
            pass
    def _reflow_dlc_grid(self, force=False):
        """Same responsive treatment for the DLC grid (2-3 cols), so the
        narrower details panel can't clip DLC cards either."""
        if not force:
            # Debounced: resize events restart the timer; the reflow runs
            # 100ms after resizes settle.
            self._reflow_timer.start(100)
            return
        self._do_reflow_dlc_grid(force=True)

    def _do_reflow_dlc_grid(self, force=False):
        """Same responsive treatment for the DLC grid (2-3 cols), so the
        narrower details panel can't clip DLC cards either."""
        if not hasattr(self, "dlc_layout") or not hasattr(self, "dlc_scroll"):
            return
        avail = self.dlc_scroll.viewport().width()
        if avail and avail > 0:
            cols = max(2, min(3, avail // 200))
        else:
            cols = 3
        if not force and getattr(self, "_dlc_cols", 3) == cols and self.dlc_layout.count() > 0:
            return
        self._dlc_cols = cols
        while self.dlc_layout.count():
            self.dlc_layout.takeAt(0)
        for c in range(3):
            self.dlc_layout.setColumnStretch(c, 1 if c < cols else 0)
        row = col = 0
        for card in self.dlc_cards:
            self.dlc_layout.addWidget(card, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1
        note = getattr(self, "_dlc_note", None)
        if note is not None:
            # Sits beside the Base game card on the first row.
            self.dlc_layout.addWidget(note, 0, 1, 1, max(1, cols - 1))

    def _reflow_now(self):
        # Fired by the debounce timer after resizes settle: reflow both
        # grids with the usual column-change check.
        self._do_reflow_grid()
        self._do_reflow_dlc_grid()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reflow_grid()
        self._reflow_dlc_grid()

    def _mark_selected_card(self):
        sel_name = self.selected.get("name", "") if self.selected else ""
        for card, v in self.version_cards:
            if v.get("name", "") == sel_name:
                # Border ONLY the card frame: the bare QFrame selector
                # leaked the border onto the card's child labels, so each
                # text line got its own outline. #Card matches the frame
                # itself; the QLabel rule explicitly strips label borders.
                card.setStyleSheet(
                    f"QFrame#Card {{ background: {CARD_HOVER}; border: 2px solid {ACCENT}; border-radius: 12px; }}"
                    " QFrame#Card QLabel { border: none; background: transparent; }")
            else:
                card.setStyleSheet("")

    def _apply_filter(self, text):
        # Reflow reads the search text itself and sets each card's
        # visibility explicitly, so filtered-out cards hide instead of
        # lingering over the grid.
        self._reflow_grid(force=True)

    def _select_version(self, v):
        self.selected = v
        self._refresh_details()

    # ---- DLC include/exclude ----
    def _excluded_for(self, version_name):
        all_ex = self.main.store.get("dlc_excluded", {})
        if isinstance(all_ex, dict) and version_name in all_ex:
            lst = all_ex.get(version_name, [])
            return set(lst) if isinstance(lst, list) else set()
        # No per-version customization yet: fall back to the Settings
        # defaults. Once the user toggles a DLC for this build, its own
        # explicit list is saved and the defaults no longer apply to it.
        defaults = self.main.store.get("default_dlc_excluded", [])
        return set(defaults) if isinstance(defaults, list) else set()

    def _set_excluded_for(self, version_name, excluded_set):
        all_ex = self.main.store.get("dlc_excluded", {})
        if not isinstance(all_ex, dict):
            all_ex = {}
        all_ex[version_name] = sorted(excluded_set)
        self.main.store.set("dlc_excluded", all_ex)

    def _toggle_dlc(self, key):
        if not self.selected:
            return
        # Ignore toggles while a download is running: the worker already
        # snapshotted its depot list, so mid-run changes must not apply.
        if self.worker and self.worker.isRunning():
            return
        name = self.selected.get("name", "")
        excluded = self._excluded_for(name)
        if key in excluded:
            excluded.discard(key)
        else:
            excluded.add(key)
        self._set_excluded_for(name, excluded)
        self._rebuild_dlc_grid(self.selected)

    # ---- DLC card grid ----
    def _build_dlc_card(self, key, icon_name, title, excluded=False, toggleable=True):
        card = ClickableCard(self) if toggleable else QFrame(self)
        card.setObjectName("Card")
        # v1.48.0: DLC cards 150px -> 118px tall, art 150x70 -> 120x56.
        # Same art, same name, same Included/Excluded badge, just shorter —
        # so ~3 DLC rows fit where 2 fit before, in the same scroll area.
        lay = QVBoxLayout(card); lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(2)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(art_label(key, 120, 56, icon_name))
        t = QLabel(title); t.setObjectName("RowTitle"); t.setAlignment(Qt.AlignmentFlag.AlignCenter); t.setWordWrap(True)
        lay.addWidget(t)
        badge = QLabel("Excluded" if excluded else "✓ Included")
        badge.setObjectName("Muted"); badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(badge)
        card.setFixedHeight(118)
        if toggleable:
            card.setToolTip("Click to include / exclude from download")
            if excluded:
                # Visibly dimmed + dashed border so "off" reads at a glance.
                # Scoped to the frame so the border can't leak onto labels.
                card.setStyleSheet(
                    f"QFrame#Card {{ background: {BG}; border: 1px dashed {BORDER}; border-radius: 12px; }}"
                    " QFrame#Card QLabel { border: none; background: transparent; }")
                badge.setStyleSheet(f"color: {FAINT};")
            card.clicked.connect(lambda kk=key: self._toggle_dlc(kk))
        return card

    def _rebuild_dlc_grid(self, v):
        while self.dlc_layout.count():
            item = self.dlc_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.dlc_cards = []
        if v is None:
            self.dlc_header.setText("DLC")
            return
        dlcs = [k for k in DLC_ORDER if v.get(k)]
        excluded = self._excluded_for(v.get("name", "")) & set(dlcs)
        active = len(dlcs) - len(excluded)
        self.dlc_header.setText(f"DLC — {active} of {len(dlcs)} included" if dlcs else "DLC")
        cards = [self._build_dlc_card("base", "planet", "Base game", toggleable=False)]
        cards += [self._build_dlc_card(k, "box", DLC_NAMES[k], excluded=(k in excluded)) for k in dlcs]
        self.dlc_cards = cards
        if not dlcs:
            note = QLabel("No DLCs in this build"); note.setObjectName("Muted")
            note.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._dlc_note = note
        else:
            self._dlc_note = None
        self._reflow_dlc_grid(force=True)

    def _on_profile_changed(self, text):
        if not self.selected: return
        name = self.selected.get("name", "")
        profiles = self.main.store.get("launch_profiles", {}) or {}
        text = (text or "").strip()
        if text: profiles[name] = text
        elif name in profiles: del profiles[name]
        self.main.store.set("launch_profiles", profiles)

    def _sync_preset_combo(self):
        presets = self.main.store.get("launch_arg_presets", {}) or {}
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("Preset…", "")
        for name in presets:
            self.preset_combo.addItem(name, name)
        self.preset_combo.blockSignals(False)

    def _on_preset_picked(self, idx):
        if idx <= 0: return
        name = self.preset_combo.itemData(idx)
        presets = self.main.store.get("launch_arg_presets", {}) or {}
        if name in presets:
            self.profile_edit.setText(presets[name])
        self.preset_combo.setCurrentIndex(0)

    def _on_manage_presets(self):
        dlg = LaunchPresetsDialog(self, self.main.store)
        dlg.exec()
        self._sync_preset_combo()

    def _refresh_details(self):
        if not self.selected:
            try: self.main_banner.setPixmapFull(art_pixmap_full("base"))
            except Exception: pass
            self.name_label.setText("Pick a version"); self.title_label.setText(""); self.desc_label.setText(""); self.status_label.setText(""); self.folder_label.setText(""); self.mods_label.setText(""); self.prim_label.setText("")
            self.play_b.setEnabled(False); self.folder_b.setEnabled(False)
            self._rebuild_dlc_grid(None)
            self._mark_selected_card()
            return

        v = self.selected; name = v.get("name", "")
        # v1.55.0: banner art follows the build (latest DLC, else base).
        # Before v1.55 the details thumbnail never changed — it always
        # showed base art, even for Ragnarok/Genesis builds.
        try:
            _bp = art_pixmap_full(era_art_key(v)) or art_pixmap_full("base")
            self.main_banner.setPixmapFull(_bp)
        except Exception: pass
        # Load this build's launch profile without triggering a save.
        self.profile_edit.blockSignals(True)
        self.profile_edit.setText((self.main.store.get("launch_profiles", {}) or {}).get(name, ""))
        self.profile_edit.blockSignals(False)
        entry = self.descriptions.get(name, {}) if isinstance(self.descriptions, dict) else {}
        title = entry.get("title", "") if isinstance(entry, dict) else ""
        # v1.48.0: title + build year on ONE line, not two. Was:
        #   "Fear in the Isles" (CardHead) + "Oct 2020 build" (Muted below it)
        # Now: "Fear in the Isles — Oct 2020 build". Same info, 1 line saved.
        self.name_label.setText(f"{title} — {name}" if title else name)
        self.title_label.setText("")
        self.desc_label.setText(entry.get("desc", "") if isinstance(entry, dict) else "")
        self._rebuild_dlc_grid(v)

        # Update Fav Button Icon
        is_fav = name in self.main.store.get("favorites", [])
        self.fav_btn.setIcon(QIcon(icon("star", 18, GOLD if is_fav else "#9A958C")))

        steam = steam_dir_for(self.main.store)
        exe = game_exe_for(steam, v, self.main.store) if steam else None
        installed = bool(exe and Path(exe).is_file())
        self.status_label.setText("Status: Installed" if installed else "Status: Not installed")

        if steam:
            game_dir = game_dir_for(self.main.store, v, steam)
            # v1.48.0: show only the tail of the folder path in the panel —
            # full path is still 1 click away via Copy folder, and in the tooltip.
            # Full path wrapped to 2 lines; tail fits on 1 line.
            try:
                _parts = Path(game_dir).parts
                _tail = "\\".join(_parts[-2:]) if len(_parts) >= 2 else str(game_dir)
            except Exception:
                _tail = str(game_dir)
            self.folder_label.setText(f"Folder: …\\{_tail}")
            try: self.folder_label.setToolTip(str(game_dir))
            except Exception: pass
        else:
            self.folder_label.setText("Steam not found.")

        try:
            _mods = mods_for_version(name, load_mods())
            # v1.48.0: count only, not the full name list. The full list was
            # 4-5 wrapped lines in a narrow panel, pushing DLC off-screen.
            # Full list is 1 click away: "View mods for this build" below.
            self.mods_label.setText(f"Compatible mods: {len(_mods)} — tap 'View mods for this build' below for the full list" if _mods else "Compatible mods: none in the catalog — check mods.json")
        except Exception:
            self.mods_label.setText("")
        # Primitive+: the #1 confusion — it is a Total Conversion, not a map,
        # and it did not exist before Jul 2016, so early builds have no Prim+ at all.
        try:
            if not v.get("primitive"):
                self.prim_label.setText("Primitive+: not in this build (did not exist until Jul 2016).")
            elif "primitive" in self._excluded_for(name):
                self.prim_label.setText("Primitive+: EXCLUDED — click its DLC card below to include it.")
            else:
                self.prim_label.setText("Primitive+: Total Conversion — after Play, pick Total Conversion → Primitive Plus in ARK's menu. Most normal mods won't work with it.")
        except Exception:
            self.prim_label.setText("")
        busy = bool(self.worker and self.worker.isRunning())
        self.play_b.setEnabled(installed and not busy)
        self.folder_b.setEnabled(installed and not busy)
        self.download_b.setEnabled(not busy)
        self.verify_b.setEnabled(installed and not busy)
        self._mark_selected_card()

    def _toggle_favorite(self):
        if not self.selected: return
        name = self.selected.get("name", "")
        favs = self.main.store.get("favorites", [])
        if name in favs: favs.remove(name)
        else: favs.append(name)
        self.main.store.set("favorites", favs)
        # Re-sort the EXISTING cards in place — rebuilding all 97 cards
        # blanks the grid and flickers. Selection is preserved because
        # no widget is deleted.
        self._resort_cards()
        self._refresh_details()

    def _resort_cards(self):
        """Favorites-first chronological sort of the live cards, no
        rebuild: updates each card's star and reflows the grid."""
        favs = self.main.store.get("favorites", [])
        mode = "date"
        if hasattr(self, "sort_combo"):
            txt = self.sort_combo.currentText()
            mode = "name" if "Name" in txt else "dlc" if "DLC" in txt else "size" if "Size" in txt else "favs" if "Favorites" in txt else "date"
        if mode == "favs":
            self.version_cards.sort(key=lambda cv: (cv[1].get("name", "") not in favs, *parse_version_date(cv[1].get("name", "")), cv[1].get("name", "")))
        else:
            self.version_cards.sort(key=lambda cv: version_sort_key(cv[1], mode))
        for card, v in self.version_cards:
            star = getattr(card, "_star", None)
            if star is not None:
                try:
                    star.setVisible(v.get("name", "") in favs)
                except RuntimeError:
                    pass
        self._do_reflow_grid(force=True)
        self._mark_selected_card()
        self.count_label.setText(f"{len(self.versions)} Builds Loaded")

    def _view_mods_for_build(self):
        if not self.selected:
            return
        try:
            self.main.mods.mod_compat_cb.setChecked(True)
        except Exception:
            pass
        self.main.show_page(2)
    def _copy_folder(self):
        if not self.selected:
            return
        _copy_text(str(game_dir_for(self.main.store, self.selected, steam_dir_for(self.main.store))))
        self.main.set_status("Folder path copied.")
    def _save_log(self):
        dest, _ok = QFileDialog.getSaveFileName(self, "Save log", "launcher-log.txt", "Text files (*.txt)")
        if dest:
            Path(dest).write_text(self.log.toPlainText(), encoding="utf-8")
            self.main.set_status(f"Log saved to {dest}")
    def _copy_version_info(self):
        if not self.selected:
            return
        v = self.selected; name = v.get("name", "")
        info = f"{name} | {count_dlcs(v)} DLCs | ~{_estimate_size_gb(v):.0f} GB estimated | Folder: {game_dir_for(self.main.store, v, steam_dir_for(self.main.store))}"
        _copy_text(info)
        self.main.set_status("Build info copied.")
    def _pick_random(self):
        import random as _r
        pool = [v for _c, v in self.version_cards] or self.versions
        if pool:
            self._select_version(_r.choice(pool))
    def _clear_filters(self):
        try:
            self.search.clear(); self.sort_combo.setCurrentIndex(0); self.era_combo.setCurrentIndex(0)
            self.installed_cb.setChecked(False); self.favonly_cb.setChecked(False)
            for _cb in ("primonly_cb", "baseonly_cb", "dlc5_cb", "hideinst_cb"):
                _w = getattr(self, _cb, None)
                if _w is not None:
                    _w.setChecked(False)
        except Exception:
            pass
        self._reflow_grid(force=True)
    def _visible_versions_101(self):
        return [v for card, v in self.version_cards if card.isVisible()]
    def _copy_dlc_list_131(self):
        if not self.selected: return
        _copy_text(", ".join(DLC_NAMES[k] for k in DLC_ORDER if self.selected.get(k)) or "Base only"); self.main.set_status("DLC list copied.")
    def _copy_title_132(self):
        if not self.selected: return
        e = self.descriptions.get(self.selected.get("name", ""), {}) if isinstance(self.descriptions, dict) else {}
        _copy_text(e.get("title", "") if isinstance(e, dict) else ""); self.main.set_status("Title copied.")
    def _copy_date_133(self):
        if not self.selected: return
        _ver, _date = _version_and_date(self.selected.get("name", "")); _copy_text(_date or _ver); self.main.set_status("Date copied.")
    def _export_build_json_134(self):
        if not self.selected: return
        dest, _ok = QFileDialog.getSaveFileName(self, "Export build", "build.json", "JSON files (*.json)")
        if dest:
            Path(dest).write_text(json.dumps(self.selected, indent=2), encoding="utf-8"); self.main.set_status(f"Build exported to {dest}")
    def _open_steam_page_135(self):
        _open_url("https://store.steampowered.com/app/346110/"); self.main.set_status("Opened ARK Steam page.")
    def _era_counts_136(self):
        counts = count_builds_by_year(self.versions)
        self.filter_label.setText(", ".join(f"{y}: {c}" for y, c in sorted(counts.items())) or "No dated builds")
    def _reverse_cards_140(self):
        self.version_cards.reverse(); self._reflow_grid(force=True); self.main.set_status("Card order reversed.")
    def _select_first_visible_141(self):
        vis = self._visible_versions_101()
        if vis: self._select_version(vis[0])
    def _select_last_visible_142(self):
        vis = self._visible_versions_101()
        if vis: self._select_version(vis[-1])
    def _random_installed_143(self):
        import random as _r
        pool = [v for card, v in self.version_cards if getattr(card, "_installed", False)]
        if pool: self._select_version(_r.choice(pool))
    def _selected_size_144(self):
        if not self.selected: return
        name = self.selected.get("name", "")
        cached = _SIZE_CACHE.get(name, 0.0)
        self.status_label.setText(f"Cached size: {cached:.1f} GB" if cached else "Size not measured yet — background measurement will fill it in.")
    def _selected_dlc_count_145(self):
        if not self.selected: return
        self.status_label.setText(f"{count_dlcs(self.selected)} DLCs for {self.selected.get('name', '')}")
    def _clear_dlc_exclusions_146(self):
        if not self.selected: return
        self._set_excluded_for(self.selected.get("name", ""), set()); self._refresh_details(); self.main.set_status("DLC exclusions cleared for this build.")
    def _export_visible_csv_147(self):
        dest, _ok = QFileDialog.getSaveFileName(self, "Export visible builds", "visible-builds.csv", "CSV files (*.csv)")
        if dest:
            rows = [[v.get("name", ""), version_year(v), count_dlcs(v), round(_estimate_size_gb(v), 1)] for v in self._visible_versions_101()]
            n = write_csv_rows(dest, ["name", "year", "dlcs", "estimate_gb"], rows); self.main.set_status(f"Exported {n} visible builds.")
    def _copy_visible_names_148(self):
        _copy_text("\n".join(v.get("name", "") for v in self._visible_versions_101())); self.main.set_status("Visible build names copied.")
    def _visible_dlcs_150(self):
        total = sum(count_dlcs(v) for v in self._visible_versions_101())
        self.filter_label.setText(f"Visible builds hold {total} DLC entries.")
    def _on_download(self):
        if not self.selected or (self.worker and self.worker.isRunning()): return
        # Disk space pre-check: raw depots and the installed copy coexist
        # until cleanup, so require ~1.6x the estimated size free on both
        # the download drive and the install drive.
        try:
            est = float(_estimate_size_gb(self.selected))
        except Exception:
            est = 0.0
        if est > 0:
            need = est * 1.6
            for label, path in (("download", str(steamcmd_depot_root())), ("install", str(install_root_for(self.main.store, steam_dir_for(self.main.store))))):
                try:
                    free = shutil.disk_usage(path).free / (1024 ** 3)
                except OSError:
                    continue
                if free < need:
                    QMessageBox.warning(self, APP_NAME,
                        f"Not enough disk space on the {label} drive.\n\nThis build needs ~{need:.0f} GB free, but only {free:.1f} GB is available.\nFree up space and try again.")
                    return
        # First download: warn before the black Steam console pops up so it
        # doesn't look like something shady. Only once.
        if not self.main.store.get("steamcmd_warned"):
            QMessageBox.information(self, APP_NAME,
                "Heads up: a black Steam window is about to open.\n\n"
                "That's Valve's official downloader. If it asks you to log in, type your "
                "Steam password and Guard code right in that window — the launcher never "
                "sees or stores it.\n\n"
                "Then just leave the window alone while it downloads.")
            self.main.store.set("steamcmd_warned", True)
        self._start_download(self.selected)

    def _start_download(self, version):
        """Begin downloading a version (called directly or from the queue)."""
        # Auto-backup: zip the Saved folder before the download touches
        # anything. Failures never block the download.
        if self.main.store.get("auto_backup"):
            try:
                ok, msg = _do_backup_now(self.main.store, version)
                self._log(f"Auto-backup: {msg}" if ok else f"Auto-backup skipped ({msg}).")
            except Exception:
                pass
        steam_dir = steam_dir_for(self.main.store)
        install_root = install_root_for(self.main.store, steam_dir)
        self._log(f"Starting download: {version.get('name', '')}")
        self._log("Downloading with SteamCMD. If a SteamCMD window asks for your password or Steam Guard code, type it in there yourself.")
        self.download_b.setEnabled(False); self.play_b.setEnabled(False); self.folder_b.setEnabled(False)
        self.queue_b.setEnabled(False); self.verify_b.setEnabled(False)
        self.progress_bar.setValue(0); self.progress_bar.setVisible(True); self.cancel_b.setVisible(True)
        self.game_b.setVisible(bool(self.main.store.get("show_dino_play", True)))

        excluded = self._excluded_for(version.get("name", ""))
        if excluded:
            names = [DLC_NAMES[k] for k in DLC_ORDER if k in excluded]
            self._log("Skipping excluded DLCs: " + ", ".join(names))
        # Show exactly what is about to be downloaded, so a failure can
        # be pinned to one depot instead of "download failed" in general.
        try:
            depots = version_depots(version, excluded)
            self._log("Depots: " + ", ".join(f"{label} ({depot})" for depot, _man, label, _min in depots))
        except Exception:
            depots = []
        if any(depot == DEPOT_MAP["primitive"] for depot, _m, _l, _g in depots):
            self._log("Primitive+ is in this download (depot 346117). Steam only serves it if the free Primitive+ DLC (app 508150) is claimed on your Steam account — if this download fails on Primitive+, use the 'Retry without Primitive+' button on the error popup and the rest of the build will still install.")
        self.worker = DownloadWorker(version, excluded,
                                     steam_dir=steam_dir,
                                     install_root=install_root,
                                     username=self.main.store.get("steam_username", ""))
        self.worker.progress.connect(self._on_progress)
        self.worker.progress_pct.connect(self.progress_bar.setValue)
        self.worker.done.connect(self._on_finished)
        self.worker.start()

    def _on_queue(self):
        if not self.selected: return
        if self.main.store.get("confirm_before_queue"):
            if QMessageBox.question(self, APP_NAME, f"Queue {self.selected.get('name', '')} for download?") != QMessageBox.StandardButton.Yes:
                return
        name = self.selected.get("name", "")
        if any(v.get("name") == name for v in self.queue):
            return  # already queued
        if self.worker and self.worker.isRunning():
            self.queue.append(self.selected)
            self._log(f"Queued: {name} (#{len(self.queue)} in line)")
        else:
            # Nothing running — just start it now.
            self._on_download()
            return
        self._refresh_queue_label()

    def _on_verify(self):
        if not self.selected or (self.worker and self.worker.isRunning()): return
        ans = QMessageBox.question(self, APP_NAME,
            "Verify files? This re-checks the download and repairs anything broken.\n\nIt only re-downloads what's wrong, so it's quick if everything's fine.")
        if ans != QMessageBox.StandardButton.Yes: return
        self._start_download(self.selected)
        if not self.selected: return
        name = self.selected.get("name", "")
        if any(v.get("name") == name for v in self.queue):
            return  # already queued
        if self.worker and self.worker.isRunning():
            self.queue.append(self.selected)
            self._log(f"Queued: {name} (#{len(self.queue)} in line)")
        else:
            # Nothing running — just start it now.
            self._on_download()
            return
        self._refresh_queue_label()

    def _refresh_queue_label(self):
        if self.queue:
            names = ", ".join(v.get("name", "") for v in self.queue)
            self.queue_label.setText(f"Up next: {names}")
            self.queue_label.setVisible(True)
        else:
            self.queue_label.setVisible(False)

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self._log("Cancelling download...")
            self.cancel_b.setEnabled(False)
            self.worker.cancel()

    def _on_play_game(self):
        # One shared dialog — bring it back if it's already open.
        dlg = getattr(self, "_dino_dlg", None)
        if dlg is None:
            dlg = DinoDialog(self, self.main.store)
            self._dino_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_progress(self, line):
        # v1.52.0: no more duplicate "Downloading — X GB" in label + log.
        # Live Downloading updates (every 5s, GB + MB/s) go to the label only.
        # Everything else (errors, cancelled, finished, retrying, installing)
        # still goes to the log too, because those are one-off events that
        # belong in history — and they are not repeated every 5 seconds.
        self.progress_label.setText(line)
        if not str(line).startswith("Downloading"):
            self._log(line)

    @staticmethod
    def _friendly_error(msg):
        """Turn a raw failure into (headline, what to do next)."""
        m = (msg or "").lower()
        if "steam username" in m or "set your steam" in m:
            return ("Steam username missing",
                    "Go to Settings → Steam, type your Steam username, then hit Download again.\n(Username only — you type the password in Steam's own window.)")
        if "password" in m or "steam guard" in m or "login" in m:
            return ("Steam login needed",
                    "A SteamCMD window asked you to log in and it didn't complete.\nHit Download again, and when the black Steam window appears, type your password and Steam Guard code in there yourself.")
        if "disk" in m or "space" in m or "not enough" in m:
            return ("Not enough disk space",
                    "Free up space (each build is tens of GB), then retry.\nTip: delete an old build in Settings → Data.")
        if "cancelled" in m:
            return ("Download cancelled",
                    "Partial files were kept — hit Download again to resume where it stopped.")
        if "couldn't start steamcmd" in m or "couldn't start" in m:
            return ("Couldn't start the downloader",
                    "Make sure SteamCMD set up correctly: Settings → Steam → Set up SteamCMD.\nThen retry the download.")
        if "not found after copying" in m or "game exe not found" in m:
            return ("Install didn't finish",
                    "Hit Verify on this build to re-check the files and repair what's missing.")
        return ("Something went wrong",
                f"{msg}\n\nIf it keeps happening, bring a screenshot of the log and retry.")

    def _show_error(self, msg):
        title, advice = self._friendly_error(msg)
        # If Primitive+ was in this download, a Prim+ depot failure must
        # not kill the whole build: offer to retry with it excluded, so
        # the base game + other DLCs still install. (Prim+ stays
        # excluded for this build only — the DLC card can re-include it.)
        if (self.selected and self.selected.get("primitive")
                and "primitive" not in self._excluded_for(self.selected.get("name", ""))):
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText(f"{title}\n\n{advice}")
            box.setInformativeText("Primitive+ was part of this download. If Steam won't serve its depot (usually because the free Primitive+ DLC isn't claimed on your account), retrying without it still installs everything else.")
            retry_prim = box.addButton("Retry without Primitive+", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Retry", QMessageBox.ButtonRole.RejectRole)
            box.addButton("Close", QMessageBox.ButtonRole.DestructiveRole)
            box.exec()
            if box.clickedButton() is retry_prim:
                name = self.selected.get("name", "")
                excluded = set(self._excluded_for(name)) | {"primitive"}
                self._set_excluded_for(name, excluded)
                self._log("Primitive+ excluded for this build — retrying download without it.")
                self._refresh_details()
                self._start_download(self.selected)
                return
            if box.clickedButton() is not None and box.clickedButton().text() == "Retry":
                self._start_download(self.selected)
                return
            return
        QMessageBox.warning(self, APP_NAME, f"{title}\n\n{advice}")

    def _on_finished(self, ok, msg):
        self.progress_bar.setVisible(False); self.cancel_b.setVisible(False); self.cancel_b.setEnabled(True)
        self.game_b.setVisible(False)
        self.progress_label.setText("")
        self._log(msg)
        # v1.53.0: if the window was auto-hidden to tray while downloading,
        # the user cannot see "Installed — hit Play!" until they reopen.
        # Tell them via tray, so they know to reopen and Play.
        try:
            _main = getattr(self, "main", None)
            _tray = getattr(_main, "tray", None) if _main is not None else None
            if ok and _main is not None and not _main.isVisible() and _tray is not None:
                _nm = (self.selected.get("name", "") if self.selected else "")
                _tray.showMessage(APP_NAME, f"Download finished — {_nm} is installed. Reopen the launcher and hit Play!",
                                  QSystemTrayIcon.MessageIcon.Information, 5000)
        except Exception:
            pass
        self.download_b.setEnabled(True); self.queue_b.setEnabled(True)
        self._refresh_details()
        if ok:
            self.progress_label.setText("Installed — hit Play!")
        elif "cancelled" not in msg.lower():
            self._show_error(msg)
        # Queue: start the next build automatically.
        if self.queue and (ok or "cancelled" in msg.lower()):
            nxt = self.queue.pop(0)
            self._refresh_queue_label()
            self._log(f"Starting queued download: {nxt.get('name', '')}")
            self._start_download(nxt)

    def _record_play(self, name):
        if not name: return
        recent = self.main.store.get("recently_played", []) or []
        recent = [n for n in recent if n != name]
        recent.insert(0, name)
        self.main.store.set("recently_played", recent[:3])

    def _on_play(self):
        if not self.selected: return
        self.play_version(self.selected)

    def play_version(self, v):
        """Launch a build directly (used by Dashboard's Recently Played)."""
        self._record_play(v.get("name", ""))
        steam = steam_dir_for(self.main.store); exe = game_exe_for(steam, v, self.main.store) if steam else None
        if not exe or not Path(exe).is_file():
            QMessageBox.warning(self, APP_NAME,
                f"\"{v.get('name', '')}\" isn't installed yet.\n\nHit Download on this build first, then Play."); return

        # Make sure steam_appid.txt sits next to the exe (repairs older
        # installs that predate the download-time write). Without it the
        # game dies silently right after the loading music.
        try:
            appid = Path(exe).parent / "steam_appid.txt"
            if not appid.is_file(): appid.write_text(str(STEAM_APP_ID))
        except OSError: pass

        # The Steam client must be running or SteamAPI init fails and the
        # game exits silently. Start it and give it a moment if needed.
        try:
            running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe"],
                                     capture_output=True, text=True, timeout=15,
                                     creationflags=_hidden_flags())
            steam_up = "steam.exe" in (running.stdout or "").lower()
        except (OSError, subprocess.SubprocessError):
            steam_up = True  # can't check — don't block the launch
        if not steam_up and steam:
            steam_exe = str(Path(steam) / "steam.exe")
            try:
                subprocess.Popen([steam_exe])
                self._log("Starting Steam so the game can verify ownership...")
                time.sleep(10)
            except OSError:
                QMessageBox.warning(self, APP_NAME, "Steam isn't running — open Steam first, then hit Play."); return

        # Apply Launch Arguments: per-build profile wins, else the global default.
        profiles = self.main.store.get("launch_profiles", {}) or {}
        args_str = ((profiles.get(v.get("name", ""), "") or "").strip()
                    or self.main.store.get("launch_args", "").strip())

        # v1.66.0: game language (TEK appends -culture= always; here it
        # only applies when the user picked one, so Steam default stays).
        culture = (self.main.store.get("game_culture", "") or "").strip()
        if culture and "-culture" not in args_str:
            args_str = (args_str + f" -culture={culture}").strip()

        # Launch via the desktop shortcut (which carries the custom "A"
        # icon) so the taskbar button shows it while the game loads — a
        # raw exe launch shows a generic icon instead. Refresh the
        # shortcut's args first so Settings changes apply.
        label = f"Legacy ARK - {v.get('name', '')}"
        lnk = _write_shortcut(label, exe, args_str)
        if lnk:
            try:
                os.startfile(str(lnk))
                try:
                    if self.main.store.get("discord_rich_presence"):
                        discord_set_playing(self.main.store.get("discord_client_id", ""), v.get("name", ""))
                except Exception: pass
                if self.main.store.get("close_on_launch"):
                    try: self.main.close()
                    except Exception: pass
                return
            except OSError:
                pass
        # Fallback: direct exe launch.
        cmd = [str(exe)]
        if args_str: cmd.extend(args_str.split())
        try:
            proc = subprocess.Popen(cmd, cwd=str(Path(exe).parent))
            try:
                if self.main.store.get("discord_rich_presence"):
                    discord_set_playing(self.main.store.get("discord_client_id", ""), v.get("name", ""))
            except Exception: pass
            if self.main.store.get("close_on_launch"):
                try: self.main.close()
                except Exception: pass
        except OSError as e: QMessageBox.warning(self, APP_NAME, f"Couldn't launch the game: {e}")

    def _on_open_folder(self):
        if not self.selected: return
        steam = steam_dir_for(self.main.store)
        if steam:
            game_dir = game_dir_for(self.main.store, self.selected, steam)
            if game_dir.is_dir():
                _open_url(QUrl.fromLocalFile(str(game_dir)).toString())
            else:
                QMessageBox.information(self, APP_NAME, "Folder doesn't exist yet.")

    def refresh(self): self._refresh_details(); self._sync_preset_combo()


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)
    def __init__(self, checked=False):
        super().__init__(); self._on = checked; self.setFixedSize(46, 24); self.setCursor(Qt.CursorShape.PointingHandCursor)
    def isChecked(self): return self._on
    def setChecked(self, on):
        if on != self._on: self._on = on; self.update(); self.toggled.emit(on)
    def mousePressEvent(self, e): self.setChecked(not self._on)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT) if self._on else QColor(BORDER)); p.drawRoundedRect(0, 0, 46, 24, 12, 12)
        p.setBrush(QColor(ON_ACCENT) if self._on else QColor(MUTED)); x = 26 if self._on else 4
        p.drawEllipse(x, 4, 16, 16); p.end()

# ------------------------------------------- startup Steam-connect overlay
class SteamConnectDialog(QDialog):
    """Modal startup overlay: the one-time Steam connection.

    First run (no username saved or no steamcmd/ folder): username field
    + "Connect Steam" -> saves the username, sets up SteamCMD in a
    worker thread, then opens SteamCMD's own VISIBLE console running
    `steamcmd +login <username>` so the user types their password /
    Steam Guard code THEMSELVES. The launcher NEVER asks for, reads,
    stores, types, or passes any password — username only.

    Only shown when setup is needed — never flashes on later runs."""
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Connect to Steam")
        self.setModal(True)
        self.setFixedSize(520, 500)

        outer = QVBoxLayout(self); outer.setContentsMargins(36, 26, 36, 26); outer.setSpacing(10)
        outer.addWidget(centered_label(brand_pixmap(72)))
        title = QLabel("Connect to Steam"); title.setObjectName("CardHead")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter); outer.addWidget(title)
        desc = QLabel("The launcher downloads old ARK builds through Steam. Connect once \u2014 after that, Download just works.")
        desc.setObjectName("Muted"); desc.setWordWrap(True); desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(desc)
        outer.addWidget(hair())

        # ---- setup page (first run) ----
        self.setup_box = QWidget(); sb = QVBoxLayout(self.setup_box); sb.setContentsMargins(0, 0, 0, 0); sb.setSpacing(8)
        ulab = QLabel("Steam Username"); ulab.setObjectName("RowTitle"); sb.addWidget(ulab)
        self.user_edit = QLineEdit(); self.user_edit.setPlaceholderText("Your Steam account name")
        self.user_edit.setText((store.get("steam_username", "") or "").strip())
        sb.addWidget(self.user_edit)
        unote = QLabel("Username only \u2014 never your password. If Steam asks for one, you type it yourself in Steam's own window.")
        unote.setObjectName("Muted"); unote.setWordWrap(True); sb.addWidget(unote)
        self.status = QLabel(""); self.status.setObjectName("Muted"); self.status.setWordWrap(True); sb.addWidget(self.status)
        self.connect_b = QPushButton("Connect Steam"); self.connect_b.setObjectName("Primary")
        self.connect_b.setCursor(Qt.CursorShape.PointingHandCursor); self.connect_b.clicked.connect(self._on_connect)
        sb.addWidget(self.connect_b)
        skip = QPushButton("Skip for now"); skip.setObjectName("Ghost")
        skip.setCursor(Qt.CursorShape.PointingHandCursor); skip.clicked.connect(self.accept)
        sb.addWidget(skip, 0, Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.setup_box)

        # ---- done page (after Connect) ----
        self.done_box = QWidget(); db = QVBoxLayout(self.done_box); db.setContentsMargins(0, 0, 0, 0); db.setSpacing(10)
        dlab = QLabel("A SteamCMD window just opened."); dlab.setObjectName("RowTitle")
        dlab.setAlignment(Qt.AlignmentFlag.AlignCenter); db.addWidget(dlab)
        dsub = QLabel("Finish logging in inside it \u2014 type your password / Steam Guard code there if it asks \u2014 then click Done.")
        dsub.setObjectName("Muted"); dsub.setWordWrap(True); dsub.setAlignment(Qt.AlignmentFlag.AlignCenter); db.addWidget(dsub)
        done_b = QPushButton("Done"); done_b.setObjectName("Primary")
        done_b.setCursor(Qt.CursorShape.PointingHandCursor); done_b.clicked.connect(self.accept)
        db.addWidget(done_b)
        db.addStretch(1)
        self.done_box.setVisible(False); outer.addWidget(self.done_box)

        # Dialog only opens when setup is needed (checked in main()),
        # so it always starts on the setup page.
        self._show_setup()

    def _show_setup(self):
        self.setup_box.setVisible(True); self.done_box.setVisible(False)

    def _show_done(self):
        self.setup_box.setVisible(False); self.done_box.setVisible(True)

    def _on_connect(self):
        username = self.user_edit.text().strip()
        if not username:
            self.status.setText("Enter your Steam account name first.")
            return
        self.store.set("steam_username", username)
        self.connect_b.setEnabled(False); self.user_edit.setEnabled(False)
        self.status.setText("Setting up SteamCMD...")
        self._setup_thread = _SetupSteamcmdThread()
        self._setup_thread.progress.connect(self.status.setText)
        self._setup_thread.done.connect(self._on_setup_done)
        self._setup_thread.start()

    def _on_setup_done(self, ok, msg):
        if not ok:
            self.status.setText(msg)
            self.connect_b.setEnabled(True); self.user_edit.setEnabled(True)
            return
        # Open SteamCMD's own VISIBLE console for the one-time login.
        # The user types their password / Guard code there themselves —
        # the launcher never captures, stores, types, or passes it.
        try:
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
            subprocess.Popen([str(STEAMCMD_EXE), "+login", self.store.get("steam_username", "").strip()], creationflags=flags)
            opened = True
        except OSError:
            opened = False
        if not opened:
            self.status.setText("Couldn't open the SteamCMD console. Open it yourself and run: steamcmd +login " + self.store.get("steam_username", "").strip())
            self.connect_b.setEnabled(True); self.user_edit.setEnabled(True)
            return
        self._show_done()

    def closeEvent(self, e):
        # Don't let a still-running setup thread signal into a dead dialog.
        th = getattr(self, "_setup_thread", None)
        if th is not None and th.isRunning():
            try: th.progress.disconnect()
            except Exception: pass
            try: th.done.disconnect()
            except Exception: pass
        super().closeEvent(e)


# ------------------------------------------------------------------ host a server
# The dedicated server exe ships inside every ARK client download, so any
# build installed through the launcher can host. This page writes the
# config files and the launch line, then runs the server.

# (map file name, display name, dlc key or None for base game)
HOST_MAPS = [
    ("TheIsland", "The Island", None),
    ("TheCenter", "The Center", "center"),
    ("ScorchedEarth_P", "Scorched Earth", "scorched"),
    ("Ragnarok", "Ragnarok", "ragnarok"),
    ("Aberration_P", "Aberration", "aberration"),
    ("Extinction", "Extinction", "extinction"),
    ("Valguero_P", "Valguero", "valguero"),
    ("Genesis", "Genesis", "genesis"),
    ("CrystalIsles", "Crystal Isles", "crystal_isles"),
    ("LostIsland", "Lost Island", "lost_island"),
    ("Fjordur", "Fjordur", "fjordur"),
]

def _host_is_old_build(name):
    """2015-2016 builds are janky to host and harder to configure."""
    try:
        year, _month = parse_version_date(name)
        return year <= 2016
    except Exception:
        return False

def _server_exe_for(store, version):
    steam = steam_dir_for(store)
    base = install_root_for(store, steam)
    return base / slugify(version.get("name", "")) / "ShooterGame" / "Binaries" / "Win64" / "ShooterGameServer.exe"

def _server_root_for(store, version):
    steam = steam_dir_for(store)
    return install_root_for(store, steam) / slugify(version.get("name", ""))


# ------------------------------------------------------------------ server wizard
# A 4-question guided setup for people who don't want to read 80 options.
# It fills the Host tab's form behind the scenes and creates the server.

WIZARD_STYLES = [
    ("chill", "🌱  Chill PvE",
     "Relaxed and friendly. 3x XP, gathering and taming. No PvP damage — build in peace.",
     {"pve": True, "xp": 3, "harvest": 3, "tame": 3, "breed": 3, "crop": 3}),
    ("normal", "⚔️  Classic PvP",
     "Default ARK. 1x rates, PvP enabled. The way it was meant to be.",
     {"pve": False}),
    ("boosted", "🚀  Boosted",
     "Fast everything. 5x rates, quick taming and breeding. For people with jobs.",
     {"xp": 5, "harvest": 5, "tame": 5, "breed": 5, "crop": 5,
      "layegg": 0.5, "baby_food": 0.5, "cuddle_interval": 0.5}),
    ("hardcore", "💀  Hardcore",
     "Permadeath. Max difficulty, PvP on. Not for the faint of heart.",
     {"hardcore": True, "pve": False, "difficulty": 1.0, "difficulty_override": 5.0}),
]

class ServerWizard(QDialog):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setWindowTitle("Set up your server")
        self.setModal(True)
        self.setMinimumSize(560, 480)
        self._style_key = "normal"

        outer = QVBoxLayout(self); outer.setContentsMargins(28, 22, 28, 22); outer.setSpacing(14)
        title = QLabel("SET UP YOUR SERVER"); title.setObjectName("SectionHeader")
        outer.addWidget(title)
        outer.addWidget(hair())

        self.pages = QStackedWidget(); outer.addWidget(self.pages, 1)
        self._build_page1(); self._build_page2(); self._build_page3(); self._build_page4()

        nav = FlowLayout(); nav.setSpacing(10)
        self.back_b = QPushButton("Back"); self.back_b.clicked.connect(self._back)
        self.next_b = QPushButton("Next"); self.next_b.setObjectName("Primary")
        self.next_b.clicked.connect(self._next)
        cancel_b = QPushButton("Cancel"); cancel_b.setObjectName("Ghost")
        cancel_b.clicked.connect(self.reject)
        nav.addWidget(cancel_b); nav.addStretch(1)
        nav.addWidget(self.back_b); nav.addWidget(self.next_b)
        outer.addLayout(nav)
        self._sync_nav()

    def _page(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(4, 8, 4, 8); v.setSpacing(12)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.pages.addWidget(w)
        return v

    def _q(self, text, sub=""):
        v = self._page()
        q = QLabel(text); q.setObjectName("RowTitle"); q.setWordWrap(True); v.addWidget(q)
        if sub:
            s = QLabel(sub); s.setObjectName("Muted"); s.setWordWrap(True); v.addWidget(s)
        return v

    def _build_page1(self):
        v = self._q("What should your server be called?",
                    "This is the name players see in the server list.")
        self.w_name = QLineEdit(); self.w_name.setPlaceholderText("My Legacy ARK Server")
        v.addWidget(self.w_name)
        v.addWidget(QLabel("Server password (optional — leave empty for anyone to join):"))
        self.w_pass = QLineEdit(); self.w_pass.setPlaceholderText("Empty = public")
        v.addWidget(self.w_pass)
        v.addWidget(QLabel("Admin password (you need this for admin commands):"))
        self.w_admin = QLineEdit(); self.w_admin.setPlaceholderText("Pick something you'll remember")
        v.addWidget(self.w_admin)

    def _build_page2(self):
        v = self._q("Which world should it run?",
                    "Pick a build you've downloaded, then the map to host.")
        v.addWidget(QLabel("Build:"))
        self.w_build = QComboBox()
        for bv in self.host._installed_builds():
            self.w_build.addItem(bv.get("name", "Unnamed"), bv.get("name", ""))
        v.addWidget(self.w_build)
        v.addWidget(QLabel("Map:"))
        self.w_map = QComboBox()
        v.addWidget(self.w_map)
        self.w_build.currentIndexChanged.connect(self._sync_wizard_maps)
        self._sync_wizard_maps()
        note = QLabel("Only maps your build actually has are listed.")
        note.setObjectName("Muted"); note.setWordWrap(True); v.addWidget(note)

    def _sync_wizard_maps(self):
        bname = self.w_build.currentData()
        self.w_map.clear()
        v = next((x for x in self.host._installed_builds() if x.get("name") == bname), None)
        if v:
            dlcs = {k for k in DLC_ORDER if v.get(k)}
            for fmap, dname, dkey in HOST_MAPS:
                if dkey is None or dkey in dlcs:
                    self.w_map.addItem(dname, fmap)

    def _build_page3(self):
        v = self._q("How should it play?", "Pick a vibe — you can fine-tune everything later.")
        grid = FlowLayout(); grid.setSpacing(10)
        self._style_cards = {}
        for i, (key, title, desc, _preset) in enumerate(WIZARD_STYLES):
            card = ClickableCard(); card.setObjectName("Card")
            cl = QVBoxLayout(card); cl.setContentsMargins(14, 12, 14, 12); cl.setSpacing(6)
            t = QLabel(title); t.setObjectName("RowTitle"); t.setWordWrap(True); cl.addWidget(t)
            d = QLabel(desc); d.setObjectName("Muted"); d.setWordWrap(True); cl.addWidget(d)
            card.clicked.connect(lambda _c=False, _k=key: self._pick_style(_k))
            grid.addWidget(card)
            self._style_cards[key] = card
        v.addLayout(grid)
        self._pick_style("normal")

    def _pick_style(self, key):
        self._style_key = key
        for k, card in self._style_cards.items():
            card.setStyleSheet("" if k != key else f"QFrame#Card {{ border: 2px solid {ACCENT}; }}")

    def _build_page4(self):
        v = self._q("Who's it for?")
        v.addWidget(QLabel("Max players:"))
        hl = FlowLayout()
        self.w_players = QSlider(Qt.Orientation.Horizontal); self.w_players.setRange(1, 100); self.w_players.setValue(20)
        self.w_players_label = QLabel("20"); self.w_players_label.setObjectName("RowTitle")
        self.w_players.valueChanged.connect(lambda n: self.w_players_label.setText(str(n)))
        hl.addWidget(self.w_players, 1); hl.addWidget(self.w_players_label)
        v.addLayout(hl)
        v.addSpacing(8)
        v.addWidget(QLabel("Can anyone join, or invite only?"))
        self.w_public = QCheckBox("Public — show up for anyone (no password needed)")
        self.w_public.setChecked(True)
        v.addWidget(self.w_public)
        note = QLabel("Private just means you set a password on step 1 — only people with the password get in.")
        note.setObjectName("Muted"); note.setWordWrap(True); v.addWidget(note)
        v.addSpacing(8)
        self.w_summary = QLabel(""); self.w_summary.setObjectName("Muted"); self.w_summary.setWordWrap(True)
        v.addWidget(self.w_summary)

    # ---- nav ----
    def _sync_nav(self):
        i = self.pages.currentIndex()
        n = self.pages.count()
        self.back_b.setEnabled(i > 0)
        self.next_b.setText("Create server" if i == n - 1 else "Next")
        if i == n - 1:
            style_name = next(t for k, t, _d, _p in WIZARD_STYLES if k == self._style_key)
            self.w_summary.setText(
                f"Ready to create:\n• {self.w_name.text().strip() or 'My Legacy ARK Server'}\n"
                f"• {self.w_build.currentText()} — {self.w_map.currentText()}\n"
                f"• {style_name}, {self.w_players.value()} players, "
                f"{'public' if self.w_public.isChecked() and not self.w_pass.text().strip() else 'private'}")

    def _back(self):
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
        self._sync_nav()

    def _next(self):
        i = self.pages.currentIndex()
        if i == 0 and not self.w_admin.text().strip():
            QMessageBox.warning(self, APP_NAME, "Set an admin password — you'll need it for admin commands.")
            return
        if i < self.pages.count() - 1:
            self.pages.setCurrentIndex(i + 1)
            self._sync_nav()
            return
        self._create()

    def _create(self):
        h = self.host
        # Point the form at the chosen build/map.
        bname = self.w_build.currentData()
        idx = h.build_combo.findData(bname)
        if idx >= 0: h.build_combo.setCurrentIndex(idx)
        h._on_build_changed()
        midx = h.map_combo.findData(self.w_map.currentData())
        if midx >= 0: h.map_combo.setCurrentIndex(midx)
        # Fill the basics.
        h.name_edit.setText(self.w_name.text().strip())
        h._widgets["password"].setText(self.w_pass.text().strip())
        h._widgets["admin"].setText(self.w_admin.text().strip())
        h._widgets["players"].setValue(self.w_players.value())
        if not self.w_public.isChecked() and not self.w_pass.text().strip():
            h._widgets["password"].setText("changeme")
        # Apply the playstyle preset.
        preset = next(p for k, _t, _d, p in WIZARD_STYLES if k == self._style_key)
        h._apply_preset_dict(preset)
        self.accept()
        h._on_create()


# ------------------------------------------------------------------ welcome wizard
# First-launch onboarding: what this app is, how downloads work, and
# which version to grab first. Shown once, before the Steam setup dialog.

RECOMMENDED_BUILDS = ["March 2017 build", "v252.96 (Dec 2016)"]

class WelcomeWizard(QDialog):
    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.setWindowTitle("Welcome to Legacy ARK")
        self.setModal(True)
        self.setMinimumSize(560, 460)

        outer = QVBoxLayout(self); outer.setContentsMargins(28, 22, 28, 22); outer.setSpacing(14)
        title = QLabel("WELCOME TO LEGACY ARK"); title.setObjectName("SectionHeader")
        outer.addWidget(title)
        outer.addWidget(hair())

        self.pages = QStackedWidget(); outer.addWidget(self.pages, 1)
        self._build_p1(); self._build_p2(); self._build_p3()

        nav = FlowLayout(); nav.setSpacing(10)
        self.back_b = QPushButton("Back"); self.back_b.clicked.connect(self._back)
        self.next_b = QPushButton("Next"); self.next_b.setObjectName("Primary")
        self.next_b.clicked.connect(self._next)
        skip_b = QPushButton("Skip"); skip_b.setObjectName("Ghost")
        skip_b.clicked.connect(self._done)
        nav.addWidget(skip_b); nav.addStretch(1)
        nav.addWidget(self.back_b); nav.addWidget(self.next_b)
        outer.addLayout(nav)
        self._sync_nav()

    def _page(self, heading, sub):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(4, 8, 4, 8); v.setSpacing(12)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)
        q = QLabel(heading); q.setObjectName("CardHead"); q.setWordWrap(True); v.addWidget(q)
        s = QLabel(sub); s.setObjectName("Muted"); s.setWordWrap(True); v.addWidget(s)
        self.pages.addWidget(w)
        return v

    def _build_p1(self):
        v = self._page("Play old-school ARK.",
                       "This launcher lets you download and play classic ARK: Survival Evolved builds "
                       "from 2015 to 2024 — the way the game used to be.\n\n"
                       "Here's the whole process:\n"
                       "1. Pick a version\n2. Download it (one-time, it's a big game)\n"
                       "3. Hit Play — that's it.")
        v.addSpacing(8)
        tip = QLabel("Tip: you need to own ARK: Survival Evolved on Steam for downloads to work.")
        tip.setObjectName("Muted"); tip.setWordWrap(True); v.addWidget(tip)

    def _build_p2(self):
        v = self._page("How downloads work.",
                       "Old game versions come from Steam itself, using Valve's official downloader tool.\n\n"
                       "When you download, a black Steam window will open and ask you to log in. "
                       "That's normal — type your Steam username and password right in that window. "
                       "The launcher never sees or stores your password.\n\n"
                       "Big builds take a while. Grab a coffee.")

    def _build_p3(self):
        v = self._page("Pick your first version.",
                       "Don't overthink it — these two are the community favorites. "
                       "You can grab more later from the Versions tab.")
        grid = FlowLayout(); grid.setSpacing(10)
        self._rec_cards = {}
        for name in RECOMMENDED_BUILDS:
            ver = next((x for x in self.main.versions.versions if x.get("name") == name), None)
            if ver is None: continue
            card = ClickableCard(); card.setObjectName("Card")
            cl = QVBoxLayout(card); cl.setContentsMargins(14, 12, 14, 12); cl.setSpacing(6)
            t = QLabel(name); t.setObjectName("RowTitle"); t.setWordWrap(True); cl.addWidget(t)
            n_dlc = sum(1 for k in DLC_ORDER if ver.get(k))
            d = QLabel(f"{n_dlc} DLCs · ~{_estimate_size_gb(ver):.0f} GB" if n_dlc else "Base game")
            d.setObjectName("Muted"); d.setWordWrap(True); cl.addWidget(d)
            card.clicked.connect(lambda _c=False, _n=name: self._pick_rec(_n))
            grid.addWidget(card, 1)
            self._rec_cards[name] = card
        v.addLayout(grid)
        self._picked = None
        self._pick_rec(RECOMMENDED_BUILDS[0] if RECOMMENDED_BUILDS[0] in self._rec_cards else None)

    def _pick_rec(self, name):
        self._picked = name
        for k, card in self._rec_cards.items():
            card.setStyleSheet("" if k != name else f"QFrame#Card {{ border: 2px solid {ACCENT}; }}")

    def _sync_nav(self):
        i = self.pages.currentIndex()
        n = self.pages.count()
        self.back_b.setEnabled(i > 0)
        self.next_b.setText("Get started" if i == n - 1 else "Next")

    def _back(self):
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
        self._sync_nav()

    def _next(self):
        i = self.pages.currentIndex()
        if i < self.pages.count() - 1:
            self.pages.setCurrentIndex(i + 1)
            self._sync_nav()
            return
        self._done()

    def _done(self):
        self.main.store.set("onboarding_done", True)
        self.accept()
        # Jump to the picked version so Download is one click away.
        if self._picked:
            for v in self.main.versions.versions:
                if v.get("name") == self._picked:
                    self.main.versions._select_version(v)
                    break
        self.main.show_page(1)


class HostPage(QWidget):
    """Turn an installed build into a dedicated server: pick the build,
    fill in the settings, hit Create — then Start/Stop from here.

    Each server gets its own save folder (?AltSaveDirectoryName), so
    multiple servers can share one build install without overwriting
    each other's configs or saves."""

    # (key, label, kind, lo, hi, default, tooltip)
    # kind: check | rate | int | line | text
    BASIC = [
        ("password", "Server password", "line", 0, 0, "", "Empty = public server"),
        ("admin", "Admin password", "line", 0, 0, "", "Required for admin commands"),
        ("spectator", "Spectator password", "line", 0, 0, "", "Empty = no spectator password"),
        ("players", "Max players", "int", 1, 200, 70, ""),
    ]
    WORLD = [
        ("pve", "PvE mode (no player-vs-player damage)", "check", 0, 0, False, ""),
        ("hardcore", "Hardcore (permadeath)", "check", 0, 0, False, ""),
        ("difficulty", "Difficulty", "rate", 0.0, 1.0, 0.2, "Higher = higher max wild dino level"),
        ("difficulty_override", "Difficulty override", "rate", 0.1, 10.0, 1.0, "Multiplies the difficulty (official uses 5)"),
        ("day", "Day speed", "rate", 0.1, 10.0, 1.0, "Higher = daytime passes faster"),
        ("night", "Night speed", "rate", 0.1, 10.0, 1.0, "Higher = nighttime passes faster"),
        ("dino_count", "Dino count", "rate", 0.1, 10.0, 1.0, "Wild dino spawn amount"),
        ("respawn_period", "Resource respawn", "rate", 0.1, 10.0, 1.0, "Lower = resources respawn faster"),
        ("global_voice", "Global voice chat", "check", 0, 0, True, ""),
        ("proximity_chat", "Proximity voice chat", "check", 0, 0, False, ""),
        ("notify_join", "Notify when players join", "check", 0, 0, True, ""),
        ("notify_left", "Notify when players leave", "check", 0, 0, True, ""),
        ("third_person", "Allow third person", "check", 0, 0, True, ""),
        ("map_location", "Show players on map", "check", 0, 0, False, ""),
        ("floating_damage", "Floating damage text", "check", 0, 0, False, ""),
        ("crosshair", "Crosshair", "check", 0, 0, False, ""),
        ("cave_pve", "Allow cave building (PvE)", "check", 0, 0, False, ""),
        ("cave_pvp", "Allow cave building (PvP)", "check", 0, 0, False, ""),
        ("flyer_carry_pve", "Allow flyer carry (PvE)", "check", 0, 0, False, ""),
        ("flyer_carry_pvp", "Allow flyer carry (PvP)", "check", 0, 0, False, ""),
        ("pve_gamma", "Disable gamma in PvE", "check", 0, 0, False, ""),
        ("autosave", "Autosave (minutes)", "int", 5, 120, 15, ""),
        ("kick_idle", "Kick idle players (sec, 0=off)", "int", 0, 3600, 0, ""),
    ]
    RATES = [
        ("xp", "XP multiplier", "rate", 0.1, 100.0, 1.0, ""),
        ("harvest", "Harvest multiplier", "rate", 0.1, 100.0, 1.0, ""),
        ("harvest_health", "Harvest health", "rate", 0.1, 100.0, 1.0, "Node health when harvesting"),
        ("tame", "Taming multiplier", "rate", 0.1, 100.0, 1.0, ""),
        ("breed", "Breeding multiplier", "rate", 0.1, 100.0, 1.0, "Mating, egg hatch and baby growth"),
        ("crop", "Crop growth", "rate", 0.1, 100.0, 1.0, ""),
        ("layegg", "Egg lay interval", "rate", 0.1, 100.0, 1.0, "Lower = dinos lay eggs faster"),
        ("spoil", "Spoiling speed", "rate", 0.1, 100.0, 1.0, ""),
        ("item_decay", "Item decomposition", "rate", 0.1, 100.0, 1.0, ""),
        ("corpse_decay", "Corpse decomposition", "rate", 0.1, 100.0, 1.0, ""),
        ("crate_loot", "Supply crate loot quality", "rate", 0.1, 100.0, 1.0, ""),
        ("fish_loot", "Fishing loot quality", "rate", 0.1, 100.0, 1.0, ""),
        ("recipe_effect", "Custom recipe effectiveness", "rate", 0.1, 100.0, 1.0, ""),
        ("recipe_skill", "Custom recipe skill bonus", "rate", 0.1, 100.0, 1.0, ""),
        ("maxtamed", "Max tamed dinos (0=default)", "int", 0, 5000, 0, ""),
    ]
    PLAYER = [
        ("p_water", "Water drain", "rate", 0.1, 10.0, 1.0, "Lower = drains slower"),
        ("p_food", "Food drain", "rate", 0.1, 10.0, 1.0, "Lower = drains slower"),
        ("p_stam", "Stamina drain", "rate", 0.1, 10.0, 1.0, "Lower = drains slower"),
        ("p_heal", "Health regen", "rate", 0.1, 10.0, 1.0, ""),
        ("p_damage", "Player damage", "rate", 0.1, 100.0, 1.0, ""),
        ("p_resist", "Player resistance", "rate", 0.1, 100.0, 1.0, ""),
    ]
    DINO = [
        ("d_food", "Food drain", "rate", 0.1, 10.0, 1.0, "Lower = drains slower"),
        ("d_heal", "Health regen", "rate", 0.1, 10.0, 1.0, ""),
        ("d_stam", "Stamina drain", "rate", 0.1, 10.0, 1.0, "Lower = drains slower"),
        ("d_damage", "Wild dino damage", "rate", 0.1, 100.0, 1.0, ""),
        ("d_resist", "Wild dino resistance", "rate", 0.1, 100.0, 1.0, ""),
        ("t_damage", "Tamed dino damage", "rate", 0.1, 100.0, 1.0, ""),
        ("t_resist", "Tamed dino resistance", "rate", 0.1, 100.0, 1.0, ""),
        ("baby_food", "Baby food consumption", "rate", 0.1, 100.0, 1.0, ""),
        ("cuddle_interval", "Baby cuddle interval", "rate", 0.1, 100.0, 1.0, ""),
        ("imprint_cuddle", "Anyone can imprint-cuddle", "check", 0, 0, False, ""),
        ("max_personal_tamed", "Max personal tamed (0=default)", "int", 0, 5000, 0, ""),
        ("disable_decay_pve", "Disable dino decay (PvE)", "check", 0, 0, False, ""),
    ]
    STRUCTURES = [
        ("s_damage", "Structure damage", "rate", 0.1, 100.0, 1.0, ""),
        ("s_resist", "Structure resistance", "rate", 0.1, 100.0, 1.0, ""),
        ("pvp_decay", "PvP structure decay", "check", 0, 0, False, ""),
        ("pvp_decay_period", "PvP decay period", "rate", 0.1, 100.0, 1.0, ""),
        ("disable_pve_decay", "Disable structure decay (PvE)", "check", 0, 0, False, ""),
        ("pve_decay_period", "PvE decay period", "rate", 0.1, 100.0, 1.0, ""),
        ("platform_structs", "Platform structures", "rate", 0.1, 100.0, 1.0, "PerPlatformMaxStructuresMultiplier"),
        ("allow_pickup", "Always allow structure pickup", "check", 0, 0, False, ""),
        ("force_lock", "Force structure locking", "check", 0, 0, False, ""),
    ]
    TRANSFERS = [
        ("dl_survivors", "Block survivor downloads", "check", 0, 0, False, ""),
        ("dl_items", "Block item downloads", "check", 0, 0, False, ""),
        ("dl_dinos", "Block dino downloads", "check", 0, 0, False, ""),
        ("ul_survivors", "Block survivor uploads", "check", 0, 0, False, ""),
        ("ul_items", "Block item uploads", "check", 0, 0, False, ""),
        ("ul_dinos", "Block dino uploads", "check", 0, 0, False, ""),
        ("no_alliances", "Prevent tribe alliances", "check", 0, 0, False, ""),
        ("max_alliances", "Max alliances per tribe (0=default)", "int", 0, 100, 0, ""),
    ]
    ADVANCED = [
        ("port", "Game port", "int", 1024, 65535, 7777, ""),
        ("query", "Query port", "int", 1024, 65535, 27015, ""),
        ("rcon", "Enable RCON (remote admin)", "check", 0, 0, False, ""),
        ("rconport", "RCON port", "int", 1024, 65535, 27020, ""),
        ("cluster", "Cluster ID", "line", 0, 0, "", "Links servers together"),
        ("mods", "Mod IDs", "line", 0, 0, "", "Comma-separated Workshop IDs"),
        ("multihome", "Bind IP", "line", 0, 0, "", "multihome address, usually empty"),
        ("banlist", "Ban list URL", "line", 0, 0, "", ""),
        ("respawn_interval", "Force respawn wild dinos (sec, 0=off)", "int", 0, 86400, 0, ""),
        ("no_disease", "Prevent diseases", "check", 0, 0, False, ""),
        ("nonperm_disease", "Non-permanent diseases", "check", 0, 0, False, ""),
        ("active_event", "Active event", "line", 0, 0, "", "e.g. WinterWonderland — broken on 2015 builds"),
        ("nobattleye", "Disable BattleEye (helps old builds)", "check", 0, 0, False, ""),
    ]
    CUSTOM = [
        ("custom_gus", "Extra GameUserSettings.ini lines", "text", 0, 0, "", "Appended to the generated config"),
        ("custom_gameini", "Game.ini content", "text", 0, 0, "", "Written to Game.ini (engrams, spawns, stacks...)"),
    ]

    SECTIONS = [
        ("BASIC", "Name, passwords, player count", BASIC),
        ("WORLD", "PvP or PvE, difficulty, day/night cycle, chat", WORLD),
        ("RATES", "How fast everything goes: XP, gathering, taming, breeding, loot", RATES),
        ("PLAYER", "How fast your survivor gets hungry, tired, and heals", PLAYER),
        ("DINO", "Wild and tamed dino stats and breeding", DINO),
        ("STRUCTURES", "Building damage, decay, and limits", STRUCTURES),
        ("TRANSFERS && TRIBES", "Cross-server transfers and tribe alliances", TRANSFERS),
        ("ADVANCED", "Ports, RCON, mods, cluster ID", ADVANCED),
        ("CUSTOM INI", "Paste raw config lines for anything else", CUSTOM),
    ]

    PRESETS = {
        "Vanilla": {},
        "Boosted 2x": {"xp": 2, "harvest": 2, "tame": 2, "breed": 2, "crop": 2},
        "Boosted 5x": {"xp": 5, "harvest": 5, "tame": 5, "breed": 5, "crop": 5,
                       "layegg": 0.5, "baby_food": 0.5, "cuddle_interval": 0.5},
        "Hardcore": {"hardcore": True, "pve": False, "difficulty": 1.0, "difficulty_override": 5.0},
    }

    DEFAULTS = {k: d for secs in [BASIC, WORLD, RATES, PLAYER, DINO, STRUCTURES, TRANSFERS, ADVANCED, CUSTOM]
                for (k, _l, _k2, _lo, _hi, d, _t) in secs}

    def __init__(self, main):
        super().__init__(); self.main = main; self.store = main.store
        self._procs = {}
        self._widgets = {}  # key -> widget
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(32, 28, 32, 32); v.setSpacing(18)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        v.addWidget(page_header("Host a server", "Turn any installed build into a dedicated ARK server."))
        intro = QLabel("Any build you've downloaded can host a dedicated server — the server files come with the game. "
                       "Fill in the settings, hit Create server, then Start it. Your friends join with your IP (or a playit.gg tunnel).")
        intro.setObjectName("Muted"); intro.setWordWrap(True); v.addWidget(intro)
        # v1.29.2 Host layout fix: plain 3-step guide up top, so the page
        # is not just a wall of collapsed sections and empty dropdowns.
        guide = QFrame(); guide.setObjectName("Card")
        gv = QVBoxLayout(guide); gv.setContentsMargins(18, 14, 18, 14); gv.setSpacing(6)
        gt = QLabel("Host in 3 steps"); gt.setObjectName("CardHead"); gv.addWidget(gt)
        g1 = QLabel("1) Install a build first — go to Versions and download any old build. Host needs an installed build, which is why Build and Map are empty until you do.")
        g1.setObjectName("Muted"); g1.setWordWrap(True); gv.addWidget(g1)
        g2 = QLabel("2) Pick that build, name your server, pick a map, then hit Create server right below.")
        g2.setObjectName("Muted"); g2.setWordWrap(True); gv.addWidget(g2)
        g3 = QLabel("3) Hit Start on your server in Your Servers below. Friends join with your IP, or a playit.gg tunnel (see Getting Players In at the bottom).")
        g3.setObjectName("Muted"); g3.setWordWrap(True); gv.addWidget(g3)
        g4 = QLabel("Advanced settings are hidden below — you can ignore them all and just hit Create server, use a preset above, or use the Quick setup wizard for the easy path.")
        g4.setObjectName("Muted"); g4.setWordWrap(True); gv.addWidget(g4)
        v.addWidget(guide)
        v.addWidget(self._header("NEW SERVER"))

        # Guided wizard for normal humans; the full form below is for tweakers.
        wiz_b = QPushButton("🧙 Quick setup wizard"); wiz_b.setObjectName("Primary"); wiz_b.setMinimumHeight(40)
        wiz_b.clicked.connect(self._open_wizard)
        wiz_b.setToolTip("Answer 4 questions and we'll set up the server for you")
        v.addWidget(wiz_b, 0, Qt.AlignmentFlag.AlignLeft)
        adv_lab = QLabel("...or configure every option manually below.")
        adv_lab.setObjectName("Muted"); v.addWidget(adv_lab)

        # Build picker + old-build warning live above the sections.
        top = QFrame(); top.setObjectName("Card")
        tv = QVBoxLayout(top); tv.setContentsMargins(18, 14, 18, 14); tv.setSpacing(10)
        tform = QFormLayout(); tform.setSpacing(10); tform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.build_combo = QComboBox(); self.build_combo.setMinimumWidth(200)
        self.build_combo.currentIndexChanged.connect(self._on_build_changed)
        tform.addRow("Build", self.build_combo)
        self.old_warn = QLabel("Heads up: 2015–2016 builds can be janky to host and are harder to configure — "
                               "some settings and mods won't work on these old versions.")
        self.old_warn.setObjectName("Muted"); self.old_warn.setWordWrap(True)
        self.old_warn.setStyleSheet(f"color: {WARNING};")
        tform.addRow("", self.old_warn)
        self.name_edit = QLineEdit(); self.name_edit.setPlaceholderText("My Legacy ARK Server")
        tform.addRow("Server name", self.name_edit)
        self.map_combo = QComboBox()
        tform.addRow("Map", self.map_combo)
        tv.addLayout(tform)
        # v1.29.2: Create is now here, right under Build/Name/Map, instead
        # of only at the bottom after scrolling through 9 sections.
        self.create_b = QPushButton("Create server"); self.create_b.setObjectName("Primary"); self.create_b.setMinimumHeight(40)
        self.create_b.clicked.connect(self._on_create)
        tv.addWidget(self.create_b, 0, Qt.AlignmentFlag.AlignLeft)
        self.no_build_warn = QLabel("No builds installed yet — go to Versions, download any old build first, then come back here.")
        self.no_build_warn.setObjectName("Muted"); self.no_build_warn.setWordWrap(True)
        tv.addWidget(self.no_build_warn)
        v.addWidget(top)

        # ---- presets ----
        v.addWidget(self._header("QUICK SETUP"))
        # v1.43.0: label on its own row, buttons 2 per row, Reset on row 2.
        # Old single row (label + 4 presets + Reset, ~700px) forced the whole
        # Host inner widget wide, which is why intro/guide text clipped
        # off-right and did not re-wrap on resize.
        prow_lab = FlowLayout(); prow_lab.setSpacing(8)
        plab = QLabel("Start from a preset, then tweak:"); plab.setObjectName("Muted")
        prow_lab.addWidget(plab); prow_lab.addStretch(1); v.addLayout(prow_lab)
        prow = FlowLayout(); prow.setSpacing(8)
        for pname in list(self.PRESETS)[:2]:
            b = QPushButton(pname)
            b.clicked.connect(lambda _c=False, _p=pname: self._apply_preset(_p))
            prow.addWidget(b)
        prow.addStretch(1); v.addLayout(prow)
        prow2 = FlowLayout(); prow2.setSpacing(8)
        for pname in list(self.PRESETS)[2:]:
            b = QPushButton(pname)
            b.clicked.connect(lambda _c=False, _p=pname: self._apply_preset(_p))
            prow2.addWidget(b)
        reset_b = QPushButton("Reset all"); reset_b.setObjectName("Ghost")
        reset_b.clicked.connect(self._reset_form)
        prow2.addWidget(reset_b); prow2.addStretch(1); v.addLayout(prow2)

        # v1.32.0 Host revamp: the 9 settings sections (~100 options)
        # are hidden behind one toggle by default. Host page now shows
        # only guide, wizard, build/name/map/create, and presets —
        # no wall of sections to scroll through. Tap to reveal them.
        self.adv_toggle = QPushButton("Show advanced settings ▸")
        self.adv_toggle.clicked.connect(self._toggle_adv)
        v.addWidget(self.adv_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.adv_widget = QWidget(); adv = QVBoxLayout(self.adv_widget); adv.setContentsMargins(0, 0, 0, 0); adv.setSpacing(12)
        v.addWidget(self.adv_widget)
        self.adv_widget.setVisible(False)

        self._section_bodies = []
        self._section_filter = []  # [{title, body, rows:[{lab,fld,hay}], expanded}]
        # Option search: filters every section's rows by label/key/tooltip.
        srow = FlowLayout(); srow.setSpacing(8)
        srow.addWidget(QLabel("🔍"))
        self.opt_search = QLineEdit()
        self.opt_search.setPlaceholderText("Filter options…  (try: rcon, harvest, pve, port)")
        self.opt_search.setClearButtonEnabled(True)
        self.opt_search.textChanged.connect(self._filter_options)
        srow.addWidget(self.opt_search, 1)
        adv.addLayout(srow)
        self._no_match = QLabel("No options match that filter.")
        self._no_match.setObjectName("Muted"); self._no_match.setVisible(False)
        adv.addWidget(self._no_match)
        for title, subtitle, specs in self.SECTIONS:
            adv.addWidget(self._section_card(title, subtitle, specs, collapsed=title != "BASIC"))

        v.addWidget(self._header("YOUR SERVERS"))
        self.servers_box = QVBoxLayout(); self.servers_box.setSpacing(10)
        v.addLayout(self.servers_box)

        v.addWidget(self._header("GETTING PLAYERS IN"))
        net = QLabel("For friends to join, your game port (UDP) and query port (UDP) must reach your PC. "
                     "Two ways:<br>"
                     "1. <b>Port forwarding</b> — forward those ports to your PC in your router settings. Free, but every router is different.<br>"
                     "2. <b>playit.gg</b> — free tunnel, no router changes. Run playit.gg, add TCP+UDP tunnels for your game and query ports, share the tunnel address.")
        net.setObjectName("Muted"); net.setWordWrap(True); net.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(net)

        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)

    def _copy_host_names_161(self):
        _copy_text("\n".join(s.get("name", "") for s in self._hosted())); self.main.set_status(f"Copied {len(self._hosted())} server names.")
    def _host_by_map_162(self):
        counts = {}
        for s in self._hosted():
            m = s.get("map_name", s.get("map", "")) or "unknown"; counts[m] = counts.get(m, 0) + 1
        self.main.set_status(", ".join(f"{k}: {c}" for k, c in counts.items()) or "No hosted servers.")
    def _export_host_json_163(self):
        dest, _ok = QFileDialog.getSaveFileName(self, "Export servers", "servers.json", "JSON files (*.json)")
        if dest:
            Path(dest).write_text(json.dumps(self._hosted(), indent=2), encoding="utf-8"); self.main.set_status(f"Exported {len(self._hosted())} servers.")
    def _copy_host_ports_164(self):
        _copy_text(", ".join(f"{s.get('name', '')}: {s.get('port', '')}/{s.get('query', '')}" for s in self._hosted())); self.main.set_status("Server ports copied.")
    def _host_password_count_165(self):
        n = sum(1 for s in self._hosted() if (s.get("password") or "").strip()); self.main.set_status(f"{n} hosted servers have a password.")
    def _host_pve_count_166(self):
        n = sum(1 for s in self._hosted() if s.get("pve")); self.main.set_status(f"{n} hosted servers are PvE.")
    def _open_first_host_folder_167(self):
        servers = self._hosted()
        if not servers: self.main.set_status("No hosted servers."); return
        v = self._build_for(servers[0])
        if v:
            _open_url(QUrl.fromLocalFile(str(game_dir_for(self.store, v, steam_dir_for(self.store)))).toString()); self.main.set_status("Opened first server build folder.")
    def _copy_first_host_name_168(self):
        servers = self._hosted()
        if servers: _copy_text(servers[0].get("name", "")); self.main.set_status("First server name copied.")
    def _host_running_count_169(self):
        n = sum(1 for name in self._procs if self._is_running(name)); self.main.set_status(f"{n} hosted servers running.")
    def _host_count_status_170(self):
        self.main.set_status(f"{len(self._hosted())} hosted servers saved.")
    def _open_wizard(self):
        if not self._installed_builds():
            QMessageBox.warning(self, APP_NAME, "Download a build on the Versions tab first."); return
        ServerWizard(self, self).exec()

    # ---- widget builders ----
    @staticmethod
    def _header(title):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(2, 10, 2, 2); h.setSpacing(12)
        t = QLabel(title.title().replace("Dlc", "DLC")); t.setObjectName("SectionHeader"); h.addWidget(t); h.addWidget(hair(), 1); return w

    def _section_card(self, title, subtitle, specs, collapsed=True):
        wrap = QWidget(); wl = QVBoxLayout(wrap); wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(4)
        # Clickable header row: title + subtitle + expand/collapse chevron.
        hw = QWidget(); h = QHBoxLayout(hw); h.setContentsMargins(2, 10, 2, 2); h.setSpacing(12)
        t = QLabel(title.title().replace("Ini", "INI")); t.setObjectName("SectionHeader"); h.addWidget(t)
        if subtitle:
            st = QLabel(subtitle); st.setObjectName("Muted"); h.addWidget(st)
        h.addStretch(1)
        tog = QPushButton("▶" if collapsed else "▼"); tog.setObjectName("Ghost")
        tog.setFixedSize(30, 26); tog.setCursor(Qt.CursorShape.PointingHandCursor)
        h.addWidget(tog)
        wl.addWidget(hw)
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(8)
        card = QFrame(); card.setObjectName("Card")
        fv = QVBoxLayout(card); fv.setContentsMargins(18, 14, 18, 14); fv.setSpacing(10)
        form = QFormLayout(); form.setSpacing(10); form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        rows = []
        for key, label, kind, lo, hi, default, tip in specs:
            w = self._make_widget(key, label, kind, lo, hi, default, tip)
            form.addRow("" if kind == "check" else label, w)
            n = form.rowCount() - 1
            lab_i = form.itemAt(n, QFormLayout.ItemRole.LabelRole)
            fld_i = form.itemAt(n, QFormLayout.ItemRole.FieldRole)
            rows.append({
                "lab": lab_i.widget() if lab_i is not None else None,
                "fld": fld_i.widget() if fld_i is not None else None,
                "hay": f"{label} {key} {tip}".lower(),
            })
        fv.addLayout(form); bl.addWidget(card); wl.addWidget(body)
        body.setVisible(not collapsed)
        rec = {"title": title, "body": body, "rows": rows, "expanded": not collapsed}
        self._section_filter.append(rec)
        def _toggle(_c=False, _b=body, _t=tog, _r=rec):
            show = not _b.isVisible()
            _b.setVisible(show)
            _t.setText("▼" if show else "▶")
            _r["expanded"] = show
        tog.clicked.connect(_toggle)
        # Clicking the header text toggles too.
        hw.mousePressEvent = lambda e, _t=tog: _t.click() if e.button() == Qt.MouseButton.LeftButton else None
        self._section_bodies.append(body)
        return wrap

    def _filter_options(self, text):
        """Show only option rows matching the search text; auto-expand
        sections with matches. Clearing restores each section's state."""
        q = (text or "").strip().lower()
        any_match = False
        for rec in self._section_filter:
            match = False
            for r in rec["rows"]:
                show = (not q) or (q in r["hay"])
                try:
                    if r["lab"] is not None:
                        r["lab"].setVisible(show)
                    if r["fld"] is not None:
                        r["fld"].setVisible(show)
                except Exception:
                    pass
                match = match or show
            try:
                rec["body"].setVisible(match if q else rec["expanded"])
            except Exception:
                pass
            any_match = any_match or match
        try:
            self._no_match.setVisible(bool(q) and not any_match)
        except Exception:
            pass

    def _make_widget(self, key, label, kind, lo, hi, default, tip):
        if kind == "check":
            w = QCheckBox(label); w.setChecked(bool(default))
        elif kind == "rate":
            w = QDoubleSpinBox(); w.setRange(lo, hi); w.setSingleStep(0.5); w.setValue(float(default)); w.setDecimals(2)
        elif kind == "int":
            w = QSpinBox(); w.setRange(lo, hi); w.setValue(int(default))
        elif kind == "text":
            w = QPlainTextEdit(); w.setPlaceholderText(tip); w.setFixedHeight(90)
            w.setStyleSheet(f"QPlainTextEdit {{ background: {INPUT_BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px; color: {TEXT}; font-family: Consolas; }}")
        else:
            w = QLineEdit(); w.setPlaceholderText(tip)
        if tip and kind != "text":
            w.setToolTip(tip)
        self._widgets[key] = w
        return w

    def _apply_preset_dict(self, preset):
        """Apply a {key: value} dict to the form widgets."""
        for key, val in (preset or {}).items():
            w = self._widgets.get(key)
            if w is None: continue
            try:
                if isinstance(w, QCheckBox): w.setChecked(bool(val))
                elif isinstance(w, QSpinBox): w.setValue(int(val))
                elif isinstance(w, QDoubleSpinBox): w.setValue(float(val))
                elif isinstance(w, QLineEdit): w.setText(str(val))
            except Exception:
                pass

    def _toggle_adv(self):
        show = not self.adv_widget.isVisible()
        self.adv_widget.setVisible(show)
        self.adv_toggle.setText("Hide advanced settings ▾" if show else "Show advanced settings ▸")

    def _apply_preset(self, name):
        """One-click setup: reset to defaults, then apply the preset's overrides."""
        # Preset tweaks live in the advanced sections — reveal them
        # so the user can see what the preset actually changed.
        try:
            if not self.adv_widget.isVisible():
                self._toggle_adv()
        except Exception:
            pass
        self._reset_form(silent=True)
        self._apply_preset_dict(self.PRESETS.get(name, {}))
        for rec in self._section_filter:
            try:
                if not rec["body"].isVisible():
                    rec["body"].setVisible(True)
                rec["expanded"] = True
            except Exception:
                pass
        for body in self._section_bodies:
            if not body.isVisible():
                body.setVisible(True)

    def _reset_form(self, silent=False):
        for key, _label, kind, _lo, _hi, default, _t in [spec for _ti, _su, specs in self.SECTIONS for spec in specs]:
            w = self._widgets.get(key)
            if w is None: continue
            try:
                if kind == "check": w.setChecked(bool(default))
                elif kind == "rate": w.setValue(float(default))
                elif kind == "int": w.setValue(int(default))
                elif kind == "text": w.setPlainText("")
                else: w.setText("")
            except Exception:
                pass

    # ---- data ----
    def _installed_builds(self):
        store = self.store
        versions = getattr(self.main.versions, "versions", [])
        return [v for v in versions if _server_exe_for(store, v).is_file()]

    def _current_build(self):
        builds = self._installed_builds()
        i = self.build_combo.currentIndex()
        return builds[i] if 0 <= i < len(builds) else None

    def refresh(self):
        builds = self._installed_builds()
        cur = self.build_combo.currentData()
        self.build_combo.blockSignals(True)
        self.build_combo.clear()
        for v in builds:
            name = v.get("name", "Unnamed build")
            self.build_combo.addItem(name, name)
        if cur:
            idx = self.build_combo.findData(cur)
            if idx >= 0: self.build_combo.setCurrentIndex(idx)
        self.build_combo.blockSignals(False)
        self._on_build_changed()
        self._refresh_server_list()

    def _on_build_changed(self):
        v = self._current_build()
        self.map_combo.blockSignals(True)
        self.map_combo.clear()
        if v:
            dlcs = {k for k in DLC_ORDER if v.get(k)}
            for fmap, dname, dkey in HOST_MAPS:
                if dkey is None or dkey in dlcs:
                    self.map_combo.addItem(dname, fmap)
        self.map_combo.blockSignals(False)
        self.old_warn.setVisible(bool(v and _host_is_old_build(v.get("name", ""))))
        self.create_b.setEnabled(v is not None)
        try:
            self.no_build_warn.setVisible(not self._installed_builds())
        except Exception:
            pass
        self.create_b.setToolTip("Download a build on the Versions tab first." if v is None and not self._installed_builds() else "")

    @staticmethod
    def _dirname(name):
        return "CML_" + slugify(name or "server")

    def _collect(self):
        s = dict(self.DEFAULTS)
        for key, _label, kind, _lo, _hi, _d, _t in [spec for _ti, _su, specs in self.SECTIONS for spec in specs]:
            w = self._widgets[key]
            if kind == "check": s[key] = w.isChecked()
            elif kind == "rate": s[key] = float(w.value())
            elif kind == "int": s[key] = int(w.value())
            elif kind == "text": s[key] = w.toPlainText().strip()
            else: s[key] = (w.text() or "").strip()
        s["name"] = (self.name_edit.text() or "").strip() or "My Legacy ARK Server"
        s["build"] = (self._current_build() or {}).get("name", "")
        s["map"] = self.map_combo.currentData() or "TheIsland"
        s["map_name"] = self.map_combo.currentText()
        return s

    @classmethod
    def _with_defaults(cls, s):
        d = dict(cls.DEFAULTS)
        d.update(s or {})
        return d

    # ---- ini generation ----
    @staticmethod
    def _f(v):
        return ("%g" % v)

    def _build_ini(self, s):
        s = self._with_defaults(s)
        f = self._f
        L = ["[ServerSettings]"]
        if s["password"]: L.append(f"ServerPassword={s['password']}")
        L.append(f"ServerAdminPassword={s['admin']}")
        if s["spectator"]: L.append(f"SpectatorPassword={s['spectator']}")
        L.append(f"MaxPlayers={s['players']}")
        L.append(f"DifficultyOffset={f(s['difficulty'])}")
        L.append(f"OverrideOfficialDifficulty={f(s['difficulty_override'])}")
        L.append(f"ServerPVE={'True' if s['pve'] else 'False'}")
        if s["hardcore"]: L.append("ServerHardcore=True")
        L.append(f"DayTimeSpeedScale={f(s['day'])}")
        L.append(f"NightTimeSpeedScale={f(s['night'])}")
        if s["maxtamed"] > 0: L.append(f"MaxTamedDinos={s['maxtamed']}")
        if s["max_personal_tamed"] > 0: L.append(f"MaxPersonalTamedDinos={s['max_personal_tamed']}")
        L.append(f"GlobalVoiceChat={'True' if s['global_voice'] else 'False'}")
        L.append(f"ProximityChat={'True' if s['proximity_chat'] else 'False'}")
        L.append(f"AlwaysNotifyPlayerJoined={'True' if s['notify_join'] else 'False'}")
        L.append(f"AlwaysNotifyPlayerLeft={'True' if s['notify_left'] else 'False'}")
        L.append(f"AllowThirdPersonPlayer={'True' if s['third_person'] else 'False'}")
        if s["map_location"]: L.append("ShowMapPlayerLocation=True")
        if s["floating_damage"]: L.append("ShowFloatingDamageText=True")
        if s["crosshair"]: L.append("ServerCrosshair=True")
        if s["cave_pve"]: L.append("AllowCaveBuildingPVE=True")
        if s["cave_pvp"]: L.append("AllowCaveBuildingPvP=True")
        if s["flyer_carry_pve"]: L.append("AllowFlyerCarryPVE=True")
        if s["flyer_carry_pvp"]: L.append("AllowFlyerCarryPvP=True")
        if s["pve_gamma"]: L.append("DisablePvEGamma=True")
        L.append(f"AutoSavePeriodMinutes={s['autosave']}")
        if s["kick_idle"] > 0: L.append(f"KickIdlePlayersPeriod={s['kick_idle']}")
        if s["banlist"]: L.append(f"BanListURL={s['banlist']}")
        if s["respawn_interval"] > 0: L.append(f"ServerAutoForceRespawnWildDinosInterval={s['respawn_interval']}")
        if s["no_disease"]: L.append("PreventDiseases=True")
        if s["nonperm_disease"]: L.append("NonPermanentDiseases=True")
        if s["active_event"]: L.append(f"ActiveEvent={s['active_event']}")
        if s["dl_survivors"]: L.append("PreventDownloadSurvivors=True")
        if s["dl_items"]: L.append("PreventDownloadItems=True")
        if s["dl_dinos"]: L.append("PreventDownloadDinos=True")
        if s["ul_survivors"]: L.append("PreventUploadSurvivors=True")
        if s["ul_items"]: L.append("PreventUploadItems=True")
        if s["ul_dinos"]: L.append("PreventUploadDinos=True")
        if s["no_alliances"]: L.append("PreventTribeAlliances=True")
        if s["max_alliances"] > 0: L.append(f"MaxAlliancesPerTribe={s['max_alliances']}")
        if s["pvp_decay"]: L.append("PvPStructureDecay=True")
        L.append(f"PvPStructureDecayPeriodMultiplier={f(s['pvp_decay_period'])}")
        if s["disable_pve_decay"]: L.append("DisableStructureDecayPVE=True")
        L.append(f"PvEStructureDecayPeriodMultiplier={f(s['pve_decay_period'])}")
        if s["force_lock"]: L.append("ForceAllStructureLocking=True")
        if s["disable_decay_pve"]: L.append("DisableDinoDecayPvE=True")
        if s["imprint_cuddle"]: L.append("AllowAnyoneBabyImprintCuddle=True")
        if s["rcon"]:
            L.append("RCONEnabled=True")
            L.append(f"RCONPort={s['rconport']}")
        if s["mods"]: L.append(f"ActiveMods={s['mods']}")
        L.append("")
        L.append("[/Script/ShooterGame.ShooterGameUserSettings]")
        L.append(f"XPMultiplier={f(s['xp'])}")
        L.append(f"HarvestAmountMultiplier={f(s['harvest'])}")
        L.append(f"HarvestHealthMultiplier={f(s['harvest_health'])}")
        L.append(f"TamingSpeedMultiplier={f(s['tame'])}")
        L.append(f"MatingMultiplier={f(s['breed'])}")
        L.append(f"EggHatchSpeedMultiplier={f(s['breed'])}")
        L.append(f"BabyMatureSpeedMultiplier={f(s['breed'])}")
        L.append(f"CropGrowthSpeedMultiplier={f(s['crop'])}")
        L.append(f"LayEggIntervalMultiplier={f(s['layegg'])}")
        L.append(f"DinoCountMultiplier={f(s['dino_count'])}")
        L.append(f"ResourcesRespawnPeriodMultiplier={f(s['respawn_period'])}")
        L.append(f"PlayerCharacterWaterDrainMultiplier={f(s['p_water'])}")
        L.append(f"PlayerCharacterFoodDrainMultiplier={f(s['p_food'])}")
        L.append(f"PlayerCharacterStaminaDrainMultiplier={f(s['p_stam'])}")
        L.append(f"PlayerCharacterHealthRecoveryMultiplier={f(s['p_heal'])}")
        L.append(f"PlayerDamageMultiplier={f(s['p_damage'])}")
        L.append(f"PlayerResistanceMultiplier={f(s['p_resist'])}")
        L.append(f"DinoCharacterFoodDrainMultiplier={f(s['d_food'])}")
        L.append(f"DinoCharacterHealthRecoveryMultiplier={f(s['d_heal'])}")
        L.append(f"DinoCharacterStaminaDrainMultiplier={f(s['d_stam'])}")
        L.append(f"DinoDamageMultiplier={f(s['d_damage'])}")
        L.append(f"DinoResistanceMultiplier={f(s['d_resist'])}")
        L.append(f"TamedDinoDamageMultiplier={f(s['t_damage'])}")
        L.append(f"TamedDinoResistanceMultiplier={f(s['t_resist'])}")
        L.append(f"BabyFoodConsumptionSpeedMultiplier={f(s['baby_food'])}")
        L.append(f"BabyCuddleIntervalMultiplier={f(s['cuddle_interval'])}")
        L.append(f"GlobalSpoilingTimeMultiplier={f(s['spoil'])}")
        L.append(f"GlobalItemDecompositionTimeMultiplier={f(s['item_decay'])}")
        L.append(f"GlobalCorpseDecompositionTimeMultiplier={f(s['corpse_decay'])}")
        L.append(f"SupplyCrateLootQualityMultiplier={f(s['crate_loot'])}")
        L.append(f"FishingLootQualityMultiplier={f(s['fish_loot'])}")
        L.append(f"CustomRecipeEffectivenessMultiplier={f(s['recipe_effect'])}")
        L.append(f"CustomRecipeSkillMultiplier={f(s['recipe_skill'])}")
        L.append(f"StructureDamageMultiplier={f(s['s_damage'])}")
        L.append(f"StructureResistanceMultiplier={f(s['s_resist'])}")
        L.append(f"PerPlatformMaxStructuresMultiplier={f(s['platform_structs'])}")
        if s["allow_pickup"]: L.append("AlwaysAllowStructurePickup=True")
        if s["custom_gus"]:
            L.append("")
            L.append(s["custom_gus"])
        L.append("")
        return "\n".join(L)

    def _config_dir_for(self, store, version, s):
        root = _server_root_for(store, version)
        return root / "ShooterGame" / "Saved" / self._dirname(s.get("name", "")) / "Config" / "WindowsServer"

    def _write_configs(self, store, version, s):
        s = self._with_defaults(s)
        cfg_dir = self._config_dir_for(store, version, s)
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "GameUserSettings.ini").write_text(self._build_ini(s), encoding="utf-8")
        if s["custom_gameini"]:
            (cfg_dir / "Game.ini").write_text(s["custom_gameini"] + "\n", encoding="utf-8")

    # ---- create ----
    def _on_create(self):
        v = self._current_build()
        if v is None:
            QMessageBox.warning(self, APP_NAME, "Download a build on the Versions tab first."); return
        s = self._collect()
        if not s["admin"]:
            QMessageBox.warning(self, APP_NAME, "Set an admin password — you'll need it for admin commands."); return
        servers = self._hosted()
        if any(x.get("name", "").lower() == s["name"].lower() for x in servers):
            QMessageBox.warning(self, APP_NAME, f'A server named "{s["name"]}" already exists.'); return
        try:
            self._write_configs(self.store, v, s)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't write the server config:\n{e}"); return
        servers.append(s)
        self._save_hosted(servers)
        self._refresh_server_list()
        QMessageBox.information(self, APP_NAME,
            f'Server "{s["name"]}" created.\n\nHit Start to run it. The server console opens in its own window — '
            f'leave it open while people play. Make sure ports {s["port"]} and {s["query"]} (UDP) can reach your PC.')

    # ---- hosted server storage ----
    def _hosted(self):
        lst = self.store.get("hosted_servers", [])
        return list(lst) if isinstance(lst, list) else []

    def _save_hosted(self, lst):
        self.store.set("hosted_servers", lst)

    # ---- server list ----
    def _refresh_server_list(self):
        while self.servers_box.count():
            item = self.servers_box.takeAt(0)
            w = item.widget()
            if w is not None: w.deleteLater()
        servers = self._hosted()
        if not servers:
            e = QLabel("No servers yet — create one above."); e.setObjectName("Empty"); e.setWordWrap(True)
            self.servers_box.addWidget(e)
            return
        for raw in servers:
            s = self._with_defaults(raw)
            name = s.get("name", "Unnamed")
            running = self._is_running(name)
            row = QFrame(); row.setObjectName("Card")
            h = QHBoxLayout(row); h.setContentsMargins(16, 12, 16, 12); h.setSpacing(12)
            col = QVBoxLayout(); col.setSpacing(2)
            t = QLabel(name); t.setObjectName("RowTitle"); col.addWidget(t)
            flags = []
            if s.get("pve"): flags.append("PvE")
            if s.get("hardcore"): flags.append("Hardcore")
            if s.get("cluster"): flags.append("cluster")
            if s.get("mods"): flags.append("mods")
            if s.get("rcon"): flags.append("RCON")
            flag_txt = (" · " + ", ".join(flags)) if flags else ""
            sub = QLabel(f"{s.get('map_name', s.get('map', ''))} · {s.get('build', '')} · {s.get('players', '')} players{flag_txt}")
            sub.setObjectName("Muted"); col.addWidget(sub)
            st = QLabel("● Running" if running else "○ Stopped")
            st.setStyleSheet(f"color: {SUCCESS if running else MUTED}; font-weight: 700;")
            col.addWidget(st)
            h.addLayout(col, 1)
            if running:
                stop_b = QPushButton("Stop"); stop_b.clicked.connect(lambda _c=False, _n=name: self._on_stop(_n))
                h.addWidget(stop_b)
            else:
                start_b = QPushButton("Start"); start_b.setObjectName("Primary")
                start_b.clicked.connect(lambda _c=False, _n=name: self._on_start(_n))
                h.addWidget(start_b)
                exp_b = QPushButton("Export"); exp_b.setObjectName("Ghost")
                exp_b.setToolTip("Save this server's config as a file to share")
                exp_b.clicked.connect(lambda _c=False, _n=name: self._on_export(_n))
                h.addWidget(exp_b)
                del_b = QPushButton("Delete"); del_b.setObjectName("Danger")
                del_b.clicked.connect(lambda _c=False, _n=name: self._on_delete(_n))
                h.addWidget(del_b)
            self.servers_box.addWidget(row)
        # Import row at the bottom.
        imp_b = QPushButton("Import config..."); imp_b.setObjectName("Ghost")
        imp_b.setToolTip("Load a server config file someone shared with you")
        imp_b.clicked.connect(self._on_import)
        self.servers_box.addWidget(imp_b, 0, Qt.AlignmentFlag.AlignLeft)

    def _find_server(self, name):
        for s in self._hosted():
            if s.get("name") == name:
                return s
        return None

    def _build_for(self, s):
        versions = getattr(self.main.versions, "versions", [])
        for v in versions:
            if v.get("name", "") == s.get("build", ""):
                return v
        return None

    def _is_running(self, name):
        p = self._procs.get(name)
        try:
            return p is not None and p.poll() is None
        except Exception:
            return False

    def _launch_line(self, s, v):
        s = self._with_defaults(s)
        exe = _server_exe_for(self.store, v)
        q = [
            f"{s['map']}?listen",
            f'SessionName="{s["name"]}"',
            f"AltSaveDirectoryName={self._dirname(s['name'])}",
        ]
        if s.get("password"):
            q.append(f"ServerPassword={s['password']}")
        q.append(f"ServerAdminPassword={s['admin']}")
        q.append(f"MaxPlayers={s['players']}")
        q.append(f"Port={s['port']}")
        q.append(f"QueryPort={s['query']}")
        if s.get("rcon"):
            q.append("RCONEnabled=True")
            q.append(f"RCONPort={s['rconport']}")
        if s.get("cluster"):
            q.append(f"ClusterId={s['cluster']}")
        cmd = f'"{exe}" ' + "?".join(q) + " -server -log"
        if s.get("nobattleye"):
            cmd += " -NoBattlEye"
        if s.get("multihome"):
            cmd += f" -multihome={s['multihome']}"
        return cmd, exe

    def _on_start(self, name):
        s = self._find_server(name)
        if not s: return
        if self._is_running(name): return
        v = self._build_for(s)
        if v is None:
            QMessageBox.warning(self, APP_NAME, "That build isn't installed anymore."); return
        exe = _server_exe_for(self.store, v)
        if not exe.is_file():
            QMessageBox.warning(self, APP_NAME, "Server exe not found in that build."); return
        try:
            self._write_configs(self.store, v, s)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't write the server config:\n{e}"); return
        cmd, _exe = self._launch_line(s, v)
        try:
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
            proc = subprocess.Popen(cmd, cwd=str(exe.parent), creationflags=flags)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't start the server:\n{e}"); return
        self._procs[name] = proc
        self._refresh_server_list()

    def _on_stop(self, name):
        p = self._procs.get(name)
        if p is None: return
        try:
            if p.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True, timeout=15,
                               creationflags=_hidden_flags())
        except (OSError, subprocess.SubprocessError):
            pass
        self._procs.pop(name, None)
        self._refresh_server_list()

    def _on_export(self, name):
        s = self._find_server(name)
        if not s: return
        path, _ = QFileDialog.getSaveFileName(self, "Export server config",
            f"{self._dirname(name)}.json", "JSON files (*.json)")
        if not path: return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"app": APP_NAME, "kind": "hosted-server", "version": 1, "server": s},
                          f, indent=2)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't save the file:\n{e}")
            return
        QMessageBox.information(self, APP_NAME, f"Config saved.\n\nShare the file — anyone with the launcher can Import it.")

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import server config",
            "", "JSON files (*.json)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't read that file:\n{e}")
            return
        s = data.get("server") if isinstance(data, dict) else None
        if not isinstance(s, dict) or not s.get("name"):
            QMessageBox.warning(self, APP_NAME, "That file isn't a server config.")
            return
        s = self._with_defaults(s)
        servers = self._hosted()
        base = s.get("name", "Imported server")
        name = base
        i = 2
        while any(x.get("name", "").lower() == name.lower() for x in servers):
            name = f"{base} ({i})"; i += 1
        s["name"] = name
        # The build might not exist on this PC — keep the config, warn.
        if self._build_for(s) is None:
            QMessageBox.warning(self, APP_NAME,
                f'Imported "{name}", but the build "{s.get("build", "")}" isn\'t downloaded here.\n\nDownload that build on the Versions tab, then Start the server.')
        servers.append(s)
        self._save_hosted(servers)
        self._refresh_server_list()

    def _on_delete(self, name):
        if self._is_running(name):
            QMessageBox.warning(self, APP_NAME, "Stop the server before deleting it."); return
        ans = QMessageBox.question(self, APP_NAME,
            f'Delete server "{name}"?\n\nThis removes it from the list (your game build is untouched).')
        if ans != QMessageBox.StandardButton.Yes: return
        servers = [s for s in self._hosted() if s.get("name") != name]
        self._save_hosted(servers)
        self._refresh_server_list()

class ModsPage(QWidget):
    """Steam Workshop mod manager for old ARK builds. Catalog comes from
    mods.json (user-editable). Downloads via SteamCMD, installs into the
    target build's ShooterGame/Content/Mods/<workshop_id>/."""

    def __init__(self, main):
        super().__init__(); self.main = main
        self.mods = load_mods()
        self.worker = None
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner)
        v.setContentsMargins(28, 24, 28, 28); v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        v.addWidget(page_header("Mods", "One-click Steam Workshop mods for old ARK builds."))
        self.setup_hint = QLabel(""); self.setup_hint.setObjectName("Muted"); self.setup_hint.setWordWrap(True)
        v.addWidget(self.setup_hint)

        tgt = FlowLayout(); tgt.setSpacing(10)
        lab = QLabel("Install into:"); lab.setObjectName("Muted"); tgt.addWidget(lab)
        self.build_combo = QComboBox(); self.build_combo.setMinimumWidth(180)
        self.build_combo.currentIndexChanged.connect(self.refresh)
        tgt.addWidget(self.build_combo, 1)
        tgt.addStretch(1)
        v.addLayout(tgt)
        # 100-pack: search, installed-only, sort, count.
        mrow = FlowLayout(); mrow.setSpacing(10)
        self.mod_search = QLineEdit(); self.mod_search.setPlaceholderText("Search mods..."); self.mod_search.textChanged.connect(self.refresh); mrow.addWidget(self.mod_search, 1)
        self.mod_installed_cb = QCheckBox("Installed only"); self.mod_installed_cb.toggled.connect(self.refresh); mrow.addWidget(self.mod_installed_cb)
        self.mod_compat_cb = QCheckBox("Compatible with selected build only"); self.mod_compat_cb.setToolTip("Filter by the build selected on the Versions tab, using each mod's min/max range"); self.mod_compat_cb.toggled.connect(self.refresh); mrow.addWidget(self.mod_compat_cb)
        self.mod_sort = QComboBox(); self.mod_sort.addItems(["Sort: Name", "Sort: Workshop ID"]); self.mod_sort.currentIndexChanged.connect(self.refresh); mrow.addWidget(self.mod_sort)
        self.mod_count_label = QLabel(""); self.mod_count_label.setObjectName("Muted"); mrow.addWidget(self.mod_count_label)
        v.addLayout(mrow)
        # v1.31.0: Mods extra buttons removed at user's order
        # (Export mods CSV, Open first Workshop, etc. — the buttons
        # in his screenshot). Mod search, filters, and mod cards stay.

        # v1.65.0: install any Workshop mod by ID (same SteamCMD worker
        # as catalog installs — owned game only, latest mod version).
        ws = QFrame(); ws.setObjectName("Card")
        wv = QVBoxLayout(ws); wv.setContentsMargins(16, 12, 16, 12); wv.setSpacing(8)
        wt = QLabel("Install a Workshop mod by ID"); wt.setObjectName("RowTitle"); wv.addWidget(wt)
        wd = QLabel("Downloads the latest version of any Workshop mod with SteamCMD and installs it into the build selected above. "
                    "You must own ARK on Steam. Warning: this downloads the latest mod version, which may not work on very old builds — "
                    "the catalog above lists versions known to work."); wd.setObjectName("Muted"); wd.setWordWrap(True); wv.addWidget(wd)
        wrow = FlowLayout(); wrow.setSpacing(10)
        self.ws_id_e = QLineEdit(); self.ws_id_e.setPlaceholderText("Workshop ID, e.g. 123456789"); wrow.addWidget(self.ws_id_e, 1)
        ws_b = QPushButton("Install by ID"); ws_b.setObjectName("Primary"); ws_b.clicked.connect(self._on_install_by_id); wrow.addWidget(ws_b)
        chk_b = QPushButton("Check"); chk_b.clicked.connect(self._on_check_by_id); wrow.addWidget(chk_b)
        tek_chk_b = QPushButton("Check (TEK CM)"); tek_chk_b.setToolTip("Verify via TEK's Steam CM client instead of the Web API (first use downloads TEK's client DLL)")
        tek_chk_b.clicked.connect(self._on_check_by_id_tek); wrow.addWidget(tek_chk_b)
        wrow.addStretch(1); wv.addLayout(wrow)
        # v1.67.0: preview image for the checked mod (TEK's preview pane).
        self.ws_preview = QLabel(); self.ws_preview.setFixedSize(128, 128); self.ws_preview.setVisible(False)
        wv.addWidget(self.ws_preview)
        v.addWidget(ws)

        # v1.66.0: Workshop browse/search (TEK's ModInstaller, lib-free:
        # Steam's public Workshop listing pages + the existing SteamCMD
        # install worker). Best effort — if Steam's markup doesn't parse,
        # Open in browser still gets you there.
        self._ws_page = 1; self._ws_query = ""; self._ws_thread = None; self._ws_check_thread = None; self._tek_check_thread = None
        br = QFrame(); br.setObjectName("Card")
        bv = QVBoxLayout(br); bv.setContentsMargins(16, 12, 16, 12); bv.setSpacing(8)
        bt = QLabel("Browse the Workshop"); bt.setObjectName("RowTitle"); bv.addWidget(bt)
        bd = QLabel("Search Steam's public Workshop listing for ARK mods. Install uses the same SteamCMD download as the ID box above. "
                    "If no results show, Steam may have changed its page — use Open in browser instead."); bd.setObjectName("Muted"); bd.setWordWrap(True); bv.addWidget(bd)
        srow = FlowLayout(); srow.setSpacing(10)
        self.ws_search_e = QLineEdit(); self.ws_search_e.setPlaceholderText("Search the Workshop, e.g. Structures Plus"); srow.addWidget(self.ws_search_e, 1)
        s_b = QPushButton("Search"); s_b.setObjectName("Primary"); s_b.clicked.connect(lambda: self._on_workshop_search(1)); srow.addWidget(s_b)
        ob_b = QPushButton("Open in browser"); ob_b.clicked.connect(self._on_workshop_open_browser); srow.addWidget(ob_b)
        srow.addStretch(1); bv.addLayout(srow)
        prow = FlowLayout(); prow.setSpacing(10)
        self.ws_prev_b = QPushButton("← Prev"); self.ws_prev_b.setEnabled(False); self.ws_prev_b.clicked.connect(lambda: self._on_workshop_search(self._ws_page - 1)); prow.addWidget(self.ws_prev_b)
        self.ws_page_l = QLabel(""); self.ws_page_l.setObjectName("Muted"); prow.addWidget(self.ws_page_l)
        self.ws_next_b = QPushButton("Next →"); self.ws_next_b.setEnabled(False); self.ws_next_b.clicked.connect(lambda: self._on_workshop_search(self._ws_page + 1)); prow.addWidget(self.ws_next_b)
        prow.addStretch(1); bv.addLayout(prow)
        self.ws_results = QVBoxLayout(); self.ws_results.setSpacing(6)
        bv.addLayout(self.ws_results)
        v.addWidget(br)

        # v1.67.0: mod update check (TEK's UpdateAvailable status,
        # lib-free: Steam's time_updated vs your copy's download time).
        self._mu_thread = None
        mu = QFrame(); mu.setObjectName("Card")
        mv = QVBoxLayout(mu); mv.setContentsMargins(16, 12, 16, 12); mv.setSpacing(8)
        mt = QLabel("Mod updates"); mt.setObjectName("RowTitle"); mv.addWidget(mt)
        md = QLabel("Compares Steam's last-updated time against when your copy was downloaded, for every mod installed in the build selected above. "
                    "A hit means Steam's version is newer — it may have an update, so check the changelog before reinstalling."); md.setObjectName("Muted"); md.setWordWrap(True); mv.addWidget(md)
        mu_b = QPushButton("Check for mod updates"); mu_b.setObjectName("Primary"); mu_b.clicked.connect(self._on_check_mod_updates); mv.addWidget(mu_b)
        self.mu_results = QVBoxLayout(); self.mu_results.setSpacing(6)
        mv.addLayout(self.mu_results)
        v.addWidget(mu)

        self.status_label = QLabel(""); self.status_label.setObjectName("Muted"); self.status_label.setWordWrap(True)
        v.addWidget(self.status_label)

        self.cards_box = QVBoxLayout(); self.cards_box.setSpacing(10)
        v.addLayout(self.cards_box)
        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)

    def _installed_builds(self):
        store = self.main.store
        steam = steam_dir_for(store)
        out = []
        for v in getattr(self.main.versions, "versions", []):
            exe = game_exe_for(steam, v, store)
            if exe and Path(exe).is_file():
                out.append(v)
        return out

    def _target(self):
        idx = self.build_combo.currentIndex()
        if 0 <= idx < len(self._builds):
            return self._builds[idx]
        return None

    def _mods_dir(self, version):
        steam = steam_dir_for(self.main.store)
        if not steam:
            return None
        return game_dir_for(self.main.store, version, steam) / "ShooterGame" / "Content" / "Mods"

    def refresh(self):
        store = self.main.store
        # Target build combo
        self._builds = self._installed_builds()
        self.build_combo.blockSignals(True)
        self.build_combo.clear()
        for v in self._builds:
            self.build_combo.addItem(v.get("name", ""), v.get("name", ""))
        # Prefer the build selected on Versions, else most recently played.
        prefer = ""
        sel = getattr(self.main.versions, "selected", None)
        if sel and sel.get("name"):
            prefer = sel.get("name", "")
        if not prefer:
            recent = store.get("recently_played", []) or []
            if recent: prefer = recent[0]
        if prefer:
            idx = self.build_combo.findData(prefer)
            if idx >= 0: self.build_combo.setCurrentIndex(idx)
        self.build_combo.blockSignals(False)

        if not steamcmd_ready() or not (store.get("steam_username", "") or "").strip():
            self.setup_hint.setText("Heads up: mod installs need SteamCMD + your Steam username (Settings → Steam). The list below still works — you'll just be asked to set those up first.")
        else:
            self.setup_hint.setText("")

        while self.cards_box.count():
            item = self.cards_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not self.mods:
            hint = QLabel("No mods in mods.json — add entries to the file next to the app and reopen this tab."); hint.setObjectName("Muted")
            self.cards_box.addWidget(hint)
            return
        target = self._target()
        mods_dir = self._mods_dir(target) if target else None
        _mods = list(self.mods)
        _q = (self.mod_search.text().lower() if hasattr(self, "mod_search") else "")
        if _q:
            _mods = [x for x in _mods if _q in x["name"].lower() or _q in x["description"].lower() or _q in x["workshop_id"]]
        if hasattr(self, "mod_compat_cb") and self.mod_compat_cb.isChecked():
            _sel = getattr(self.main.versions, "selected", None)
            if _sel and _sel.get("name"):
                _mods = [x for x in _mods if mod_compatible(x, _sel.get("name", ""))]
        if hasattr(self, "mod_installed_cb") and self.mod_installed_cb.isChecked():
            _mods = [x for x in _mods if mods_dir is not None and (mods_dir / x["workshop_id"]).is_dir()]
        if hasattr(self, "mod_sort") and self.mod_sort.currentText().endswith("Workshop ID"):
            _mods.sort(key=lambda x: x["workshop_id"])
        else:
            _mods.sort(key=lambda x: x["name"].lower())
        try:
            self.mod_count_label.setText(f"{len(_mods)} of {len(self.mods)} mods")
        except Exception:
            pass
        for m in _mods:
            card = QFrame(); card.setObjectName("Card")
            lay = QVBoxLayout(card); lay.setContentsMargins(16, 12, 16, 12); lay.setSpacing(4)
            top = FlowLayout()
            t = QLabel(m["name"]); t.setObjectName("RowTitle"); top.addWidget(t, 1)
            inst = mods_dir is not None and (mods_dir / m["workshop_id"]).is_dir()
            badge = QLabel("✓ Installed" if inst else "Not installed")
            badge.setStyleSheet(f"color: {'#5FBF6E' if inst else '#9A958C'}; font-weight: 700;")
            top.addWidget(badge)
            lay.addLayout(top)
            d = QLabel(m["description"]); d.setObjectName("Muted"); d.setWordWrap(True); lay.addWidget(d)
            _selname = (getattr(self.main.versions, "selected", None) or {}).get("name", "") if hasattr(self.main, "versions") else ""
            _compat_note = ""
            if _selname:
                _compat_note = f"  ·  {'✓ Compatible' if mod_compatible(m, _selname) else '✗ Not for'} {_selname}"
            compat = "  ·  ".join(x for x in [f"Workshop ID {m['workshop_id']} ({chr(10003) if is_valid_workshop_id(m['workshop_id']) else 'Invalid ID'})",
                                              f"Works with: {m['min_build']} – {m['max_build']}".strip(" –")] if x) + _compat_note
            c = QLabel(compat); c.setObjectName("Muted"); lay.addWidget(c)
            row = FlowLayout(); row.addStretch(1)
            cp = QPushButton("Copy ID"); cp.clicked.connect(lambda _c=False, _id=m["workshop_id"]: _copy_text(_id)); row.addWidget(cp)
            if inst:
                of = QPushButton("Open folder"); of.clicked.connect(lambda _c=False, _d=(mods_dir / m["workshop_id"] if mods_dir else None): _open_url(QUrl.fromLocalFile(str(_d)).toString()) if _d else None); row.addWidget(of)
                rm = QPushButton("Remove"); rm.setObjectName("Danger")
                rm.clicked.connect(lambda _c=False, _m=m: self._on_remove(_m))
                row.addWidget(rm)
            else:
                ins = QPushButton("Install"); ins.setObjectName("Primary"); ins.setMinimumHeight(40)
                ins.setEnabled(target is not None)
                ins.clicked.connect(lambda _c=False, _m=m: self._on_install(_m))
                row.addWidget(ins)
            lay.addLayout(row)
            self.cards_box.addWidget(card)
        if not self._builds:
            hint = QLabel("No builds installed yet — download one on the Versions tab first."); hint.setObjectName("Muted")
            self.cards_box.addWidget(hint)

    def _copy_all_mod_names_151(self):
        _copy_text("\n".join(x["name"] for x in self.mods)); self.status_label.setText(f"Copied {len(self.mods)} mod names.")
    def _export_mods_csv_152(self):
        dest, _ok = QFileDialog.getSaveFileName(self, "Export mods", "mods.csv", "CSV files (*.csv)")
        if dest:
            rows = [[x["name"], x["workshop_id"], x["min_build"], x["max_build"]] for x in self.mods]
            self.status_label.setText(f"Exported {write_csv_rows(dest, ['name', 'workshop_id', 'min_build', 'max_build'], rows)} mods.")
    def _compatible_count_153(self):
        sel = getattr(self.main.versions, "selected", None)
        name = sel.get("name", "") if sel else ""
        n = sum(1 for x in self.mods if name and mod_compatible(x, name)) if name else 0
        self.status_label.setText(f"{n} mods compatible with {name or 'no selected build'}.")
    def _long_ids_count_154(self):
        n = sum(1 for x in self.mods if len(x["workshop_id"]) >= 10)
        self.status_label.setText(f"{n} mods have Workshop IDs of 10+ digits.")
    def _open_first_workshop_155(self):
        if self.mods:
            _open_url(f"https://steamcommunity.com/sharedfiles/filedetails/?id={self.mods[0]['workshop_id']}")
            self.status_label.setText(f"Opened Workshop page for {self.mods[0]['name']}.")
    def _on_install(self, mod):
        if self.worker and self.worker.isRunning():
            return
        target = self._target()
        if not target:
            QMessageBox.information(self, APP_NAME, "Install a build on the Versions tab first, then come back.")
            return
        store = self.main.store
        if not steamcmd_ready() or not (store.get("steam_username", "") or "").strip():
            QMessageBox.information(self, APP_NAME,
                "Mod installs need two things first:\n\n1. SteamCMD — Settings → Steam → Set up SteamCMD\n2. Your Steam username — Settings → Steam\n\n(Username only — you type the password in Steam's own window.)")
            return
        steam = steam_dir_for(store)
        game_dir = game_dir_for(store, target, steam)
        self.status_label.setText(f"Installing {mod['name']} into {target.get('name', '')}...")
        self.worker = _ModDownloadThread(mod["workshop_id"], mod["name"], game_dir,
                                         username=store.get("steam_username", ""))
        self.worker.progress.connect(self.status_label.setText)
        self.worker.done.connect(self._on_installed)
        self.worker.start()

    def _on_installed(self, ok, msg):
        self.status_label.setText(msg)
        try:
            _main = getattr(self, "main", None)
            _tray = getattr(_main, "tray", None) if _main is not None else None
            if ok and _main is not None and not _main.isVisible() and _tray is not None:
                _tray.showMessage(APP_NAME, f"Mod installed — {msg}",
                                  QSystemTrayIcon.MessageIcon.Information, 5000)
        except Exception:
            pass
        if not ok:
            QMessageBox.warning(self, APP_NAME, msg)
        self.refresh()

    def _on_remove(self, mod):
        target = self._target()
        if not target:
            return
        mods_dir = self._mods_dir(target)
        dest = mods_dir / mod["workshop_id"] if mods_dir else None
        if dest is None or not dest.is_dir():
            return
        ans = QMessageBox.question(self, APP_NAME,
            f"Remove {mod['name']} from {target.get('name', '')}?\n\nThis deletes the mod's folder. Your saves are untouched.")
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(dest)
            self.status_label.setText(f"{mod['name']} removed.")
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't remove it: {e}")
        self.refresh()


    def _on_install_by_id(self):
        """v1.65.0: install any Workshop mod by ID, reusing the catalog
        install worker (owned game only, latest mod version)."""
        if self.worker and self.worker.isRunning():
            return
        wid = (self.ws_id_e.text() or "").strip()
        if not wid.isdigit() or not is_valid_workshop_id(wid):
            QMessageBox.warning(self, APP_NAME, "Enter a valid Workshop ID (digits only).")
            return
        self._install_workshop_id(wid)

    def _install_workshop_id(self, wid):
        """Shared install path for the ID box + Workshop browse results."""
        if self.worker and self.worker.isRunning():
            return
        target = self._target()
        if not target:
            QMessageBox.information(self, APP_NAME, "Install a build on the Versions tab first, then come back.")
            return
        store = self.main.store
        if not steamcmd_ready() or not (store.get("steam_username", "") or "").strip():
            QMessageBox.information(self, APP_NAME,
                "Mod installs need two things first:\n\n1. SteamCMD — Settings → Steam → Set up SteamCMD\n2. Your Steam username — Settings → Steam\n\n(Username only — you type the password in Steam's own window.)")
            return
        steam = steam_dir_for(store)
        game_dir = game_dir_for(store, target, steam)
        self.status_label.setText(f"Installing Workshop mod {wid} into {target.get('name', '')}...")
        self.worker = _ModDownloadThread(wid, f"Workshop mod {wid}", game_dir,
                                         username=store.get("steam_username", ""))
        self.worker.progress.connect(self.status_label.setText)
        self.worker.done.connect(self._on_installed)
        self.worker.start()

    def _on_check_by_id(self):
        """v1.66.0: verify an ID is a real ARK mod before downloading."""
        if self._ws_check_thread is not None and self._ws_check_thread.isRunning():
            return
        wid = (self.ws_id_e.text() or "").strip()
        if not wid.isdigit() or not is_valid_workshop_id(wid):
            QMessageBox.warning(self, APP_NAME, "Enter a valid Workshop ID (digits only).")
            return
        self.status_label.setText(f"Checking Workshop mod {wid}...")
        self._ws_check_thread = _ModCheckThread(wid)
        self._ws_check_thread.done.connect(self._on_checked_by_id)
        self._ws_check_thread.start()

    def _on_checked_by_id(self, res):
        self._ws_check_thread = None
        try:
            self.ws_preview.setVisible(False)
            preview = res.get("preview")
            if preview:
                pm = QPixmap()
                if pm.loadFromData(preview) and not pm.isNull():
                    self.ws_preview.setPixmap(pm.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    self.ws_preview.setVisible(True)
        except Exception:
            pass
        try:
            if res.get("error"):
                self.status_label.setText("Couldn't verify that ID — check your connection. Install still works from the ID box.")
            elif not res.get("found"):
                self.status_label.setText(f"No Workshop mod with ID {res.get('wid', '')}.")
            elif res.get("app_id") == 346110:
                self.status_label.setText(f"ARK mod: {res.get('title', '')} ({res.get('wid', '')}) — good to install.")
            else:
                self.status_label.setText(f"Not an ARK mod (it's for app {res.get('app_id')}) — don't install it into ARK.")
        except Exception:
            self.status_label.setText("Couldn't verify that ID.")

    def _on_check_by_id_tek(self):
        """v1.72.0: same ID check as 'Check', but through TEK's CM
        client (tek_steamclient) instead of the public Web API. The
        result lands in the same handler, prefixed so the user can
        tell which path answered."""
        if self._tek_check_thread is not None and self._tek_check_thread.isRunning():
            return
        wid = (self.ws_id_e.text() or "").strip()
        if not wid.isdigit() or not is_valid_workshop_id(wid):
            QMessageBox.warning(self, APP_NAME, "Enter a valid Workshop ID (digits only).")
            return
        self.status_label.setText(f"Checking Workshop mod {wid} via TEK CM (first use downloads TEK's client DLL)…")
        self._tek_check_thread = _TekCmCheckThread(wid)
        self._tek_check_thread.done.connect(self._on_checked_by_id_tek)
        self._tek_check_thread.start()

    def _on_checked_by_id_tek(self, res):
        self._tek_check_thread = None
        self._on_checked_by_id(res)
        try:
            cur = self.status_label.text()
            if res.get("error"):
                self.status_label.setText(f"TEK CM check failed: {res['error']} — the normal Check button uses the Web API instead.")
            elif cur:
                self.status_label.setText(f"[via TEK CM] {cur}")
        except Exception:
            pass

    def _on_check_mod_updates(self):
        """v1.67.0: check installed mods in the target build for newer
        Steam versions (TEK's UpdateAvailable, without their lib)."""
        if self._mu_thread is not None and self._mu_thread.isRunning():
            return
        target = self._target()
        if not target:
            self.status_label.setText("No builds installed yet — download one on the Versions tab first."); return
        mods_dir = self._mods_dir(target)
        if mods_dir is None or not mods_dir.is_dir():
            self.status_label.setText(f"No mods installed in {target.get('name', '')} yet."); return
        items = []
        try:
            for entry in mods_dir.iterdir():
                if entry.is_dir() and entry.name.isdigit():
                    try: items.append((entry.name, entry.stat().st_mtime))
                    except OSError: pass
        except OSError:
            items = []
        if not items:
            self.status_label.setText(f"No mods installed in {target.get('name', '')} yet."); return
        self.status_label.setText(f"Checking {len(items)} installed mod(s) for updates...")
        self._mu_thread = _ModUpdatesThread(items)
        self._mu_thread.done.connect(self._on_mod_updates)
        self._mu_thread.start()

    def _on_mod_updates(self, updates, error):
        self._mu_thread = None
        while self.mu_results.count():
            item = self.mu_results.takeAt(0)
            w = item.widget()
            if w is not None: w.deleteLater()
        if error:
            self.status_label.setText(error); return
        if not updates:
            self.status_label.setText("All installed mods look up to date."); return
        self.status_label.setText(f"{len(updates)} mod(s) may have an update — check the changelog before reinstalling.")
        for wid, title, steam_t, local_t in updates:
            row = QFrame(); row.setObjectName("Card")
            rv = QHBoxLayout(row); rv.setContentsMargins(12, 8, 12, 8); rv.setSpacing(10)
            try:
                s_date = datetime.datetime.fromtimestamp(steam_t).strftime("%Y-%m-%d")
                l_date = datetime.datetime.fromtimestamp(local_t).strftime("%Y-%m-%d")
            except (OSError, OverflowError, ValueError):
                s_date = "?"; l_date = "?"
            lab = QLabel(f"{title} — Steam updated {s_date} · yours from {l_date}"); lab.setWordWrap(True); rv.addWidget(lab, 1)
            upd = QPushButton("Update"); upd.setObjectName("Primary")
            upd.clicked.connect(lambda _c=False, _w=wid: self._install_workshop_id(_w))
            rv.addWidget(upd)
            self.mu_results.addWidget(row)

    def _on_workshop_search(self, page):
        """v1.66.0: search Steam's public Workshop listing for ARK mods."""
        if self._ws_thread is not None and self._ws_thread.isRunning():
            return
        query = (self.ws_search_e.text() or "").strip()
        if not query:
            self.status_label.setText("Type something to search for first.")
            return
        page = max(1, page)
        self._ws_query = query; self._ws_page = page
        self.status_label.setText(f"Searching the Workshop for '{query}' (page {page})...")
        self.ws_prev_b.setEnabled(False); self.ws_next_b.setEnabled(False)
        self.ws_page_l.setText(f"Page {page}")
        self._ws_thread = _WorkshopSearchThread(query, page)
        self._ws_thread.done.connect(self._on_workshop_results)
        self._ws_thread.start()

    def _on_workshop_results(self, results, error):
        self._ws_thread = None
        while self.ws_results.count():
            item = self.ws_results.takeAt(0)
            w = item.widget()
            if w is not None: w.deleteLater()
        if error:
            self.status_label.setText(error)
        elif not results:
            self.status_label.setText("No results — Steam may have changed its Workshop page. Try Open in browser.")
        else:
            self.status_label.setText(f"Found {len(results)} mod(s) — page {self._ws_page}.")
            for wid, title in results:
                row = QFrame(); row.setObjectName("Card")
                rv = QHBoxLayout(row); rv.setContentsMargins(12, 8, 12, 8); rv.setSpacing(10)
                lab = QLabel(title); lab.setWordWrap(True); rv.addWidget(lab, 1)
                inst = QPushButton("Install"); inst.setObjectName("Primary")
                inst.clicked.connect(lambda _c=False, _w=wid: self._install_workshop_id(_w))
                rv.addWidget(inst)
                op = QPushButton("Open page")
                op.clicked.connect(lambda _c=False, _w=wid: _open_url(f"https://steamcommunity.com/sharedfiles/filedetails/?id={_w}"))
                rv.addWidget(op)
                self.ws_results.addWidget(row)
        self.ws_prev_b.setEnabled(self._ws_page > 1)
        self.ws_next_b.setEnabled(bool(results))

    def _on_workshop_open_browser(self):
        query = (self.ws_search_e.text() or "").strip()
        url = "https://steamcommunity.com/workshop/browse/?appid=346110"
        if query: url += "&searchtext=" + urllib.parse.quote(query)
        _open_url(url)

class BackupsPage(QWidget):
    """Saved-folder backups: one-click now, auto-backup before downloads,
    restore (never deletes the live folder — it renames it to .bak first)."""

    def __init__(self, main):
        super().__init__(); self.main = main
        self.worker = None
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner)
        v.setContentsMargins(28, 24, 28, 28); v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        v.addWidget(page_header("Backups", "Your Saved folders — backed up and restorable."))

        auto = QFrame(); auto.setObjectName("Card")
        ah = QHBoxLayout(auto); ah.setContentsMargins(16, 12, 16, 12); ah.setSpacing(16)
        col = QVBoxLayout(); col.setSpacing(2)
        t = QLabel("Auto-backup before downloads"); t.setObjectName("RowTitle"); col.addWidget(t)
        s = QLabel("Zip the build's Saved folder automatically before any download/update starts."); s.setObjectName("Muted"); s.setWordWrap(True); col.addWidget(s)
        ah.addLayout(col, 1)
        self.auto_t = ToggleSwitch(bool(self.main.store.get("auto_backup")))
        self.auto_t.toggled.connect(lambda on: self.main.store.set("auto_backup", on))
        ah.addWidget(self.auto_t, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(auto)

        tgt = FlowLayout(); tgt.setSpacing(10)
        lab = QLabel("Build:"); lab.setObjectName("Muted"); tgt.addWidget(lab)
        self.build_combo = QComboBox(); self.build_combo.setMinimumWidth(180)
        tgt.addWidget(self.build_combo, 1)
        self.backup_b = QPushButton("Back up now"); self.backup_b.setObjectName("Primary"); self.backup_b.setMinimumHeight(40)
        self.backup_b.clicked.connect(self._on_backup_now)
        tgt.addWidget(self.backup_b)
        open_b = QPushButton("Open folder"); open_b.clicked.connect(self._on_open_folder)
        tgt.addWidget(open_b)
        v.addLayout(tgt)

        self.status_label = QLabel(""); self.status_label.setObjectName("Muted"); self.status_label.setWordWrap(True)
        v.addWidget(self.status_label)
        self.backup_search = QLineEdit(); self.backup_search.setPlaceholderText("Search backups..."); self.backup_search.textChanged.connect(self.refresh); v.addWidget(self.backup_search)
        self.backup_summary = QLabel(""); self.backup_summary.setObjectName("Muted"); v.addWidget(self.backup_summary)
        # v1.29.2: split into two rows so buttons never squeeze to letters
        brow = FlowLayout(); brow.setSpacing(10)
        for _txt, _fn in [("Oldest backup", self._backup_oldest_156), ("Newest backup", self._backup_newest_157), ("Copy backup names", self._copy_backup_names_158)]:
            _b = QPushButton(_txt); _b.clicked.connect(_fn); brow.addWidget(_b)
        brow.addStretch(1); v.addLayout(brow)
        brow2 = FlowLayout(); brow2.setSpacing(10)
        for _txt, _fn in [("Export backup CSV", self._export_backup_csv_159), ("Largest backup", self._largest_backup_160)]:
            _b = QPushButton(_txt); _b.clicked.connect(_fn); brow2.addWidget(_b)
        brow2.addStretch(1); v.addLayout(brow2)

        self.list_box = QVBoxLayout(); self.list_box.setSpacing(10)
        v.addLayout(self.list_box)
        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)

    def _installed_builds(self):
        store = self.main.store
        steam = steam_dir_for(store)
        out = []
        for v in getattr(self.main.versions, "versions", []):
            exe = game_exe_for(steam, v, store)
            if exe and Path(exe).is_file():
                out.append(v)
        return out

    def _target(self):
        idx = self.build_combo.currentIndex()
        if 0 <= idx < len(self._builds):
            return self._builds[idx]
        return None

    def _backup_files(self):
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            files = sorted(BACKUP_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
            return files
        except OSError:
            return []

    def _backup_oldest_156(self):
        files = self._backup_files()
        self.status_label.setText(f"Oldest backup: {files[-1].name if files else 'none'}")
    def _backup_newest_157(self):
        files = self._backup_files()
        self.status_label.setText(f"Newest backup: {files[0].name if files else 'none'}")
    def _copy_backup_names_158(self):
        files = self._backup_files(); _copy_text("\n".join(f.name for f in files)); self.status_label.setText(f"Copied {len(files)} backup names.")
    def _export_backup_csv_159(self):
        dest, _ok = QFileDialog.getSaveFileName(self, "Export backups", "backups.csv", "CSV files (*.csv)")
        if dest:
            files = self._backup_files()
            rows = [[f.name, fmt_bytes(f.stat().st_size), human_date(f.stat().st_mtime)] for f in files]
            self.status_label.setText(f"Exported {write_csv_rows(dest, ['name', 'size', 'date'], rows)} backups.")
    def _largest_backup_160(self):
        files = self._backup_files()
        if files:
            big = max(files, key=lambda f: f.stat().st_size)
            self.status_label.setText(f"Largest backup: {big.name} ({fmt_bytes(big.stat().st_size)})")
        else:
            self.status_label.setText("No backups yet.")
    def refresh(self):
        self.auto_t.setChecked(bool(self.main.store.get("auto_backup")))
        self._builds = self._installed_builds()
        self.build_combo.blockSignals(True)
        self.build_combo.clear()
        for v in self._builds:
            self.build_combo.addItem(v.get("name", ""), v.get("name", ""))
        sel = getattr(self.main.versions, "selected", None)
        if sel and sel.get("name"):
            idx = self.build_combo.findData(sel.get("name", ""))
            if idx >= 0: self.build_combo.setCurrentIndex(idx)
        self.build_combo.blockSignals(False)

        while self.list_box.count():
            item = self.list_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        files = self._backup_files()
        try:
            _tot = sum(f.stat().st_size for f in files if f.is_file())
            self.backup_summary.setText(f"{len(files)} backups · {fmt_bytes(_tot)} total")
        except Exception:
            pass
        _q = (self.backup_search.text().lower() if hasattr(self, "backup_search") else "")
        if _q:
            files = [f for f in files if _q in f.name.lower()]
        if not files:
            hint = QLabel("No backups yet — hit Back up now to zip a build's Saved folder."); hint.setObjectName("Muted")
            self.list_box.addWidget(hint)
            return
        for f in files:
            try:
                size_mb = f.stat().st_size / (1024 * 1024)
                dt = time.strftime("%b %d, %Y %H:%M", time.localtime(f.stat().st_mtime))
            except OSError:
                continue
            card = QFrame(); card.setObjectName("Card")
            h = QHBoxLayout(card); h.setContentsMargins(16, 10, 16, 10); h.setSpacing(12)
            col = QVBoxLayout(); col.setSpacing(2)
            t = QLabel(f.stem); t.setObjectName("RowTitle"); col.addWidget(t)
            s = QLabel(f"{dt}  ·  {size_mb:.1f} MB"); s.setObjectName("Muted"); col.addWidget(s)
            h.addLayout(col, 1)
            rs = QPushButton("Restore"); rs.clicked.connect(lambda _c=False, _f=f: self._on_restore(_f))
            cp = QPushButton("Copy path"); cp.clicked.connect(lambda _c=False, _f=f: _copy_text(str(_f))); h.addWidget(cp)
            dl = QPushButton("Delete"); dl.setObjectName("Danger"); dl.setMinimumHeight(40); dl.clicked.connect(lambda _c=False, _f=f: self._on_delete(_f))
            h.addWidget(rs); h.addWidget(dl)
            self.list_box.addWidget(card)

    def _on_backup_now(self):
        if self.worker and self.worker.isRunning():
            return
        target = self._target()
        if not target:
            QMessageBox.information(self, APP_NAME, "Install a build on the Versions tab first.")
            return
        saved = _saved_dir_for(self.main.store, target)
        if saved is None or not saved.is_dir():
            QMessageBox.information(self, APP_NAME, "That build has no Saved folder yet — play it once first, then back it up.")
            return
        ts = time.strftime("%Y%m%d-%H%M%S")
        dest = BACKUP_DIR / f"{slugify(target.get('name', 'build'))}_{ts}.zip"
        self.status_label.setText("Backing up Saved folder...")
        self.backup_b.setEnabled(False)
        self.worker = _BackupThread(saved, dest)
        self.worker.done.connect(self._on_backup_done)
        self.worker.start()

    def _on_backup_done(self, ok, msg):
        self.backup_b.setEnabled(True)
        self.status_label.setText(msg)
        if not ok:
            QMessageBox.warning(self, APP_NAME, msg)
        self.refresh()

    def _on_restore(self, f):
        target = self._target()
        if not target:
            QMessageBox.information(self, APP_NAME, "Pick the build this backup belongs to first.")
            return
        ans = QMessageBox.question(self, APP_NAME,
            f"Restore {f.name}?\n\nYour current Saved folder is NOT deleted — it's renamed to Saved.bak first, so you can always go back.")
        if ans != QMessageBox.StandardButton.Yes:
            return
        saved = _saved_dir_for(self.main.store, target)
        if saved is None:
            QMessageBox.warning(self, APP_NAME, "Couldn't locate that build's folder.")
            return
        try:
            if saved.is_dir():
                bak = saved.parent / f"Saved.bak-{time.strftime('%Y%m%d-%H%M%S')}"
                saved.rename(bak)
            saved.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(f, "r") as z:
                z.extractall(saved)
            self.status_label.setText(f"Restored {f.name} (old Saved kept as Saved.bak).")
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Restore failed: {e}")
        self.refresh()

    def _on_delete(self, f):
        ans = QMessageBox.question(self, APP_NAME, f"Delete backup {f.name}?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            f.unlink()
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't delete it: {e}")
        self.refresh()

    def _on_open_folder(self):
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            _open_url(QUrl.fromLocalFile(str(BACKUP_DIR)).toString())
        except Exception:
            pass


class FramelessResizeFilter(QObject):
    """Pure-Qt edge/corner resizing for the frameless main window.

    Installed on the QApplication: watches mouse events over the main
    window and turns its 7px border into resize handles. Deliberately
    no ctypes / native messages — the WM_NCHITTEST approach crashed
    on real machines.
    """
    EDGE = 7
    MIN_W, MIN_H = 1080, 680
    _CURSORS = {
        "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
        "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
        "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._drag = None   # (direction, global start QPoint, geometry QRect)
        self._hover = None  # active override-cursor direction (or None)
        win.setMouseTracking(True)
        for w in win.findChildren(QWidget):
            w.setMouseTracking(True)

    def _direction(self, gpos):
        win = self.win
        pt = win.mapFromGlobal(gpos)
        e, w, h = self.EDGE, win.width(), win.height()
        left = pt.x() <= e
        right = pt.x() >= w - e
        top = pt.y() <= e
        bottom = pt.y() >= h - e
        if top and left: return "tl"
        if top and right: return "tr"
        if bottom and left: return "bl"
        if bottom and right: return "br"
        if left: return "l"
        if right: return "r"
        if top: return "t"
        if bottom: return "b"
        return None

    def _set_hover(self, d):
        if d == self._hover:
            return
        if self._hover is not None:
            QApplication.restoreOverrideCursor()
        self._hover = d
        if d is not None:
            QApplication.setOverrideCursor(self._CURSORS[d])

    def _over_titlebar(self, obj):
        tb = getattr(self.win, "titlebar", None)
        return tb is not None and (obj is tb or tb.isAncestorOf(obj))

    def eventFilter(self, obj, ev):
        win = self.win
        try:
            if obj is not win and not win.isAncestorOf(obj):
                return False
            if win.isMaximized() or win.isFullScreen() or not win.isVisible():
                self._drag = None
                self._set_hover(None)
                return False
            t = ev.type()
            if t == QEvent.Type.Leave and obj is win:
                self._set_hover(None)
                return False
            if t == QEvent.Type.MouseMove:
                gpos = ev.globalPosition().toPoint()
                if self._drag:
                    self._do_resize(gpos)
                    return True
                # v1.33.0: buttons eat clicks, titlebar empty space does
                # not. Previously ANY mouse over the titlebar (now also
                # the nav tabs area) blocked edge resizing, so dragging
                # the top edge felt broken. Now: button -> no resize,
                # titlebar background / edge -> resize works.
                if isinstance(obj, QPushButton):
                    self._set_hover(None)
                    return False
                self._set_hover(self._direction(gpos))
                return False
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                if isinstance(obj, QPushButton):
                    return False
                d = self._direction(ev.globalPosition().toPoint())
                if d:
                    self._drag = (d, ev.globalPosition().toPoint(), win.geometry())
                    self._set_hover(d)
                    return True
                return False
            if t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
                if self._drag:
                    self._drag = None
                    self._set_hover(None)
                    return True
                return False
        except Exception:
            pass
        return False

    def _do_resize(self, gpos):
        d, start, geom = self._drag
        dx = gpos.x() - start.x()
        dy = gpos.y() - start.y()
        g = QRect(geom)
        if "r" in d: g.setRight(geom.right() + dx)
        if "l" in d: g.setLeft(geom.left() + dx)
        if "b" in d: g.setBottom(geom.bottom() + dy)
        if "t" in d: g.setTop(geom.top() + dy)
        if g.width() < self.MIN_W:
            if "l" in d: g.setLeft(g.right() - self.MIN_W + 1)
            else: g.setWidth(self.MIN_W)
        if g.height() < self.MIN_H:
            if "t" in d: g.setTop(g.bottom() - self.MIN_H + 1)
            else: g.setHeight(self.MIN_H)
        self.win.setGeometry(g)


# ------------------------------------------------------------------ 100 improvements pack (v1.24.0)
# Helpers, a Tools page, and small cross-page improvements. Every item
# in IMPROVEMENTS-100.md is backed by a function, a widget, or a wiring
# change below or in the patched pages — not just a comment.

def fmt_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"

def fmt_gb(n):
    try:
        return f"{float(n):.1f} GB"
    except (TypeError, ValueError):
        return "—"

def fmt_duration(seconds):
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "—"
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m" if h else f"{m}m {s}s"

def human_date(ts):
    try:
        return time.strftime("%b %d, %Y %H:%M", time.localtime(float(ts)))
    except Exception:
        return "—"
def safe_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

def is_valid_workshop_id(v):
    s = str(v or "").strip()
    return s.isdigit() and 5 <= len(s) <= 12

def is_valid_port(v):
    try:
        p = int(v)
    except (TypeError, ValueError):
        return False
    return 1024 <= p <= 65535

def safe_filename(name):
    s = slugify(str(name or "build"))
    return s[:80] or "build"

def parse_launch_args(text):
    import shlex
    try:
        return shlex.split(str(text or ""))
    except ValueError:
        return str(text or "").split()

_KNOWN_LAUNCH_FLAGS = {"-useallavailablecores", "-sm4", "-d3d10", "-nomansky", "-lowmemory", "-high", "-windowed", "-fullscreen", "-resx", "-resy", "-log", "-nosteamclient", "-usecache", "-culture", "-language"}

def validate_launch_args(text):
    args = parse_launch_args(text)
    unknown = [a for a in args if a.startswith("-") and a.split("=")[0].lower() not in _KNOWN_LAUNCH_FLAGS and not a[1:].isdigit()]
    return args, unknown

def version_year(version):
    try:
        y, _m = parse_version_date(version.get("name", ""))
    except Exception:
        return 0
    return y if y != 9999 else 0

def version_sort_key(version, mode="date"):
    name = version.get("name", "")
    if mode == "name":
        return (name.lower(),)
    if mode == "dlc":
        return (-sum(1 for k in DLC_ORDER if version.get(k)), name.lower())
    if mode == "size":
        return (-_estimate_size_gb(version), name.lower())
    y, m = parse_version_date(name)
    return (y, m, name.lower())

def search_match(version, query, descriptions=None):
    q = (query or "").lower().strip()
    if not q:
        return True
    name = version.get("name", "")
    entry = (descriptions or {}).get(name, {}) if isinstance(descriptions, dict) else {}
    title = entry.get("title", "") if isinstance(entry, dict) else ""
    desc = entry.get("desc", "") if isinstance(entry, dict) else ""
    return q in name.lower() or q in title.lower() or q in desc.lower()

def count_dlcs(version):
    return sum(1 for k in DLC_ORDER if version.get(k))

def estimate_total_gb(versions):
    try:
        return sum(_estimate_size_gb(v) for v in versions)
    except Exception:
        return 0.0

def disk_free_gb(path):
    try:
        return shutil.disk_usage(str(path)).free / (1024 ** 3)
    except Exception:
        return -1.0

def fmt_minutes(seconds):  # 193: seconds -> "12m" / "1h 5m"
    try:
        s = int(seconds)
    except Exception:
        return "0m"
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m" if s < 3600 else f"{s // 3600}h {s % 3600 // 60}m"

def clamp_int(value, lo, hi):  # 194: int clamped to [lo, hi], never raises
    try:
        v = int(value)
    except Exception:
        return lo
    return max(lo, min(hi, v))

def count_builds_by_year(versions):  # 195: {year: count} for builds
    out = {}
    for v in versions or []:
        y = version_year(v)
        if y:
            out[y] = out.get(y, 0) + 1
    return out

def most_common_dlc_key(versions):  # 196: DLC key appearing on most builds
    counts = {}
    for v in versions or []:
        for k in DLC_ORDER:
            if v.get(k):
                counts[k] = counts.get(k, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""

def rank_builds_by_size(versions):  # 197: builds sorted by estimate, largest first
    return sorted(versions or [], key=lambda v: _estimate_size_gb(v), reverse=True)

def safe_str(value):  # 198: str() that never raises
    try:
        return str(value or "")
    except Exception:
        return ""

def is_valid_build_name(name):  # 199: non-empty, no path separators
    n = str(name or "").strip()
    return bool(n) and "/" not in n and "\\" not in n and len(n) <= 200

def write_csv_rows(path, header, rows):  # 200: write header+rows to CSV, return count
    import csv as _csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return len(rows)

def is_port_free(port):
    import socket
    if not is_valid_port(port):
        return False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", int(port))) != 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass

def diagnostics_lines(main):
    store = main.store
    versions = getattr(main.versions, "versions", []) or []
    steam = steam_dir_for(store)
    installed = []
    for v in versions:
        exe = game_exe_for(steam, v, store) if steam else None
        if exe and Path(exe).is_file():
            installed.append(v.get("name", ""))
    mods = load_mods()
    lines = [
        f"{APP_NAME} {VERSION}",
        f"Platform: {sys.platform}  Python: {sys.version.split()[0]}",
        f"Steam: {steam or 'not found'}  SteamCMD ready: {steamcmd_ready()}",
        f"Builds: {len(versions)} total, {len(installed)} installed",
        f"Installed: {', '.join(installed) if installed else 'none'}",
        f"Favorites: {len(store.get('favorites', []) or [])}  Profiles: {len(store.get('profiles', []) or [])}",
        f"Mods in catalog: {len(mods)}  Host servers: {len(store.get('hosted_servers', []) or [])}",
        f"Backups: {len(list(BACKUP_DIR.glob('*.zip'))) if BACKUP_DIR.is_dir() else 0}",
        f"Install root: {install_root_for(store, steam)}",
        f"Disk free (install): {disk_free_gb(install_root_for(store, steam)):.1f} GB",
    ]
    return lines

def _tool_result(fn):
    try:
        out = fn()
        return str(out) if out else "(no result)"
    except Exception as e:
        return f"Check failed: {e}"

class ToolsPage(QWidget):
    """Read-only diagnostics + safe actions. Nothing here deletes a
    build, a backup, or a setting — actions only open folders, export
    a text file, copy text, or clear an in-memory cache."""

    def __init__(self, main):
        super().__init__(); self.main = main; self.store = main.store
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(28, 24, 28, 28); v.setSpacing(12); v.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(page_header("Tools", "Diagnostics and safe actions — nothing here deletes anything."))
        hint = QLabel("Tip: click a check and its result appears in the box above. 'Run all checks' puts all results in the box, with a summary at the top. Use Filter below to find a check without scrolling."); hint.setObjectName("Muted"); hint.setWordWrap(True); v.addWidget(hint); self.hint_label = hint
        self.output = QPlainTextEdit(); self.output.setObjectName("Log"); self.output.setReadOnly(True); self.output.setMinimumHeight(180)
        v.addWidget(self.output)
        runrow = FlowLayout(); runrow.setSpacing(10)
        run_all = QPushButton("Run all checks"); run_all.setObjectName("Primary"); run_all.setMinimumHeight(40); run_all.clicked.connect(self._run_all); runrow.addWidget(run_all)
        clear_b = QPushButton("Clear results"); clear_b.clicked.connect(lambda: (self.output.clear(), self._clear_tool_labels())); runrow.addWidget(clear_b)
        runrow.addStretch(1); v.addLayout(runrow)
        # v1.32.0: filter, so you don't have to scroll through 60+ checks
        self.tool_search = QLineEdit(); self.tool_search.setPlaceholderText("Filter checks…  (try: disk, mods, backups, steam)")
        self.tool_search.setClearButtonEnabled(True); self.tool_search.textChanged.connect(self._filter_tools)
        v.addWidget(self.tool_search)
        self._tool_labels = {}
        self._tool_buttons = []  # (button, title_lower, category_header)
        self._buttons_box = QVBoxLayout(); self._buttons_box.setSpacing(8); v.addLayout(self._buttons_box)
        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)
        self._build_buttons()

    def _show(self, title, text):
        self.output.appendPlainText(f"— {title} —\n{text}\n")

    def _clear_tool_labels(self):
        for lbl in self._tool_labels.values():
            try:
                lbl.setText("")
            except Exception:
                pass

    def _run_tool(self, title, fn):
        result = _tool_result(fn)
        self._show(title, result)
        lbl = self._tool_labels.get(title)
        if lbl is not None:
            try:
                lbl.setText(result.replace("\n", " · ")[:300])
            except Exception:
                pass
        return result

    def _run_all(self):
        sections = []
        for _cat, title, fn in self._tool_defs():
            result = _tool_result(fn)
            sections.append(f"— {title} —\n{result}")
            lbl = self._tool_labels.get(title)
            if lbl is not None:
                try:
                    lbl.setText(result.replace("\n", " · ")[:300])
                except Exception:
                    pass
        summary = f"Ran {len(sections)} checks. Scroll down for each result, or click a single check to see its result next to its button."
        self.output.setPlainText(summary + "\n\n" + "\n\n".join(sections))
        try:
            self.output.verticalScrollBar().setValue(0)
        except Exception:
            pass

    def _open_folder(self, path):
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            _open_url(QUrl.fromLocalFile(str(path)).toString())
            return f"Opened: {path}"
        except Exception as e:
            return f"Could not open {path}: {e}"

    def _tool_defs(self):
        m = self.main; s = self.store
        versions = getattr(m.versions, "versions", []) or []
        steam = steam_dir_for(s)
        def _installed():
            out = []
            for v in versions:
                exe = game_exe_for(steam, v, s) if steam else None
                if exe and Path(exe).is_file():
                    out.append(v)
            return out
        def _export_diag():
            dest, _ok = QFileDialog.getSaveFileName(self, "Export diagnostics", "launcher-diagnostics.txt", "Text files (*.txt)")
            if not dest:
                return "Export cancelled."
            Path(dest).write_text("\n".join(diagnostics_lines(m)), encoding="utf-8")
            return f"Saved diagnostics to {dest}"
        def _copy_diag():
            _copy_text("\n".join(diagnostics_lines(m)))
            return "Diagnostics copied to clipboard."
        def _clear_cache():
            _SIZE_CACHE.clear()
            return "In-memory size cache cleared. Sizes will be re-measured on the next Versions refresh."
        def _refresh_all():
            try:
                m.refresh_all()
                return "All pages refreshed."
            except Exception as e:
                return f"Refresh failed: {e}"
        def _random_build():
            import random as _r
            pool = _installed() or versions
            if not pool:
                return "No builds found."
            v = _r.choice(pool)
            return f"Try this one: {v.get('name', '')} ({count_dlcs(v)} DLCs, ~{_estimate_size_gb(v):.0f} GB estimated)"
        def _missing_desc():
            descs = getattr(m.versions, "descriptions", {}) or {}
            missing = [v.get("name", "") for v in versions if v.get("name", "") not in descs]
            return f"{len(missing)} builds without a description.\n" + ("\n".join(missing[:20]) if missing else "All builds have descriptions.")
        def _dup_names():
            names = [v.get("name", "") for v in versions]
            dups = sorted({n for n in names if names.count(n) > 1})
            return f"{len(dups)} duplicate names.\n" + ("\n".join(dups) if dups else "No duplicates.")
        def _missing_art():
            keys = set()
            for v in versions:
                keys.add(era_art_key(v))
            missing = [k for k in sorted(keys) if art_pixmap(k, 150, 68) is None]
            return f"Art keys used: {', '.join(sorted(keys))}\nMissing art: {', '.join(missing) if missing else 'none'}"
        def _broken_exes():
            broken = []
            root = install_root_for(s, steam)
            if root and Path(root).is_dir():
                for d in Path(root).iterdir():
                    if d.is_dir() and not list(d.glob("**/ShooterGame/Binaries/Win64/*.exe")):
                        broken.append(d.name)
            return f"Folders without a game exe: {len(broken)}\n" + ("\n".join(broken[:20]) if broken else "All install folders have an exe.")
        def _launch_check():
            args, unknown = validate_launch_args(s.get("launch_args", ""))
            return f"Default launch args: {len(args)} tokens.\nUnknown flags: {', '.join(unknown) if unknown else 'none'}"
        def _workshop_check():
            mods = load_mods()
            bad = [x["name"] for x in mods if not is_valid_workshop_id(x["workshop_id"])]
            return f"{len(mods)} mods, {len(bad)} with an invalid Workshop ID.\n" + ("\n".join(bad) if bad else "All Workshop IDs look valid.")
        def _ports_check():
            hosted = s.get("hosted_servers", []) or []
            lines = []
            for h in hosted:
                for key in ("port", "query"):
                    p = h.get(key)
                    if p is not None:
                        lines.append(f"{h.get('name', '')} {key} {p}: {'free' if is_port_free(p) else 'in use / blocked'}")
            return "\n".join(lines) if lines else "No hosted servers to check."
        def _backups_total():
            files = list(BACKUP_DIR.glob("*.zip")) if BACKUP_DIR.is_dir() else []
            total = sum(f.stat().st_size for f in files if f.is_file())
            return f"{len(files)} backups, {fmt_bytes(total)} total."
        def _mods_installed():
            inst = _installed()
            if not inst:
                return "No builds installed, so no mods can be installed yet."
            target = inst[0]
            mdir = game_dir_for(s, target, steam) / "ShooterGame" / "Content" / "Mods" if steam else None
            if not mdir or not mdir.is_dir():
                return "No Mods folder yet for the first installed build."
            return f"Mods folder for {target.get('name', '')}: {len(list(mdir.iterdir()))} entries."
        def _date_range():
            years = sorted({version_year(v) for v in versions if version_year(v)})
            return f"Build years: {years[0] if years else '—'} – {years[-1] if years else '—'} ({len(years)} years)"
        def _download_headers():
            ok, failed = download_official_headers()
            # Cards cache pixmaps at build time — rebuild them so the
            # new headers show without a restart.
            try:
                m.versions._populate()
            except Exception:
                pass
            if not failed:
                return f"Downloaded all {ok} official ARK headers into art/. Cards now use ARK's own art, one per map/DLC."
            return (f"Downloaded {ok} of {len(OFFICIAL_HEADERS)} official headers. "
                    f"Failed: {', '.join(k for k, _ in failed)} — those cards keep their previous banner. Try again; Steam's CDN hiccups are usually one-off.")
        def _export_builds_csv():
            dest, _ok = QFileDialog.getSaveFileName(self, "Export builds", "builds.csv", "CSV files (*.csv)")
            if not dest:
                return "Export cancelled."
            rows = [[v.get("name", ""), version_year(v), count_dlcs(v), round(_estimate_size_gb(v), 1)] for v in versions]
            return f"Exported {write_csv_rows(dest, ['name', 'year', 'dlcs', 'estimate_gb'], rows)} builds to {dest}"
        def _export_mods_csv():
            dest, _ok = QFileDialog.getSaveFileName(self, "Export mods", "mods.csv", "CSV files (*.csv)")
            if not dest:
                return "Export cancelled."
            mods = load_mods()
            rows = [[x["name"], x["workshop_id"], x["min_build"], x["max_build"]] for x in mods]
            return f"Exported {write_csv_rows(dest, ['name', 'workshop_id', 'min_build', 'max_build'], rows)} mods to {dest}"
        def _art_stats():
            files = list(ART_DIR.glob("*.jpg")) if ART_DIR.is_dir() else []
            total = sum(f.stat().st_size for f in files if f.is_file())
            return f"{len(files)} art files, {fmt_bytes(total)} total."
        def _steamcmd_size():
            root = steamcmd_depot_root()
            if not Path(root).is_dir():
                return "SteamCMD depot folder not found yet."
            return f"SteamCMD depot folder: {dir_size_gb(str(root)):.2f} GB"
        def _error_log_size():
            f = _app_dir() / "launcher-error.log"
            return f"launcher-error.log: {fmt_bytes(f.stat().st_size) if f.is_file() else 'not created yet'}"
        return [
            ("Art", "Download official ARK headers", _download_headers),
            ("More checks", "Disk free (backups folder)", lambda: f"{disk_free_gb(BACKUP_DIR):.1f} GB free"),
            ("More checks", "Disk free (app folder)", lambda: f"{disk_free_gb(_app_dir()):.1f} GB free"),
            ("More checks", "Builds per era", lambda: ", ".join(f"{y}: {c}" for y, c in sorted(count_builds_by_year(versions).items())) or "No dated builds"),
            ("More checks", "Largest estimated build", lambda: f"{rank_builds_by_size(versions)[0].get('name', '')} ~{_estimate_size_gb(rank_builds_by_size(versions)[0]):.0f} GB" if versions else "No builds"),
            ("More checks", "Smallest estimated build", lambda: f"{rank_builds_by_size(versions)[-1].get('name', '')} ~{_estimate_size_gb(rank_builds_by_size(versions)[-1]):.0f} GB" if versions else "No builds"),
            ("More checks", "Average estimated build size", lambda: f"~{estimate_total_gb(versions) / len(versions):.1f} GB average" if versions else "No builds"),
            ("More checks", "Primitive+ builds count", lambda: f"{sum(1 for v in versions if v.get('primitive'))} builds include Primitive+"),
            ("More checks", "Builds with 5+ DLCs", lambda: f"{sum(1 for v in versions if count_dlcs(v) >= 5)} builds have 5 or more DLCs"),
            ("More checks", "Installed builds estimated total", lambda: f"~{sum(_estimate_size_gb(v) for v in _installed()):.0f} GB estimated for installed builds"),
            ("More checks", "Favorites estimated total", lambda: f"~{sum(_estimate_size_gb(v) for v in versions if v.get('name', '') in (s.get('favorites', []) or [])):.0f} GB estimated for favorites"),
            ("More checks", "Uninstalled builds count", lambda: f"{len(versions) - len(_installed())} builds not installed"),
            ("More checks", "Distinct DLC keys used", lambda: f"{len({k for v in versions for k in DLC_ORDER if v.get(k)})} distinct DLC keys used across all builds"),
            ("More checks", "Most common DLC", lambda: f"Most common DLC: {DLC_NAMES.get(most_common_dlc_key(versions), most_common_dlc_key(versions)) or 'none'}"),
            ("More checks", "Art files count and bytes", _art_stats),
            ("More checks", "Settings keys count", lambda: f"{len(s.settings)} settings keys stored"),
            ("More checks", "Profiles with custom launch args", lambda: f"{sum(1 for pr in (s.get('profiles', []) or []) if isinstance(pr, dict) and (pr.get('launch_args') or '').strip())} profiles have custom launch args"),
            ("More checks", "Hosted servers non-default port", lambda: f"{sum(1 for h in (s.get('hosted_servers', []) or []) if isinstance(h, dict) and h.get('port') not in (None, 7777))} hosted servers use a non-default port"),
            ("More checks", "Backup folder entries", lambda: f"{len(list(BACKUP_DIR.iterdir())) if BACKUP_DIR.is_dir() else 0} entries in the backups folder"),
            ("More checks", "SteamCMD depot folder size", _steamcmd_size),
            ("More checks", "Launcher error log size", _error_log_size),
            ("More checks", "Open art folder", lambda: self._open_folder(ART_DIR)),
            ("More checks", "Open SteamCMD folder", lambda: self._open_folder(steamcmd_depot_root().parent if steamcmd_depot_root() else _app_dir())),
            ("More checks", "Copy all build names", lambda: (_copy_text("\n".join(v.get('name', '') for v in versions)), f"Copied {len(versions)} build names.")[1]),
            ("More checks", "Export builds to CSV", _export_builds_csv),
            ("More checks", "Export mods to CSV", _export_mods_csv),
            ("More checks", "Copy favorites to clipboard", lambda: (_copy_text("\n".join(s.get('favorites', []) or [])), f"Copied {len(s.get('favorites', []) or [])} favorites.")[1]),
            ("More checks", "Builds with empty base manifest", lambda: f"{sum(1 for v in versions if not (v.get('base') or '').strip())} builds have an empty base manifest"),
            ("More checks", "Python version check", lambda: f"Python {sys.version.split()[0]} — {'OK (3.10+)' if sys.version_info >= (3, 10) else 'older than 3.10, upgrade recommended'}"),
            ("More checks", "Free space vs largest build", lambda: (f"Free {disk_free_gb(install_root_for(s, steam)):.1f} GB vs largest ~{_estimate_size_gb(rank_builds_by_size(versions)[0]):.0f} GB — {'enough' if versions and disk_free_gb(install_root_for(s, steam)) >= _estimate_size_gb(rank_builds_by_size(versions)[0]) else 'not enough'}") if versions else "No builds"),
            ("More checks", "Count of Tools checks", lambda: f"{len(self._tool_defs())} Tools checks available (including this one)"),
            ("Disk & Steam", "Disk free (install)", lambda: f"{disk_free_gb(install_root_for(s, steam)):.1f} GB free"),
            ("Disk & Steam", "Disk free (download)", lambda: f"{disk_free_gb(steamcmd_depot_root()):.1f} GB free"),
            ("Disk & Steam", "Steam path", lambda: str(steam or "not found")),
            ("Disk & Steam", "SteamCMD status", lambda: "Ready" if steamcmd_ready() else "Not set up yet — Settings → Steam → Set up SteamCMD"),
            ("Builds & Mods", "Builds installed", lambda: f"{len(_installed())} of {len(versions)} builds installed"),
            ("Builds & Mods", "Favorites", lambda: f"{len(s.get('favorites', []) or [])} favorites"),
            ("Builds & Mods", "DLC total", lambda: f"{sum(count_dlcs(v) for v in versions)} DLC entries across all builds"),
            ("Builds & Mods", "Estimated total size", lambda: f"~{estimate_total_gb(versions):.0f} GB for every build (estimates only)"),
            ("Builds & Mods", "Mods installed", _mods_installed),
            ("Builds & Mods", "Random build suggestion", _random_build),
            ("Files & Settings", "Backups total", _backups_total),
            ("Files & Settings", "Host servers", lambda: f"{len(s.get('hosted_servers', []) or [])} hosted servers saved"),
            ("Files & Settings", "Profiles", lambda: f"{len(s.get('profiles', []) or [])} player profiles"),
            ("Files & Settings", "Settings file", lambda: f"{SETTINGS_FILE} ({fmt_bytes(SETTINGS_FILE.stat().st_size) if SETTINGS_FILE.is_file() else 'not created yet'})"),
            ("Files & Settings", "Build date range", _date_range),
            ("Files & Settings", "Open install folder", lambda: self._open_folder(install_root_for(s, steam))),
            ("Files & Settings", "Open backups folder", lambda: self._open_folder(BACKUP_DIR)),
            ("Files & Settings", "Open settings folder", lambda: self._open_folder(DATA_DIR)),
            ("Checks", "Missing descriptions", _missing_desc),
            ("Checks", "Duplicate names", _dup_names),
            ("Checks", "Missing art", _missing_art),
            ("Checks", "Broken install folders", _broken_exes),
            ("Checks", "Launch args check", _launch_check),
            ("Checks", "Workshop IDs check", _workshop_check),
            ("Checks", "Host ports check", _ports_check),
            ("Actions", "Export diagnostics", _export_diag),
            ("Actions", "Copy diagnostics", _copy_diag),
            ("Actions", "Clear size cache", _clear_cache),
            ("Actions", "Refresh all pages", _refresh_all),
            ("Actions", "System info", lambda: f"Platform {sys.platform}, Python {sys.version.split()[0]}, app dir {_app_dir()}"),
        ]

    def _build_buttons(self):
        # v1.32.0: grid, not one-check-per-row. 60+ checks in one long
        # vertical list meant scrolling forever (his screenshot). 3
        # columns cuts the height by about two-thirds. Results go to
        # the output box above, not to a label next to each button —
        # _run_tool already handles a missing label gracefully.
        cur_cat = None; grid = None; col = 0
        for cat, title, fn in self._tool_defs():
            if cat != cur_cat:
                cur_cat = cat
                hdr = QLabel(cat); hdr.setObjectName("SectionHeader"); self._buttons_box.addWidget(hdr)
                grid = FlowLayout(); grid.setSpacing(10); grid.setContentsMargins(0, 0, 0, 0)
                self._buttons_box.addLayout(grid); col = 0
                self._cur_tool_hdr = hdr
            b = QPushButton(title); b.setMinimumWidth(180); b.clicked.connect(lambda _c=False, t=title, f=fn: self._run_tool(t, f))
            grid.addWidget(b); col += 1
            self._tool_buttons.append((b, title.lower(), self._cur_tool_hdr))

    def _filter_tools(self, text):
        # Show only checks matching the filter; hide empty categories.
        q = (text or "").strip().lower()
        seen_hdr = {}
        for b, low, hdr in self._tool_buttons:
            show = (not q) or (q in low)
            b.setVisible(show)
            if show:
                seen_hdr[id(hdr)] = True
        # Headers: visible if any of their buttons is visible (or no filter)
        for _b, _low, hdr in self._tool_buttons:
            try:
                hdr.setVisible((not q) or (id(hdr) in seen_hdr))
            except Exception:
                pass

    def refresh(self):
        try:
            self.hint_label.setVisible(bool(self.store.get("show_tool_hints", True)))
        except Exception:
            pass


class DetailsPanel(QFrame):
    """v1.41.0 persistent right details panel, like his rightSidePanel:
    it does NOT scroll with the center column. Top to bottom: a spaced
    caps label, a preview box, a title + value pill, a description,
    key/value facts, and a left-accent note. It is NOT a second
    settings list — it summarises the current page / selected build.
    Versions hides this panel because Versions already has its own
    grid + details split (that IS its right panel)."""
    def __init__(self, main):
        super().__init__(); self.main = main; self.setObjectName("DetailsPanel"); self.setMinimumWidth(240); self.setMaximumWidth(320)
        v = QVBoxLayout(self); v.setContentsMargins(20, 20, 20, 20); v.setSpacing(12); v.setAlignment(Qt.AlignmentFlag.AlignTop)
        caps = QLabel("SETTING DETAILS"); caps.setObjectName("Muted")
        try:
            _f = caps.font(); _f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5); _f.setBold(True); caps.setFont(_f)
        except Exception: pass
        v.addWidget(caps)
        self.preview = QFrame(); self.preview.setObjectName("DetailsCard"); self.preview.setFixedHeight(150)
        _pv = QVBoxLayout(self.preview); _pv.setContentsMargins(0, 0, 0, 0)
        self.preview_label = FullBleedBanner(None, height=150, fit=False, round_all=True); _pv.addWidget(self.preview_label)
        v.addWidget(self.preview)
        self.title_label = QLabel("Legacy ARK Launcher"); self.title_label.setObjectName("CardHead"); self.title_label.setWordWrap(True); v.addWidget(self.title_label)
        self.value_pill = QLabel(""); self.value_pill.setObjectName("VersionPill"); self.value_pill.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(self.value_pill, 0, Qt.AlignmentFlag.AlignLeft)
        self.desc_label = QLabel(""); self.desc_label.setObjectName("Muted"); self.desc_label.setWordWrap(True); v.addWidget(self.desc_label)
        self.facts_box = QVBoxLayout(); self.facts_box.setSpacing(6); v.addLayout(self.facts_box)
        self.note = QLabel(""); self.note.setObjectName("Muted"); self.note.setWordWrap(True)
        try: self.note.setStyleSheet("border-left: 3px solid #3579b1; padding-left: 12px;")
        except Exception: pass
        v.addWidget(self.note)
        v.addStretch(1)
        self.status_label = QLabel("Ready"); self.status_label.setObjectName("Muted"); self.status_label.setWordWrap(True); v.addWidget(self.status_label)
        self.update_panel(0)

    def _set_facts(self, pairs):
        while self.facts_box.count():
            _it = self.facts_box.takeAt(0); _w = _it.widget()
            if _w is not None: _w.deleteLater()
        for k, val in pairs:
            row = QWidget(); h = FlowLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
            kl = QLabel(k); kl.setObjectName("Muted"); h.addWidget(kl)
            h.addStretch(1)
            vl = QLabel(str(val)); vl.setObjectName("RowTitle"); h.addWidget(vl)
            self.facts_box.addWidget(row)

    def update_panel(self, idx):
        try:
            store = self.main.store
            titles = ["Dashboard", "Versions", "Mods", "Game Options", "Servers", "Host", "Backups", "Help", "Settings", "Tools"]
            title = titles[idx] if 0 <= idx < len(titles) else "Legacy ARK Launcher"
            profile = store.get("active_profile", "Default") or "Default"
            versions = getattr(self.main.versions, "versions", []) or []
            steam = None
            try: steam = steam_dir_for(store)
            except Exception: pass
            installed = 0
            if steam:
                for _v in versions:
                    try:
                        _exe = game_exe_for(steam, _v, store)
                        if _exe and Path(_exe).is_file(): installed += 1
                    except Exception: pass
            favs = store.get("favorites", []) or []
            mods = getattr(self.main.mods, "mods", []) or []
            descs = {
                "Dashboard": ("Old ARK is back — 97 builds, 2015 to 2024. Pick a build on Versions, download once, hit Play.", [("Installed builds", installed), ("Favorites", len(favs) if isinstance(favs, list) else 0), ("Profiles", len(store.get("profiles", []) or []))]),
                "Versions": ("All old ARK builds, 2015 to 2024, with search and filters. The details on the right of this page are its own right panel.", [("Builds", len(versions)), ("Installed", installed)]),
                "Mods": ("Workshop mods, filtered to the selected build. Only mods that actually existed for that build show as compatible.", [("Mods listed", len(mods)), ("Installed builds", installed)]),
                "Host": ("Turn an installed build into a dedicated server for friends.", [("Installed builds", installed)]),
                "Backups": ("Back up and restore the Saved folder for an installed build.", [("Installed builds", installed)]),
                "Help": ("How to play, download, host, and fix common problems.", [("Builds", len(versions))]),
                "Settings": ("Profiles, theme, background, and launcher options.", [("Profile", profile), ("Theme", store.get("theme", ""))]),
                "Tools": ("Checks, diagnostics, and maintenance for the launcher and its builds.", [("Builds", len(versions)), ("Installed", installed)]),
                "Servers": ("Servers you added yourself — queried live, joined through Steam.", [("Servers saved", len(store.get("servers", []) or []))]),
                "Game Options": ("Default launch arguments for ARK.", [("Profile", profile)]),
            }
            desc, facts = descs.get(title, ("Legacy ARK Launcher.", []))
            # Selected build, if Versions has one, beats the page summary.
            sel = getattr(self.main.versions, "selected", None)
            if sel and isinstance(sel, dict) and sel.get("name"):
                title = sel.get("name", title)
                desc = f"Selected build on Versions. {desc}"
                facts = [("DLCs", count_dlcs(sel) if 'count_dlcs' in globals() else "?")] + facts
            self.title_label.setText(title)
            self.value_pill.setText(f"Profile: {profile}")
            self.desc_label.setText(desc)
            self._set_facts(facts)
            self.note.setText("Tip: the center column is rows, not cards — title, description, then the control, separated by a hairline, like his.")
            # Preview: The Island header if shipped, else the dino photo.
            _art = None
            try:
                _c = ART_DIR / "base.jpg"
                if _c.is_file(): _art = _c
                else:
                    _d = ART_DIR / "ark-background.png"
                    if _d.is_file(): _art = _d
            except Exception: pass
            if _art is not None:
                _pm = QPixmap(str(_art))
                if not _pm.isNull():
                    self.preview_label.setPixmapFull(_pm)
        except Exception:
            pass

# ------------------------------------------------------------------ Servers (v1.65.0)
# User-added ARK servers, queried live with Valve's public A2S_INFO
# protocol (the same protocol Steam's own server browser uses). No
# sponsored or community servers are listed — only servers the user adds.
# Joining opens steam://connect in Steam, so it requires owning ARK.
# Deliberately NOT ported from TEKLauncher: ownership bypass, TEK Steam
# Client downloads of unowned content, skin unlocks.

_ARK_MAP_NAMES = {
    "TheIsland": "The Island", "TheCenter": "The Center",
    "ScorchedEarth": "Scorched Earth", "Ragnarok": "Ragnarok",
    "Aberration": "Aberration", "Extinction": "Extinction",
    "Valguero_P": "Valguero", "Genesis": "Genesis Part 1",
    "Gen2": "Genesis Part 2", "CrystalIsles": "Crystal Isles",
    "LostIsland": "Lost Island", "Fjordur": "Fjordur",
}

def _read_cstr(buf, pos):
    end = buf.find(b"\x00", pos)
    if end < 0:
        return "", len(buf)
    return buf[pos:end].decode("utf-8", "replace"), end + 1

def _a2s_parse_info(buf):
    """Parse a single (reassembled) A2S_INFO response. Returns a dict or None."""
    try:
        if len(buf) < 6 or buf[:4] != b"\xff\xff\xff\xff" or buf[4] != 0x49:
            return None
        pos = 5
        pos += 1  # protocol version
        name, pos = _read_cstr(buf, pos)
        map_raw, pos = _read_cstr(buf, pos)
        _folder, pos = _read_cstr(buf, pos)
        _game, pos = _read_cstr(buf, pos)
        pos += 2  # app id
        if pos + 7 > len(buf):
            return None
        players, maxplayers = buf[pos], buf[pos + 1]
        pos += 7  # players, max, bots, type, env, visibility, vac
        version, pos = _read_cstr(buf, pos)
        if " - (v" in name:
            base, ver = name.rsplit(" - (v", 1)
            version = ver.rstrip(")")
            name = base
        return {"name": name, "map": map_raw,
                "map_display": _ARK_MAP_NAMES.get(map_raw, map_raw),
                "players": players, "maxplayers": maxplayers,
                "version": version}
    except Exception:
        return None

def _a2s_query(host, query_port, timeout=2.0):
    """One A2S_INFO query. Returns the info dict, or None if the server
    did not answer, refused, or sent something unparseable."""
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return None
    req = b"\xff\xff\xff\xff\x54Source Engine Query\x00"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(req, (ip, int(query_port)))
            try:
                data, _addr = sock.recvfrom(4096)
            except OSError:
                return None
            if len(data) == 9 and data[:4] == b"\xff\xff\xff\xff" and data[4] == 0x41:
                # Challenge: resend with the challenge bytes appended.
                sock.sendto(req + data[5:9], (ip, int(query_port)))
                try:
                    data, _addr = sock.recvfrom(4096)
                except OSError:
                    return None
            if len(data) >= 4 and data[:4] == b"\xff\xff\xff\xfe":
                # Split packet: reassemble parts (classic format, with a
                # size-field variant handled by length check).
                parts = {}
                total = None
                buf = data
                while buf is not None:
                    if len(buf) < 9 or buf[:4] != b"\xff\xff\xff\xfe":
                        break
                    total = buf[8]
                    num = buf[9]
                    rest = buf[10:]
                    if len(rest) >= 2:
                        sz = struct.unpack_from("<H", rest, 0)[0]
                        if sz == len(rest) - 2:
                            rest = rest[2:]
                    parts[num] = rest
                    if total is not None and len(parts) >= total:
                        break
                    try:
                        buf, _addr = sock.recvfrom(4096)
                    except OSError:
                        break
                if total is None or len(parts) < total:
                    return None
                data = b"".join(parts[i] for i in sorted(parts))
            return _a2s_parse_info(data)
        finally:
            sock.close()
    except OSError:
        return None

def _lan_scan(timeout=2.5):
    """Broadcast A2S_INFO on the LAN query port and collect replies.
    Returns a list of {ip, query_port, info} (info may be None)."""
    found = {}
    req = b"\xff\xff\xff\xff\x54Source Engine Query\x00"
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.5)
        try:
            sock.sendto(req, ("255.255.255.255", 27015))
        except OSError:
            return []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
            except OSError:
                continue
            if len(data) > 5 and data[:4] == b"\xff\xff\xff\xff" and data[4] == 0x49:
                found[(addr[0], addr[1])] = _a2s_parse_info(data)
    except OSError:
        pass
    finally:
        try:
            if sock is not None:
                sock.close()
        except Exception:
            pass
    return [{"ip": ip, "query_port": port, "info": info} for (ip, port), info in sorted(found.items())]

def _a2s_parse_rules(buf):
    """Parse a single (reassembled) A2S_RULES response into {name: value}."""
    try:
        if len(buf) < 7 or buf[:4] != b"\xff\xff\xff\xff" or buf[4] != 0x45:
            return None
        count = struct.unpack_from("<h", buf, 5)[0]
        out = {}
        pos = 7
        for _ in range(max(0, count)):
            name, pos = _read_cstr(buf, pos)
            if pos >= len(buf):
                break
            value, pos = _read_cstr(buf, pos)
            if name:
                out[name] = value
        return out
    except Exception:
        return None

def _a2s_query_rules(host, query_port, timeout=2.0):
    """A2S_RULES query: returns {rule: value} or None. Same challenge +
    split-packet handling as _a2s_query. Callers interpret only vanilla,
    documented ARK rules (ClusterId_s, NUMOPENPUBCONN, SESSIONISPVE_i);
    TEK's TEKWrapper gate and BattlEye gate are NOT copied — vanilla
    servers must list."""
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return None
    req = b"\xff\xff\xff\xff\x56\xff\xff\xff\xff"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(req, (ip, int(query_port)))
            try:
                data, _addr = sock.recvfrom(4096)
            except OSError:
                return None
            if len(data) == 9 and data[:4] == b"\xff\xff\xff\xff" and data[4] == 0x41:
                sock.sendto(b"\xff\xff\xff\xff\x56" + data[5:9], (ip, int(query_port)))
                try:
                    data, _addr = sock.recvfrom(4096)
                except OSError:
                    return None
            if len(data) >= 4 and data[:4] == b"\xff\xff\xff\xfe":
                parts = {}
                total = None
                buf = data
                while buf is not None:
                    if len(buf) < 9 or buf[:4] != b"\xff\xff\xff\xfe":
                        break
                    total = buf[8]
                    num = buf[9]
                    rest = buf[10:]
                    if len(rest) >= 2:
                        sz = struct.unpack_from("<H", rest, 0)[0]
                        if sz == len(rest) - 2:
                            rest = rest[2:]
                    parts[num] = rest
                    if total is not None and len(parts) >= total:
                        break
                    try:
                        buf, _addr = sock.recvfrom(4096)
                    except OSError:
                        break
                if total is None or len(parts) < total:
                    return None
                data = b"".join(parts[i] for i in sorted(parts))
            return _a2s_parse_rules(data)
        finally:
            sock.close()
    except OSError:
        return None

def _parse_workshop_browse(html_text):
    """Parse Steam Workshop browse HTML into [(workshop_id, title)].
    Pairs each filedetails link with the next workshopItemTitle after
    it (the preview link precedes the title in each item card). Best
    effort: returns [] when the markup doesn't match, and callers fall
    back to opening the search in the browser."""
    out = []
    try:
        for m in re.finditer(r"sharedfiles/filedetails/\?id=(\d+)", html_text or ""):
            tm = re.search(r"workshopItemTitle[^>]*>([^<]+)<", html_text[m.end():])
            if tm:
                title = html.unescape(tm.group(1)).strip()
                if title:
                    out.append((m.group(1), title))
        seen = set(); ded = []
        for wid, title in out:
            if wid not in seen:
                seen.add(wid); ded.append((wid, title))
        return ded[:30]
    except Exception:
        return []

def _bloom_ini_text():
    """Scalability.ini content from TEK's FixBloom (verified in source):
    bloom quality 1 at every post-process quality level."""
    parts = []
    for i in range(4):
        parts.append(f"[PostProcessQuality@{i}]\r\nr.BloomQuality=1")
    return "\r\n".join(parts) + "\r\n"

def _mod_updates_available(local_mtimes, details):
    """Compare local install mtimes {wid: epoch} against Steam
    GetPublishedFileDetails entries. Returns [(wid, title, steam_time,
    local_time)] where Steam's version is newer than the local install
    (1h margin for clock skew and copy time). Heuristic, not proof —
    the label says 'may have an update' for exactly this reason."""
    out = []
    try:
        for d in details or []:
            wid = str(d.get("publishedfileid", d.get("id", "")) or "")
            try: steam_t = int(d.get("time_updated", 0) or 0)
            except (TypeError, ValueError): continue
            local_t = local_mtimes.get(wid)
            if wid and steam_t and local_t is not None and steam_t > local_t + 3600:
                out.append((wid, d.get("title", "") or wid, steam_t, local_t))
    except Exception:
        pass
    return out

class _ModUpdatesThread(QThread):
    """Bulk-fetch Steam details for installed mod IDs and compare
    timestamps. Emits (updates, error). No auth, no Steam client."""
    done = pyqtSignal(list, str)

    def __init__(self, items):
        super().__init__(); self.items = list(items)  # [(wid, mtime)]

    def run(self):
        try:
            fields = {"itemcount": len(self.items), "format": "json"}
            for i, (wid, _mt) in enumerate(self.items):
                fields[f"publishedfileids[{i}]"] = wid
            data = urllib.parse.urlencode(fields).encode()
            req = urllib.request.Request("https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                                         data=data, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            details = (payload.get("response", {}) or {}).get("publishedfiledetails", []) or []
            details = [d for d in details if str(d.get("result", "")) == "1"]
            local = {wid: mt for wid, mt in self.items}
            self.done.emit(_mod_updates_available(local, details), "")
        except Exception as e:
            self.done.emit([], f"Mod update check failed: {e}")

class _WorkshopSearchThread(QThread):
    """Fetch one page of Steam's public Workshop browse listing and
    parse it. Emits (results, error). No auth, no Steam client."""
    done = pyqtSignal(list, str)

    def __init__(self, query, page):
        super().__init__(); self.query = query; self.page = page

    def run(self):
        try:
            url = ("https://steamcommunity.com/workshop/browse/?appid=346110"
                   "&searchtext=" + urllib.parse.quote(self.query) +
                   f"&p={self.page}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html_text = resp.read().decode("utf-8", "replace")
            self.done.emit(_parse_workshop_browse(html_text), "")
        except Exception as e:
            self.done.emit([], f"Workshop search failed: {e}")

class _ModCheckThread(QThread):
    """Look up one Workshop ID via Steam's public GetPublishedFileDetails
    endpoint (no API key needed for public items). Emits a dict."""
    done = pyqtSignal(dict)

    def __init__(self, wid):
        super().__init__(); self.wid = str(wid)

    def run(self):
        out = {"wid": self.wid, "found": False, "title": "", "app_id": None, "error": "", "preview": None}
        try:
            data = urllib.parse.urlencode({"itemcount": 1, "publishedfileids[0]": self.wid, "format": "json"}).encode()
            req = urllib.request.Request("https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                                         data=data, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            details = (payload.get("response", {}) or {}).get("publishedfiledetails", [{}])[0] or {}
            if str(details.get("result", "")) == "1":
                out["found"] = True
                out["title"] = details.get("title", "") or ""
                app = details.get("consumer_app_id") or details.get("creator_app_id")
                try: out["app_id"] = int(app) if app is not None else None
                except (TypeError, ValueError): out["app_id"] = None
                # v1.67.0: preview image for TEK's ModInstaller preview pane.
                preview_url = details.get("preview_url", "") or ""
                if preview_url:
                    try:
                        preq = urllib.request.Request(preview_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(preq, timeout=10) as presp:
                            out["preview"] = presp.read()
                    except Exception:
                        out["preview"] = None
        except Exception:
            out["error"] = "fetch failed"
        self.done.emit(out)

class _ServerQueryThread(QThread):
    """Query saved servers off the GUI thread: A2S_INFO + A2S_RULES.
    Emits {index: (info-dict-or-None, rules-dict-or-None)}."""
    done = pyqtSignal(dict)

    def __init__(self, servers):
        super().__init__(); self.servers = list(servers)

    def run(self):
        out = {}
        try:
            for i, srv in enumerate(self.servers):
                try:
                    _t0 = time.perf_counter()
                    info = _a2s_query(srv.get("ip", ""), int(srv.get("query_port", 27015)))
                    if info is not None:
                        # v1.72.0: ping for the card (round-trip of the
                        # INFO query itself - no extra traffic).
                        info["ping_ms"] = (time.perf_counter() - _t0) * 1000.0
                    rules = _a2s_query_rules(srv.get("ip", ""), int(srv.get("query_port", 27015))) if info else None
                    out[i] = (info, rules)
                except Exception:
                    out[i] = (None, None)
        except Exception:
            pass
        self.done.emit(out)

class _ServerPlayersThread(QThread):
    """v1.72.0: A2S_PLAYER via tek_lib (the TEK port's query_server) -
    who's on one server right now. Emits a tek_lib.ServerStatus, or
    None when tek_lib is missing or the query blew up."""
    done = pyqtSignal(object)

    def __init__(self, srv):
        super().__init__(); self.srv = srv

    def run(self):
        try:
            if tek_lib is None:
                self.done.emit(None); return
            status = tek_lib.query_server(self.srv.get("ip", ""),
                                          int(self.srv.get("query_port", 27015)),
                                          timeout=3.0, with_players=True)
            self.done.emit(status)
        except Exception:
            self.done.emit(None)

class _TekCmCheckThread(QThread):
    """v1.72.0: Workshop ID lookup through TEK's CM client
    (tek_steamclient): anonymous CM sign-in - no Web API, and no
    credentials anywhere (the bindings declare no password API).
    First use downloads libtek-steamclient-2.dll from TEK's official
    mirrors into TEK_DLL_DIR. Emits the _ModCheckThread dict shape
    plus a 'via' marker."""
    done = pyqtSignal(dict)

    def __init__(self, wid):
        super().__init__(); self.wid = str(wid)

    def run(self):
        out = {"wid": self.wid, "found": False, "title": "", "app_id": None,
               "error": "", "preview": None, "via": "TEK CM"}
        try:
            if tek_steamclient is None:
                out["error"] = "tek_steamclient module missing"
                self.done.emit(out); return
            details = tek_steamclient.workshop_details(
                [int(self.wid)], TEK_DLL_DIR, timeout_ms=15000)
            if not details:
                out["error"] = "TEK CM returned nothing (connect/sign-in failed)"
                self.done.emit(out); return
            d = details[0]
            if d.status == 1 or d.name:
                out["found"] = True
                out["title"] = d.name or ""
                out["app_id"] = int(d.app_id) if d.app_id else None
                if d.preview_url:
                    try:
                        preq = urllib.request.Request(d.preview_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(preq, timeout=10) as presp:
                            out["preview"] = presp.read()
                    except Exception:
                        out["preview"] = None
            else:
                out["error"] = "not found via TEK CM"
        except Exception as e:
            out["error"] = str(e) or "TEK CM check failed"
        self.done.emit(out)

class _LanScanThread(QThread):
    done = pyqtSignal(list)

    def run(self):
        try:
            self.done.emit(_lan_scan())
        except Exception:
            self.done.emit([])

class ServersPage(QWidget):
    """User-added ARK servers: live A2S queries, join through Steam.
    No sponsored or community servers are listed here — only servers
    the user adds (v1.21.8 removed the sponsored Servers tab, and this
    page does not bring it back)."""

    def __init__(self, main):
        super().__init__(); self.main = main
        self._results = {}
        self._rules = {}
        self._thread = None
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner)
        v.setContentsMargins(28, 24, 28, 28); v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        v.addWidget(page_header("Servers",
            "Servers you added yourself — queried live (map, players, PvE/PvP, auto-cluster), "
            "joined through Steam or directly with one of your builds. "
            "No sponsored or community servers are listed here."))
        row = FlowLayout(); row.setSpacing(10)
        add_b = QPushButton("Add server"); add_b.setObjectName("Primary"); add_b.setMinimumHeight(40); add_b.clicked.connect(self._on_add); row.addWidget(add_b)
        self.refresh_b = QPushButton("Refresh all"); self.refresh_b.clicked.connect(self._on_refresh_all); row.addWidget(self.refresh_b)
        scan_b = QPushButton("Scan LAN"); scan_b.clicked.connect(self._on_scan_lan); row.addWidget(scan_b)
        row.addStretch(1); v.addLayout(row)
        self.status_label = QLabel(""); self.status_label.setObjectName("Muted"); self.status_label.setWordWrap(True)
        v.addWidget(self.status_label)
        self.list_box = QVBoxLayout(); self.list_box.setSpacing(10)
        v.addLayout(self.list_box)
        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)

    def _servers(self):
        try:
            lst = self.main.store.get("servers", []) or []
            return list(lst) if isinstance(lst, list) else []
        except Exception:
            return []

    def _save(self, servers):
        try: self.main.store.set("servers", servers)
        except Exception: pass

    def refresh(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            w = item.widget()
            if w is not None: w.deleteLater()
        servers = self._servers()
        if not servers:
            hint = QLabel("No servers yet — hit Add server. A server needs its IP (or hostname), "
                          "game port (usually 7777), and query port (usually 27015). "
                          "Join opens the server in Steam — you must own ARK on Steam.")
            hint.setObjectName("Muted"); hint.setWordWrap(True); self.list_box.addWidget(hint)
            return
        groups = {}
        for i, srv in enumerate(servers):
            # Grouping: manual cluster wins, else the server's own
            # ClusterId_s rule (vanilla ARK cluster servers publish one),
            # else Ungrouped. Favorites always sort first.
            if srv.get("favorite"):
                key = "★ Favorites"
            elif srv.get("cluster"):
                key = srv.get("cluster")
            else:
                cid = (self._rules.get(i) or {}).get("ClusterId_s", "")
                key = cid if cid else "Ungrouped"
            groups.setdefault(key, []).append(i)
        order = []
        if "★ Favorites" in groups: order.append("★ Favorites")
        order += sorted(k for k in groups if k not in ("★ Favorites", "Ungrouped"))
        if "Ungrouped" in groups: order.append("Ungrouped")
        for gname in order:
            h = QLabel(gname); h.setObjectName("SectionHeader"); self.list_box.addWidget(h)
            for i in groups[gname]:
                self.list_box.addWidget(self._card(i, servers[i]))
        # First open with saved servers and no results yet: query in background.
        if not self._results and (self._thread is None or not self._thread.isRunning()):
            self._on_refresh_all()

    def _card(self, i, srv):
        card = QFrame(); card.setObjectName("Card")
        v = QVBoxLayout(card); v.setContentsMargins(16, 12, 16, 12); v.setSpacing(6)
        res = self._results.get(i, "pending")
        rules = self._rules.get(i) or {}
        name = (srv.get("name") or "").strip()
        addr = f"{srv.get('ip', '')}:{srv.get('game_port', 7777)}"
        if res == "pending":
            title = name or addr; info = f"{addr} • Not queried yet"
        elif res is None:
            title = name or addr; info = f"{addr} • No reply (offline or unreachable)"
        else:
            title = res.get("name") or name or addr
            players = res.get("players", 0); maxplayers = res.get("maxplayers", 0)
            # NUMOPENPUBCONN is the true open-slots count; ARK's INFO
            # player field is often wrong, so prefer it when present.
            try:
                open_slots = int(rules.get("NUMOPENPUBCONN", ""))
                players = max(0, maxplayers - open_slots)
            except (TypeError, ValueError):
                pass
            info = f"{res.get('map_display', '')} • {players}/{maxplayers} players"
            if rules.get("SESSIONISPVE_i") == "1": info += " • PvE"
            elif rules.get("SESSIONISPVE_i") == "0": info += " • PvP"
            if res.get("version"): info += f" • {res['version']}"
            if res.get("ping_ms") is not None: info += f" • {res['ping_ms']:.0f} ms"
            info += f" • {addr}"
        t = QLabel(title); t.setObjectName("RowTitle"); v.addWidget(t)
        s = QLabel(info); s.setObjectName("Muted"); s.setWordWrap(True); v.addWidget(s)
        # v1.67.0: manual version of TEK's cluster info (hoster/Discord/
        # description) — a note and Discord link the user typed when
        # adding the server.
        if (srv.get("note") or "").strip():
            n = QLabel(srv.get("note").strip()); n.setObjectName("Muted"); n.setWordWrap(True); v.addWidget(n)
        brow = FlowLayout(); brow.setSpacing(10)
        join_b = QPushButton("Join"); join_b.setObjectName("Primary"); join_b.clicked.connect(lambda _c=False, _s=srv: self._on_join(_s)); brow.addWidget(join_b)
        jwb_b = QPushButton("Join with build"); jwb_b.clicked.connect(lambda _c=False, _s=srv: self._on_join_with_build(_s)); brow.addWidget(jwb_b)
        if (srv.get("discord") or "").strip():
            dc_b = QPushButton("Discord"); dc_b.clicked.connect(lambda _c=False, _u=srv.get("discord").strip(): _open_url(_u)); brow.addWidget(dc_b)
        ref_b = QPushButton("Refresh"); ref_b.clicked.connect(lambda _c=False, _i=i: self._on_refresh_one(_i)); brow.addWidget(ref_b)
        pl_b = QPushButton("Players"); pl_b.setToolTip("List who's on this server right now (A2S_PLAYER)")
        pl_b.clicked.connect(lambda _c=False, _s=srv: self._on_players(_s)); brow.addWidget(pl_b)
        cp_b = QPushButton("Copy address"); cp_b.clicked.connect(lambda _c=False, _s=srv: self._on_copy(_s)); brow.addWidget(cp_b)
        fav_b = QPushButton("★ Unfavorite" if srv.get("favorite") else "☆ Favorite"); fav_b.clicked.connect(lambda _c=False, _i=i: self._on_favorite(_i)); brow.addWidget(fav_b)
        rm_b = QPushButton("Remove"); rm_b.clicked.connect(lambda _c=False, _i=i: self._on_remove(_i)); brow.addWidget(rm_b)
        brow.addStretch(1); v.addLayout(brow)
        return card

    def _on_add(self):
        dlg = QDialog(self); dlg.setWindowTitle("Add server")
        form = QFormLayout(dlg)
        name_e = QLineEdit(); name_e.setPlaceholderText("Optional — filled from the query")
        ip_e = QLineEdit(); ip_e.setPlaceholderText("IP or hostname, e.g. 192.168.1.10")
        game_e = QSpinBox(); game_e.setRange(1, 65535); game_e.setValue(7777)
        query_e = QSpinBox(); query_e.setRange(1, 65535); query_e.setValue(27015)
        cluster_e = QLineEdit(); cluster_e.setPlaceholderText("Optional group name")
        note_e = QLineEdit(); note_e.setPlaceholderText("Optional note, e.g. CML OG Ark — 2015 rates")
        discord_e = QLineEdit(); discord_e.setPlaceholderText("Optional Discord invite link")
        fav_cb = QCheckBox("Favorite")
        form.addRow("Name:", name_e); form.addRow("Address:", ip_e)
        form.addRow("Game port:", game_e); form.addRow("Query port:", query_e)
        form.addRow("Cluster:", cluster_e); form.addRow("Note:", note_e); form.addRow("Discord:", discord_e); form.addRow("", fav_cb)
        brow = QHBoxLayout(); ok_b = QPushButton("Add"); ok_b.setObjectName("Primary"); cancel_b = QPushButton("Cancel")
        brow.addStretch(1); brow.addWidget(ok_b); brow.addWidget(cancel_b); form.addRow(brow)
        ok_b.clicked.connect(dlg.accept); cancel_b.clicked.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        ip = ip_e.text().strip()
        if not ip:
            QMessageBox.warning(self, APP_NAME, "Enter an IP or hostname."); return
        servers = self._servers()
        servers.append({"name": name_e.text().strip(), "ip": ip,
                        "game_port": int(game_e.value()), "query_port": int(query_e.value()),
                        "cluster": cluster_e.text().strip(), "favorite": bool(fav_cb.isChecked()),
                        "note": note_e.text().strip(), "discord": discord_e.text().strip()})
        self._save(servers); self.status_label.setText(f"Added {ip}."); self.refresh()

    def _on_refresh_all(self):
        if self._thread is not None and self._thread.isRunning():
            return
        servers = self._servers()
        if not servers: return
        self.status_label.setText("Querying servers…")
        try: self.refresh_b.setEnabled(False)
        except Exception: pass
        self._thread = _ServerQueryThread(servers)
        self._thread.done.connect(self._on_queried)
        self._thread.start()

    def _on_queried(self, results):
        self._thread = None
        try: self.refresh_b.setEnabled(True)
        except Exception: pass
        try:
            for k, val in (results or {}).items():
                info, rules = val if isinstance(val, tuple) else (val, None)
                if info is None:
                    self._results[int(k)] = None
                    self._rules.pop(int(k), None)  # offline: drop stale rules
                else:
                    self._results[int(k)] = info
                    if rules is not None: self._rules[int(k)] = rules
        except Exception: pass
        servers = self._servers()
        online = sum(1 for v in self._results.values() if v)
        self.status_label.setText(f"{online} of {len(servers)} server(s) online.")
        self.refresh()

    def _on_refresh_one(self, i):
        if self._thread is not None and self._thread.isRunning():
            self.status_label.setText("Already querying — wait for it to finish."); return
        servers = self._servers()
        if not (0 <= i < len(servers)): return
        self._thread = _ServerQueryThread([servers[i]])
        self._thread.done.connect(lambda res, _i=i: self._on_queried_one(_i, res))
        self._thread.start()

    def _on_queried_one(self, i, results):
        self._thread = None
        try:
            if results and 0 in results:
                info, rules = results[0] if isinstance(results[0], tuple) else (results[0], None)
                if info is None:
                    self._results[i] = None
                    self._rules.pop(i, None)
                else:
                    self._results[i] = info
                    if rules is not None: self._rules[i] = rules
        except Exception: pass
        self.refresh()

    def _on_players(self, srv):
        """v1.72.0: who's online on this server (A2S_PLAYER via
        tek_lib). Queried on demand in a dialog - servers only publish
        the player list when asked, and it costs a second query."""
        if getattr(self, "_players_thread", None) is not None and self._players_thread.isRunning():
            return
        dlg = QDialog(self); dlg.setWindowTitle("Players on server")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        head = QLabel(f"{srv.get('ip', '')}:{srv.get('query_port', 27015)} — asking the server…")
        head.setObjectName("Muted"); head.setWordWrap(True); lay.addWidget(head)
        lst = QListWidget(); lay.addWidget(lst)
        close_b = QPushButton("Close"); close_b.clicked.connect(dlg.accept); lay.addWidget(close_b)
        self._players_dlg = dlg; self._players_list = lst; self._players_head = head
        self._players_thread = _ServerPlayersThread(srv)
        self._players_thread.done.connect(self._on_players_done)
        self._players_thread.start()
        dlg.exec()

    def _on_players_done(self, status):
        self._players_thread = None
        try:
            lst, head = self._players_list, self._players_head
            lst.clear()
            if status is None or getattr(status, "info", None) is None:
                head.setText("The server didn't answer — offline or unreachable.")
                return
            info = status.info
            players = status.players
            ping = f" • {info.ping_ms:.0f} ms" if getattr(info, "ping_ms", None) is not None else ""
            if players is None:
                head.setText(f"{info.name or 'Server'} — answered, but didn't publish a player list{ping}.")
                return
            head.setText(f"{info.name or 'Server'} — {len(players)} player(s) online{ping}.")
            for p in sorted(players, key=lambda x: -x.duration_seconds):
                lst.addItem(f"{p.name or '(unnamed)'} — {p.duration_str} connected — score {p.score}")
            if not players:
                lst.addItem("Server is empty.")
        except Exception:
            pass

    def _on_join(self, srv):
        try:
            if _open_url(f"steam://connect/{srv.get('ip', '')}:{srv.get('game_port', 7777)}"):
                self.main.set_status(f"Opening Steam to join {srv.get('ip', '')} — you must own ARK on Steam.")
            else:
                self.main.set_status("Couldn't open Steam — is Steam installed?")
        except Exception: pass

    def _on_join_with_build(self, srv):
        """TEK-style direct join: pick an installed timecapsule build and
        launch its exe with +connect, instead of Steam's current install."""
        try:
            steam = steam_dir_for(self.main.store)
        except Exception:
            steam = None
        builds = []
        try:
            for v in (self.main.versions.versions or []):
                exe = game_exe_for(steam, v, self.main.store) if steam else None
                if exe and Path(exe).is_file():
                    builds.append(v)
        except Exception:
            builds = []
        if not builds:
            QMessageBox.information(self, APP_NAME, "No builds installed yet — download a build on the Versions tab first, then join with it.")
            return
        dlg = QDialog(self); dlg.setWindowTitle("Join with build")
        v = QVBoxLayout(dlg)
        lab = QLabel(f"Join {srv.get('ip', '')}:{srv.get('game_port', 7777)} with which installed build?")
        lab.setWordWrap(True); v.addWidget(lab)
        combo = QComboBox()
        for b in builds: combo.addItem(b.get("name", ""))
        try:
            cur = self.main.versions.selected
            if cur is not None: combo.setCurrentText(cur.get("name", ""))
        except Exception: pass
        v.addWidget(combo)
        brow = QHBoxLayout(); ok_b = QPushButton("Join"); ok_b.setObjectName("Primary"); cancel_b = QPushButton("Cancel")
        brow.addStretch(1); brow.addWidget(ok_b); brow.addWidget(cancel_b); v.addLayout(brow)
        ok_b.clicked.connect(dlg.accept); cancel_b.clicked.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        if not combo.count(): return
        self._launch_join(builds[combo.currentIndex()], srv)

    def _launch_join(self, build, srv):
        """Direct exe launch with +connect. Mirrors VersionsPage's Play
        preflight (steam_appid repair, Steam must be running) but skips
        the desktop shortcut so join args never pollute the Play shortcut."""
        try:
            steam = steam_dir_for(self.main.store)
            exe = game_exe_for(steam, build, self.main.store) if steam else None
        except Exception:
            exe = None
        if not exe or not Path(exe).is_file():
            QMessageBox.warning(self, APP_NAME, "That build isn't installed anymore."); return
        try:
            appid = Path(exe).parent / "steam_appid.txt"
            if not appid.is_file(): appid.write_text(str(STEAM_APP_ID))
        except OSError: pass
        try:
            running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe"],
                                     capture_output=True, text=True, timeout=15,
                                     creationflags=_hidden_flags())
            steam_up = "steam.exe" in (running.stdout or "").lower()
        except (OSError, subprocess.SubprocessError):
            steam_up = True  # can't check — don't block the launch
        if not steam_up and steam:
            try:
                subprocess.Popen([str(Path(steam) / "steam.exe")])
                self.status_label.setText("Starting Steam so the game can verify ownership...")
                time.sleep(10)
            except OSError:
                QMessageBox.warning(self, APP_NAME, "Steam isn't running — open Steam first, then join."); return
        profiles = self.main.store.get("launch_profiles", {}) or {}
        args_str = ((profiles.get(build.get("name", ""), "") or "").strip()
                    or self.main.store.get("launch_args", "").strip())
        culture = (self.main.store.get("game_culture", "") or "").strip()
        if culture and "-culture" not in args_str:
            args_str = (args_str + f" -culture={culture}").strip()
        cmd = [str(exe)]
        if args_str: cmd.extend(args_str.split())
        cmd += ["+connect", f"{srv.get('ip', '')}:{srv.get('game_port', 7777)}"]
        try:
            subprocess.Popen(cmd, cwd=str(Path(exe).parent))
            self.status_label.setText(f"Joining {srv.get('ip', '')} with {build.get('name', '')}...")
            try:
                if self.main.store.get("discord_rich_presence"):
                    discord_set_playing(self.main.store.get("discord_client_id", ""), build.get("name", ""))
            except Exception: pass
            if self.main.store.get("close_on_launch"):
                try: self.main.close()
                except Exception: pass
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't launch the game: {e}")

    def _on_copy(self, srv):
        try:
            _copy_text(f"{srv.get('ip', '')}:{srv.get('game_port', 7777)}")
            self.status_label.setText("Copied server address.")
        except Exception: pass

    def _on_remove(self, i):
        servers = self._servers()
        if 0 <= i < len(servers):
            servers.pop(i); self._save(servers)
            nr = {}; nru = {}
            for k, val in self._results.items():
                if k < i: nr[k] = val
                elif k > i: nr[k - 1] = val
            for k, val in self._rules.items():
                if k < i: nru[k] = val
                elif k > i: nru[k - 1] = val
            self._results = nr; self._rules = nru
            self.status_label.setText("Server removed."); self.refresh()

    def _on_favorite(self, i):
        servers = self._servers()
        if 0 <= i < len(servers):
            servers[i]["favorite"] = not servers[i].get("favorite")
            self._save(servers); self.refresh()

    def _on_scan_lan(self):
        if self._thread is not None and self._thread.isRunning():
            self.status_label.setText("Already querying — wait for it to finish."); return
        self.status_label.setText("Scanning the LAN for ARK servers…")
        self._thread = _LanScanThread(); self._thread.done.connect(self._on_lan_found); self._thread.start()

    def _on_lan_found(self, found):
        self._thread = None
        servers = self._servers()
        known = {(s.get("ip", ""), int(s.get("query_port", 27015))) for s in servers}
        new = [f for f in found if (f["ip"], f["query_port"]) not in known]
        if not new:
            self.status_label.setText("No new LAN servers found."); return
        dlg = QDialog(self); dlg.setWindowTitle("LAN servers found")
        v = QVBoxLayout(dlg)
        checks = []
        for f in new:
            info = f.get("info") or {}
            label = (info.get("name") or f["ip"]) + f"  ({f['ip']}:{f['query_port']})"
            cb = QCheckBox(label); cb.setChecked(True); v.addWidget(cb); checks.append((cb, f))
        brow = QHBoxLayout(); ok_b = QPushButton("Add selected"); ok_b.setObjectName("Primary"); cancel_b = QPushButton("Cancel")
        brow.addStretch(1); brow.addWidget(ok_b); brow.addWidget(cancel_b); v.addLayout(brow)
        ok_b.clicked.connect(dlg.accept); cancel_b.clicked.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        added = 0
        for cb, f in checks:
            if not cb.isChecked(): continue
            info = f.get("info") or {}
            servers.append({"name": info.get("name", ""), "ip": f["ip"],
                            "game_port": 7777, "query_port": f["query_port"],
                            "cluster": "LAN", "favorite": False})
            added += 1
        self._save(servers); self.status_label.setText(f"Added {added} LAN server(s)."); self.refresh()
        # Fresh servers have no results yet — query everything now so the
        # new ones show live data instead of "Not queried yet".
        self._on_refresh_all()

class GameOptionsPage(QWidget):
    """Launch arguments as checkboxes plus a free-text field, editing
    the same store keys the Settings tab uses (launch_args and
    launch_arg_presets). Mirrors TEKLauncher's GameOptions tab.
    Per-build args can still be set on the Versions tab."""

    _FLAGS = [
        ("-sm4", "Shader Model 4 — simpler shaders, big FPS gain on weak GPUs."),
        ("-lowmemory", "Low memory mode — reduces RAM use."),
        ("-nomansky", "Disables the sky — fewer effects, more FPS."),
        ("-windowed", "Run in a window instead of fullscreen."),
        ("-high", "High CPU priority for the game (do not combine with -low)."),
        ("-nosound", "Disables sound — last resort FPS gain."),
        ("-d3d10", "DirectX 10 path — helps very old GPUs that choke on DX11."),
        ("-nosplash", "Skip the splash screens on launch."),
        ("-nomemorybias", "Disables the game's memory bias."),
        ("-norhithread", "Disables the render thread — can fix stutter on some PCs."),
        ("-novsync", "Disables VSync — uncaps the frame rate."),
        ("-preventhibernation", "Keeps creatures active in single-player (no dino hibernation)."),
    ]

    # TEK's game-language list (display name, -culture= code).
    _CULTURES = [
        ("Steam default", ""), ("Català", "ca"), ("Český", "cs"), ("Dansk", "da"),
        ("Deutsch", "de"), ("English", "en"), ("Español", "es"), ("Euskara", "eu"),
        ("Suomi", "fi"), ("Français", "fr"), ("Magyar", "hu"), ("Italiano", "it"),
        ("日本語", "ja"), ("ქართული", "ka"), ("한국어", "ko"), ("Nederlands", "nl"),
        ("Polski", "pl"), ("Português/Brasil", "pt_BR"), ("Русский", "ru"),
        ("Svenska", "sv"), ("ภาษาไทย", "th"), ("Türkçe", "tr"), ("Українська", "uk"),
        ("中文", "zh"), ("中文 (简体)", "zh-Hans-CN"), ("中文 (台湾)", "zh-TW"),
    ]

    def __init__(self, main):
        super().__init__(); self.main = main
        self._syncing = False
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner)
        v.setContentsMargins(28, 24, 28, 28); v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(page_header("Game Options",
            "Default launch arguments for ARK. These are the same arguments "
            "the Settings tab edits, and per-build args can still be set on "
            "the Versions tab."))
        self.text = QLineEdit(); self.text.setPlaceholderText("e.g. -sm4 -lowmemory")
        self.text.editingFinished.connect(self._on_text_committed)
        v.addWidget(self.text)
        self.checks = {}
        for flag, desc in self._FLAGS:
            card = QFrame(); card.setObjectName("Card")
            cv = QVBoxLayout(card); cv.setContentsMargins(16, 12, 16, 12); cv.setSpacing(4)
            cb = QCheckBox(flag); cb.toggled.connect(lambda _c=False, _f=flag: self._on_flag(_f))
            cv.addWidget(cb)
            d = QLabel(desc); d.setObjectName("Muted"); d.setWordWrap(True); cv.addWidget(d)
            self.checks[flag] = cb
            v.addWidget(card)
        prow = FlowLayout(); prow.setSpacing(10)
        for pname in ("High FPS", "Balanced", "Windowed", "Pretty"):
            b = QPushButton(pname); b.clicked.connect(lambda _c=False, _p=pname: self._on_preset(_p)); prow.addWidget(b)
        prow.addStretch(1); v.addLayout(prow)
        srow = FlowLayout(); srow.setSpacing(10)
        self.name_e = QLineEdit(); self.name_e.setPlaceholderText("Preset name"); srow.addWidget(self.name_e, 1)
        sb = QPushButton("Save current as preset"); sb.setObjectName("Primary"); sb.clicked.connect(self._on_save_preset); srow.addWidget(sb)
        srow.addStretch(1); v.addLayout(srow)
        # v1.66.0: game language (-culture=, TEK's Play-tab dropdown) and
        # close-on-launch (TEK's launcher setting). Language defaults to
        # Steam default (no flag) so nobody's language changes unasked.
        lrow = FlowLayout(); lrow.setSpacing(10)
        lrow.addWidget(QLabel("Game language:"))
        self.lang_combo = QComboBox()
        for disp, code in self._CULTURES:
            self.lang_combo.addItem(disp, code)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lrow.addWidget(self.lang_combo, 1)
        lrow.addStretch(1); v.addLayout(lrow)
        self.close_cb = QCheckBox("Close the launcher when the game launches")
        self.close_cb.toggled.connect(self._on_close_toggled)
        v.addWidget(self.close_cb)
        fb = QPushButton("Fix bloom (writes Scalability.ini for the selected build)")
        fb.clicked.connect(self._on_fix_bloom); v.addWidget(fb)
        self.status_label = QLabel(""); self.status_label.setObjectName("Muted"); self.status_label.setWordWrap(True)
        v.addWidget(self.status_label)
        v.addStretch(1); scroll.setWidget(inner); outer.addWidget(scroll)

    def _args(self):
        try: return (self.main.store.get("launch_args", "") or "").split()
        except Exception: return []

    def refresh(self):
        args = set(self._args())
        self._syncing = True
        try:
            self.text.setText(self.main.store.get("launch_args", "") or "")
            for flag, cb in self.checks.items():
                cb.blockSignals(True); cb.setChecked(flag in args); cb.blockSignals(False)
            culture = (self.main.store.get("game_culture", "") or "")
            self.lang_combo.blockSignals(True)
            idx = self.lang_combo.findData(culture)
            self.lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.lang_combo.blockSignals(False)
            self.close_cb.blockSignals(True)
            self.close_cb.setChecked(bool(self.main.store.get("close_on_launch", False)))
            self.close_cb.blockSignals(False)
        finally:
            self._syncing = False

    def _on_flag(self, flag):
        if self._syncing: return
        args = self._args()
        if self.checks[flag].isChecked():
            if flag not in args: args.append(flag)
        else:
            args = [a for a in args if a != flag]
        self.main.store.set("launch_args", " ".join(args))
        self._syncing = True
        try: self.text.setText(" ".join(args))
        finally: self._syncing = False

    def _on_text_committed(self):
        if self._syncing: return
        self.main.store.set("launch_args", self.text.text())
        self.refresh()

    def _on_preset(self, pname):
        presets = self.main.store.get("launch_arg_presets", {}) or {}
        if pname in presets:
            self.main.store.set("launch_args", presets[pname]); self.refresh()
            self.status_label.setText(f"Preset '{pname}' applied.")

    def _on_save_preset(self):
        name = (self.name_e.text() or "").strip()
        if not name:
            QMessageBox.warning(self, APP_NAME, "Type a name for the preset first."); return
        presets = dict(self.main.store.get("launch_arg_presets", {}) or {})
        presets[name] = self.main.store.get("launch_args", "") or ""
        self.main.store.set("launch_arg_presets", presets)
        self.status_label.setText(f"Preset '{name}' saved.")

    def _on_language_changed(self, _idx):
        if self._syncing: return
        try: self.main.store.set("game_culture", self.lang_combo.currentData() or "")
        except Exception: pass

    def _on_close_toggled(self, checked):
        if self._syncing: return
        try: self.main.store.set("close_on_launch", bool(checked))
        except Exception: pass

    def _on_fix_bloom(self):
        """TEK's FixBloom, verified in source: write Scalability.ini with
        r.BloomQuality=1 at every post-process quality level, into the
        selected build. Refuses while the game runs (it would overwrite
        the file on exit)."""
        try:
            sel = self.main.versions.selected
        except Exception:
            sel = None
        if sel is None:
            QMessageBox.information(self, APP_NAME, "Pick a build on the Versions tab first."); return
        try:
            steam = steam_dir_for(self.main.store)
            game_dir = game_dir_for(self.main.store, sel, steam) if steam else None
        except Exception:
            game_dir = None
        if not game_dir or not Path(game_dir).is_dir():
            QMessageBox.information(self, APP_NAME, "That build isn't installed yet — download it first."); return
        try:
            running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ShooterGame.exe"],
                                     capture_output=True, text=True, timeout=15,
                                     creationflags=_hidden_flags())
            if "ShooterGame.exe" in (running.stdout or ""):
                QMessageBox.warning(self, APP_NAME, "Close the game first — it would overwrite this file on exit."); return
        except (OSError, subprocess.SubprocessError):
            pass  # can't check — proceed
        ini_path = Path(game_dir) / "ShooterGame" / "Saved" / "Config" / "WindowsNoEditor" / "Scalability.ini"
        try:
            ini_path.parent.mkdir(parents=True, exist_ok=True)
            ini_path.write_text(_bloom_ini_text())
            self.status_label.setText(f"Bloom fix written for {sel.get('name', '')}.")
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't write the bloom fix: {e}")

def _fetch_active_users():
    """v1.71.0: read the public counter total; '—' on any failure
    (including 404 for a fresh key with no pings yet, bad JSON, or a
    missing value). Pure read, no data sent."""
    try:
        req = urllib.request.Request(PUBLIC_PING_GET, headers={"User-Agent": "LegacyARKLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        value = data.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "—"
        return f"{int(value):,}"
    except Exception:
        return "—"

PRESENCE_BROKER_HOST = "broker.hivemq.com"
PRESENCE_BROKER_PORT = 1883
PRESENCE_TOPIC_PREFIX = "legacyark/presence/v1/"

def _mqtt_encode_length(n):
    """MQTT variable-byte remaining-length encoding."""
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)

def _mqtt_encode_string(s):
    b = s.encode("utf-8")
    return len(b).to_bytes(2, "big") + b

def _mqtt_connect_packet(client_id, will_topic, will_payload, keepalive=60):
    """CONNECT with clean session, Will (QoS 0, retained) and keepalive.
    Flags: clean session 0x02 | will flag 0x04 | will retain 0x20."""
    var = b"\x00\x04MQTT\x04"
    var += bytes([0x02 | 0x04 | 0x20]) + keepalive.to_bytes(2, "big")
    payload = _mqtt_encode_string(client_id)
    payload += _mqtt_encode_string(will_topic)
    payload += _mqtt_encode_string(will_payload)
    body = var + payload
    return b"\x10" + _mqtt_encode_length(len(body)) + body

def _mqtt_publish_packet(topic, payload, retain=True):
    body = _mqtt_encode_string(topic) + payload.encode("utf-8")
    header = 0x30 | (0x01 if retain else 0x00)
    return bytes([header]) + _mqtt_encode_length(len(body)) + body

def _mqtt_subscribe_packet(packet_id, topic):
    body = packet_id.to_bytes(2, "big") + _mqtt_encode_string(topic) + b"\x00"
    return b"\x82" + _mqtt_encode_length(len(body)) + body

def _mqtt_parse_packets(buf):
    """Parse complete MQTT packets out of buf. Returns (packets, rest)
    where each packet is (type_byte, payload_bytes). Partial packets
    stay in rest; malformed length fields drop one byte so a corrupt
    stream cannot wedge the parser forever."""
    packets = []
    i = 0
    n = len(buf)
    while i < n:
        if i + 1 >= n:
            break
        mult = 1
        length = 0
        j = i + 1
        count = 0
        bad = False
        while True:
            if j >= n:
                return packets, buf[i:]
            b = buf[j]
            length += (b & 0x7F) * mult
            mult *= 128
            j += 1
            count += 1
            if not (b & 0x80):
                break
            if count >= 4:
                bad = True
                break
        if bad or length > 1024 * 1024:
            return packets, buf[i + 1:]
        if j + length > n:
            return packets, buf[i:]
        packets.append((buf[i] & 0xF0, buf[j:j + length]))
        i = j + length
    return packets, buf[i:]

class _PresenceThread(QThread):
    """v1.71.3: live presence over MQTT (no new dependency — a minimal
    MQTT 3.1.1 client on a raw socket). Same opt-in toggle as the usage
    ping, same anonymity: the only identity is a random install UUID
    stored in settings; no username, no game data. Publishes retained
    'online' on connect, pings to hold the connection, and publishes
    retained 'offline' + DISCONNECT on a clean stop. If the process
    dies without a clean stop, the broker fires the Last Will
    ('offline', retained) when the TCP connection drops — so a crash
    still clears presence. Subscribes to the presence wildcard so the
    header can show the live online count; retained messages deliver
    the current set on subscribe. Detached (no parent); finished ->
    deleteLater. Count updates go out on the count signal (Qt queued
    connection) — no UI touches off the thread."""
    count = pyqtSignal(int)
    def __init__(self, presence_id):
        super().__init__()
        self.presence_id = presence_id
        self._stop = False
        self._sock = None
    def request_stop(self):
        # Flag only — no socket shutdown: the pump loop notices within
        # ~1s (select timeout) and does the graceful offline publish +
        # DISCONNECT. Shutting the socket down here would make that
        # publish fail.
        self._stop = True
    def run(self):
        topic = PRESENCE_TOPIC_PREFIX + self.presence_id
        backoff = 5.0
        while not self._stop:
            try:
                self._run_once(topic)
                backoff = 5.0
            except Exception:
                pass
            if self._stop:
                break
            slept = 0.0
            while not self._stop and slept < backoff:
                time.sleep(0.2)
                slept += 0.2
            backoff = min(backoff * 2.0, 30.0)
    def _run_once(self, topic):
        """One connection lifetime: connect, publish online, subscribe,
        then pump packets (pings + count updates) until error or stop.
        On a clean stop, publish offline + DISCONNECT before returning;
        on error or broker close, return without them and let the
        broker fire the Will."""
        sock = socket.create_connection(
            (PRESENCE_BROKER_HOST, PRESENCE_BROKER_PORT), timeout=10)
        self._sock = sock
        try:
            sock.sendall(_mqtt_connect_packet(
                self.presence_id, topic, "offline", keepalive=60))
            # CONNACK is 4 bytes; read exactly (TCP may fragment it).
            connack = bytearray()
            end = time.time() + 12.0
            while len(connack) < 4 and time.time() < end:
                try:
                    chunk = sock.recv(4 - len(connack))
                except Exception:
                    chunk = b""
                if not chunk:
                    break
                connack += chunk
            if len(connack) < 4 or connack[0] != 0x20 or connack[3] != 0x00:
                return
            sock.sendall(_mqtt_publish_packet(topic, "online", retain=True))
            sock.sendall(_mqtt_subscribe_packet(1, PRESENCE_TOPIC_PREFIX + "#"))
            online = {}
            buf = bytearray()
            last_ping = time.time()
            sock.settimeout(None)
            while True:
                if self._stop:
                    break
                r, _, _ = select.select([sock], [], [], 1.0)
                if r:
                    try:
                        chunk = sock.recv(4096)
                    except Exception:
                        chunk = b""
                    if not chunk:
                        if self._stop:
                            break
                        return  # broker closed or error: Will fires
                    buf += chunk
                    packets, rest = _mqtt_parse_packets(bytes(buf))
                    buf = bytearray(rest)
                    for ptype, payload in packets:
                        if ptype == 0x30 and len(payload) >= 2:
                            tlen = int.from_bytes(payload[0:2], "big")
                            if len(payload) >= 2 + tlen:
                                t = payload[2:2 + tlen].decode("utf-8", "replace")
                                m = payload[2 + tlen:].decode("utf-8", "replace")
                                if t.startswith(PRESENCE_TOPIC_PREFIX):
                                    uid = t[len(PRESENCE_TOPIC_PREFIX):]
                                    if uid:
                                        if m == "online":
                                            online[uid] = True
                                        elif m == "offline":
                                            online.pop(uid, None)
                                        try: self.count.emit(len(online))
                                        except Exception: pass
                if self._stop:
                    break
                if time.time() - last_ping >= 45.0:
                    try:
                        sock.sendall(b"\xc0\x00")
                    except Exception:
                        if self._stop:
                            break
                        return
                    last_ping = time.time()
            # Clean stop only (reached via break): publish offline, DISCONNECT.
            try:
                sock.sendall(_mqtt_publish_packet(topic, "offline", retain=True))
            except Exception:
                pass
            try:
                sock.sendall(b"\xe0\x00")
            except Exception:
                pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
            self._sock = None

class _ActiveUsersThread(QThread):
    """v1.71.0: fetch the header total off the UI thread; the result
    signal is what touches the label (Qt queued connection)."""
    result = pyqtSignal(str)
    def run(self):
        try: self.result.emit(_fetch_active_users())
        except Exception:
            try: self.result.emit("—")
            except Exception: pass

class _UsagePingThread(QThread):
    """v1.71.2: send both usage pings off the UI thread and report
    whether either one succeeded. Detached (no parent) like the header
    fetch thread, so closing the window mid-ping can't destroy a
    running thread; finished -> deleteLater. The done signal is what
    marks the day (on the UI thread) — no store writes off it."""
    done = pyqtSignal(bool)
    def run(self):
        ok = False
        try:
            if _send_usage_ping(VERSION):
                ok = True
        except Exception:
            pass
        try:
            if _send_public_ping():
                ok = True
        except Exception:
            pass
        try: self.done.emit(ok)
        except Exception: pass

class MainWindow(QMainWindow):
    def __init__(self, store):
        super().__init__(); self.store = store; self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(brand_pixmap(48)))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        # v1.40.0: OPAQUE again, reversing v1.39.0. His "transparent"
        # look is NOT desktop transparency — it is an image painted
        # INSIDE the window, with a dark overlay on top of it (see
        # paintEvent). WA_TranslucentBackground made the desktop /
        # browser / Activate-Windows watermark bleed through the top
        # bar and bottom, which is exactly the mess in the v1.39
        # screenshot. Opaque window + painted image = his method,
        # and no desktop bleed. Corners are square on Windows, not
        # rounded-transparent — that is the trade-off, and it is the
        # clean one.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        self.resize(1360, 860); self.setMinimumSize(900, 600)
        
        root = QWidget(); self.setCentralWidget(root)
        rv = QVBoxLayout(root); rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(0)
        
        self.titlebar = TitleBar(self); rv.addWidget(self.titlebar); rv.addWidget(hair())
        # v1.39.0 Config Editor layout: top bar (above) + left sidebar
        # + pages, like his. Sidebar: 258px total (14px margins + 230px
        # rows, his exact sidebar geometry), rows 46px (NavButton
        # default), radius 10, selected = card-hover tint, no accent
        # bar. Top nav from v1.31-v1.38 is gone — it was never his look.
        self.nav_group = QButtonGroup(self); self.nav_group.setExclusive(True)
        self.pages = QStackedWidget()
        self.dashboard = DashboardPage(self); self.versions = VersionsPage(self); self.mods = ModsPage(self); self.gameoptions = GameOptionsPage(self); self.servers = ServersPage(self); self.host = HostPage(self); self.backups = BackupsPage(self); self.help = HelpPage(self); self.settings = SettingsPage(self); self.tools = ToolsPage(self)
        for pg in (self.dashboard, self.versions, self.mods, self.gameoptions, self.servers, self.host, self.backups, self.help, self.settings, self.tools): self.pages.addWidget(pg)
        # v1.43.0 text-wrap on resize, all tabs: no horizontal scrolling in any
        # page scroll area. Vertical scroll still works. Inner widgets then
        # follow the viewport width, so WordWrap paragraphs re-wrap when the
        # window is resized, instead of staying wide and clipping off-right.
        try:
            # NOTE: self.pages is not attached to MainWindow yet here, so
            # self.findChildren would miss every page scroll area. Search
            # from self.pages, which already owns all pages.
            for _sa in self.pages.findChildren(QScrollArea):
                _sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                _sa.setWidgetResizable(True)
            # v1.43.0, same step: every paragraph label in every page wraps.
            # Some long labels never had WordWrap turned on, so horizontal-off
            # alone would still clip them at the viewport edge instead of
            # wrapping them. Short labels are unaffected in practice — they
            # still fit on one line, they just wrap instead of clipping if
            # the window gets narrow. Pixmap labels have no text, so this
            # is a no-op for them.
            for _lab in self.pages.findChildren(QLabel):
                try: _lab.setWordWrap(True)
                except Exception: pass
        except Exception:
            pass
        _dump_windows("init-pages-built")

        # Sidebar frame (QSS #Sidebar: transparent over the photo,
        # right divider only — like his, the sidebar is rows floating
        # over the background image, NOT a solid dark panel)
        self.side = QFrame(); self.side.setObjectName("Sidebar"); self.side.setMinimumWidth(200); self.side.setMaximumWidth(258)
        sv = QVBoxLayout(self.side); sv.setContentsMargins(14, 14, 14, 14); sv.setSpacing(4)
        # His sidebar search box (230x36, radius 10) — for ARK it searches
        # builds: typing jumps to Versions and sets its search filter.
        self.sidebar_search = QLineEdit(); self.sidebar_search.setPlaceholderText("Search builds…"); self.sidebar_search.setFixedHeight(36)
        self.sidebar_search.textChanged.connect(self._on_sidebar_search)
        sv.addWidget(self.sidebar_search)
        sv.addSpacing(8)
        self.nav_buttons = []
        self._nav_index = {}
        # v1.67.0: sidebar sections — one flat list of 11 was a junk
        # drawer. Order here MUST match the pages tuple above and the
        # update_panel titles list, because nav ids are page indices.
        _nav_sections = [
            ("Play", [("dashboard", "Dashboard"), ("box", "Versions"), ("plus", "Mods"), ("code", "Game Options")]),
            ("Servers", [("users", "Servers"), ("monitor", "Host")]),
            ("Launcher", [("save", "Backups"), ("help", "Help"), ("gear", "Settings"), ("search", "Tools")]),
        ]
        _i = 0
        for _sec, _items in _nav_sections:
            if _i > 0: sv.addSpacing(10)
            _h = QLabel(_sec.upper()); _h.setObjectName("SectionHeader"); sv.addWidget(_h)
            for ic, label in _items:
                b = NavButton(ic, label); b.setFixedHeight(46); b.setToolTip(f"{label} (Ctrl+{_i+1})" if _i < 8 else label); self.nav_group.addButton(b, _i); self.nav_buttons.append(b); sv.addWidget(b); self._nav_index[label] = _i; _i += 1
        self.nav_group.idClicked.connect(self.show_page); self.nav_buttons[0].setChecked(True)
        sv.addStretch(1)
        # His version pill: height 24, radius 12, quiet dark pill at sidebar bottom
        ver = QLabel(VERSION); ver.setObjectName("VersionPill"); ver.setAlignment(Qt.AlignmentFlag.AlignCenter); ver.setFixedHeight(24)
        sv.addWidget(ver)
        self.brand_text = self.titlebar.brand_text
        # Top-bar action button at right, like his action buttons at right.
        # v1.41.0: insert before min_b by widget, not by count()-3, because
        # the centered profile pill + stretches changed the layout count.
        # v1.54.0 Discord button (user order, Nov 1 01:21), v1.56.0 text
        # version (user order, Nov 1 01:41: "REMOVE LOGO ADD TXT THAT
        # SAYS JOIN DISCORD"): the top-bar button is now plain text
        # "JOIN DISCORD", NO logo icon, and clicking it opens the
        # community Discord invite in the browser. This replaces the
        # v1.46 placeholder and the v1.54 logo button.
        # This is the TOP-BAR button only — Dashboard hero Play and the
        # Dashboard tile Play still launch the game, so Play is NOT lost.
        top_play = QPushButton("JOIN DISCORD"); top_play.setObjectName("Primary"); top_play.setMinimumHeight(38)
        top_play.setToolTip("Join the Discord — opens the invite in your browser")
        def _dc_open(_c=False, _win=self):
            try:
                if _open_url(DISCORD_INVITE_URL):
                    _win.set_status("Opened Discord invite in your browser.")
                else:
                    _win.set_status(f"Discord invite: {DISCORD_INVITE_URL} — copy that link into your browser.")
            except Exception:
                pass
        top_play.clicked.connect(_dc_open)
        self.discord_button = top_play
        self.dc_placeholder_button = top_play  # old name, kept for compatibility
        try:
            _mi = None
            for _i in range(self.titlebar.h.count()):
                _it = self.titlebar.h.itemAt(_i)
                if _it is not None and _it.widget() is self.titlebar.min_b: _mi = _i; break
            self.titlebar.h.insertWidget(_mi if _mi is not None else self.titlebar.h.count(), top_play)
        except Exception:
            self.titlebar.h.addWidget(top_play)
        # Body: sidebar left, center pages, right details panel — his
        # three-column frame. Versions hides the global panel because
        # it already has its own grid + details split.
        self.details_panel = DetailsPanel(self)
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        body.addWidget(self.side); body.addWidget(self.pages, 1); body.addWidget(self.details_panel)
        rv.addLayout(body, 1)

        # v1.41.0: his window has NO bottom status bar. The status frame
        # is kept (set_status still writes to it, and to the details
        # panel) but hidden, so feedback lives in the details panel
        # instead of a second toolbar at the bottom.
        rv.addWidget(hair())
        self.statusbar = QFrame(); self.statusbar.setObjectName("StatusBar"); self.statusbar.setFixedHeight(30)
        sl = QHBoxLayout(self.statusbar); sl.setContentsMargins(16, 0, 16, 0); sl.setSpacing(10)
        self.status_label = QLabel("Ready"); self.status_label.setObjectName("Muted"); sl.addWidget(self.status_label)
        sl.addStretch(1)
        sver = QLabel(VERSION); sver.setObjectName("Ver"); sl.addWidget(sver)
        rv.addWidget(self.statusbar)
        self.statusbar.setVisible(False)
        
        self.setStyleSheet(QSS)
        # Start at a real size, never a tiny default: restored size if
        # saved, else a sensible 1280x800. A small-then-growing window
        # on launch looks broken.
        ws = store.get("window_size")
        if store.get("window_size_autosave") and ws:
            try:
                rw, rh = int(ws[0]), int(ws[1])
                # Guard against a bogus tiny saved size — never restore below minimum.
                if rw >= 900 and rh >= 600:
                    self.resize(rw, rh)
                else:
                    self.resize(1360, 860)
            except (TypeError, ValueError, IndexError):
                self.resize(1360, 860)
        else:
            self.resize(1360, 860)
        # v1.29.2: Always on Top was on in saved settings, which is why
        # the launcher stayed on top when clicking another app. Turn it
        # off once on first run of this version — the user can turn it
        # back on in Settings > Always on Top if they ever want it.
        if store.get("always_on_top") and not store.get("always_on_top_off_v1292"):
            store.set("always_on_top", False); store.set("always_on_top_off_v1292", True)
        if store.get("always_on_top"): self.apply_always_on_top()
        # v1.46.0: clamp the starting size to the actual monitor before first show.
        try: self._clamp_to_screen(); self._scale_chrome()
        except Exception: pass
        # v1.47.0 NOT down-scalable (user order): once the window is at its
        # starting size, it may grow / maximize, but it may NOT shrink below
        # that size — shrinking is what broke rows, cards and Settings labels
        # in earlier builds. The floor is the screen-fit starting size, not a
        # blind 1360x860, so a small monitor still fits (its starting size
        # is already clamped to that monitor in _clamp_to_screen).
        self.refresh_all(); _dump_windows("init-refresh-done"); self._ready = True
        self._maybe_usage_ping()
        # v1.71.3: live presence — same opt-in toggle as the ping.
        try: self._update_presence()
        except Exception: pass
        # v1.71.3: stop presence on a REAL quit (aboutToQuit fires for
        # every real quit path — window close and tray Quit — but never
        # for hide-to-tray, where the launcher is still running and
        # presence must stay up).
        try:
            QApplication.instance().aboutToQuit.connect(lambda: self._stop_presence(refresh=False))
        except Exception:
            pass
        # v1.71.0: header Active users — first fetch now, then every 60s.
        try:
            self._au_timer = QTimer(self)
            self._au_timer.timeout.connect(self._refresh_active_users)
            self._au_timer.start(60000)
            self._refresh_active_users()
        except Exception:
            pass
        # v1.65.0: What's New, once per version.
        try:
            if (store.get("last_seen_version", "") or "") != VERSION:
                QTimer.singleShot(1500, self._show_whats_new)
        except Exception:
            pass
        self._painted_once = False
        self._setup_shortcuts()
        # System tray: minimize-to-tray + startup tab.
        self._setup_tray()
        startup = (self.store.get("startup_tab", "") or "").strip()
        tab_index = self._nav_index.get(startup)
        if tab_index is not None:
            self.show_page(tab_index)
            self.nav_buttons[tab_index].setChecked(True)
        # Frameless edge resizing (pure Qt — no native/ctypes calls).
        self._resize_filter = FramelessResizeFilter(self)
        QApplication.instance().installEventFilter(self._resize_filter)
        # v1.47.0: lock the floor to the starting size, for BOTH resize paths:
        # Qt's setMinimumSize (native / snap / programmatic) and the frameless
        # edge-drag filter (MIN_W/MIN_H, which defaults to 1080x680 and would
        # otherwise let the window shrink below its starting size).
        try:
            self.setMinimumSize(self.width(), self.height())
            self._resize_filter.MIN_W = self.width()
            self._resize_filter.MIN_H = self.height()
        except Exception: pass

    def _setup_tray(self):
        try:
            self.tray = QSystemTrayIcon(QIcon(brand_pixmap(48)), self)
            menu = QMenu()
            show_a = menu.addAction("Show")
            show_a.triggered.connect(lambda: (self.show(), self.raise_(), self.activateWindow()))
            quit_a = menu.addAction("Quit")
            quit_a.triggered.connect(self._quit_from_tray)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._on_tray_activated)
            if bool(self.store.get("minimize_to_tray")):
                self.tray.show()
        except Exception:
            self.tray = None

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible(): self.hide()
            else: (self.show(), self.raise_(), self.activateWindow())

    def _quit_from_tray(self):
        self._force_quit = True
        self.close()

    def _any_work_running(self):
        """True if a build download, mod download, or backup is running."""
        try:
            for _pg in (getattr(self, "versions", None), getattr(self, "mods", None), getattr(self, "backups", None)):
                _w = getattr(_pg, "worker", None) if _pg is not None else None
                if _w is not None and _w.isRunning():
                    return True
        except Exception:
            pass
        return False

    def _cancel_running_workers(self):
        """Cancel build/mod downloads cleanly: kills SteamCMD, partial files
        kept so the next Download resumes instead of starting over."""
        try:
            for _pg in (getattr(self, "versions", None), getattr(self, "mods", None)):
                _w = getattr(_pg, "worker", None) if _pg is not None else None
                if _w is not None and _w.isRunning():
                    try: _w.cancel()
                    except Exception: pass
        except Exception:
            pass

    def closeEvent(self, e):
        # v1.60: clear Discord presence on a real quit, not on hide-to-tray.
        # _force_quit is set only for tray > Quit, so check that first.
        if getattr(self, "_force_quit", False):
            try: discord_clear()
            except Exception: pass
        # v1.53.0 close-while-downloading fix (see comment above).
        # Explicit quit from tray: cancel workers first, so no orphan SteamCMD.
        if getattr(self, "_force_quit", False):
            try: self._cancel_running_workers()
            except Exception: pass
            super().closeEvent(e)
            return
        # Download/work in progress: hide to tray and let it finish, even
        # if Minimize to Tray is OFF in Settings. This is the fix — closing
        # the window no longer orphans SteamCMD or skips the install step.
        # The user can still quit for real from tray > Quit (that cancels,
        # partial files kept for resume), or hit Cancel in the launcher first.
        if self._any_work_running():
            _tray = getattr(self, "tray", None)
            if _tray is not None:
                e.ignore()
                try: _tray.show()
                except Exception: pass
                self.hide()
                try:
                    _tray.showMessage(APP_NAME, "Download still running — launcher minimized to tray, download will finish normally. Right-click the tray icon to show it again, or Quit to cancel (partial files kept, you can resume by hitting Download again).",
                                          QSystemTrayIcon.MessageIcon.Information, 5000)
                except Exception:
                    pass
                return
            # No tray available (rare): ask, don't quit silently mid-download.
            try:
                from PyQt6.QtWidgets import QMessageBox as _MB
                _ans = _MB.question(self, APP_NAME, "A download is still running. Closing now will cancel it (partial files are kept, so you can resume by hitting Download again).\n\nClose anyway?",
                                    _MB.StandardButton.Yes | _MB.StandardButton.No, _MB.StandardButton.No)
                if _ans != _MB.StandardButton.Yes:
                    e.ignore(); return
                self._cancel_running_workers()
            except Exception:
                pass
            super().closeEvent(e)
            return
        # Minimize to tray instead of quitting (if enabled and tray exists).
        if bool(self.store.get("minimize_to_tray")) and getattr(self, "tray", None) is not None and not getattr(self, "_force_quit", False):
            e.ignore()
            self.hide()
            try:
                self.tray.showMessage(APP_NAME, "Launcher minimized to tray — right-click the icon to quit.",
                                      QSystemTrayIcon.MessageIcon.Information, 3000)
            except Exception:
                pass
            return
        super().closeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Custom background (Settings → Appearance): drawn first, at the
        # user's opacity. The dark overlay below stays semi-transparent
        # so the image shows through; without a background the painting
        # is exactly as before.
        bg_drawn = False
        bg_path = (self.store.get("custom_background", "") or "").strip()
        # v1.40.0 default background: YOUR ARK photo (art/ark-background.png,
        # the dino-on-the-mountain / obelisk shot you sent, 860x484),
        # NOT the tiny base.jpg header and NOT Apex art. If the user
        # set a custom image in Settings > Appearance, that wins.
        # If they set opacity to 0%, the image is invisible and the
        # look is plain dark again.
        if not (bg_path and Path(bg_path).is_file()):
            try:
                _art_bg = ART_DIR / "ark-background.png"
                if not _art_bg.is_file():
                    _art_bg = ART_DIR / "base.jpg"
                if _art_bg.is_file():
                    bg_path = str(_art_bg)
            except Exception:
                pass
        if bg_path and Path(bg_path).is_file():
            bg_pm = QPixmap(bg_path)
            if not bg_pm.isNull():
                try: op = float(self.store.get("background_opacity", 1.0))
                except (TypeError, ValueError): op = 1.0
                p.setOpacity(max(0.0, min(1.0, op)))
                p.drawPixmap(self.rect(), bg_pm.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation))
                p.setOpacity(1.0)
                bg_drawn = True
        r = 0 if self.isMaximized() else 18; path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        overlay = QColor(BG)
        if bg_drawn:
            # His overlay: #0b0d14 at 0.75 opacity = alpha 191.
            # Image at 100% opacity + 191 overlay = photo 25% visible,
            # dimmed but clearly there, like his. v1.39 was 0.5 image
            # x 200 overlay = ~11% visible, which is why it looked
            # like plain dark instead of a photo.
            overlay.setAlpha(191)
        p.fillPath(path, overlay); p.setPen(QPen(QColor(BORDER), 1)); p.drawPath(path); p.end()
        # First real paint is done — the startup dialog (if needed) may
        # now pop over a fully painted window instead of flashing over
        # a half-painted one.
        self._painted_once = True

    def toggle_max(self):
        if self.isMaximized(): self.showNormal()
        else: self.showMaximized()
        self.titlebar.sync_max_icon()

    def showEvent(self, e): super().showEvent(e); self.titlebar.sync_max_icon()

    def _clamp_to_screen(self):
        """v1.46.0 monitor scaling: never start larger than the monitor you are on.
        Old code always resized to 1360x860, even on a 1280x720 / 1366x768 laptop,
        so the bottom of the window was off-screen and unusable. Now the window
        is capped to 95% of the primary screen's available geometry (taskbar
        excluded), and the minimum size shrinks on small screens too, so the
        window can actually fit. On a big / 4K monitor this changes nothing —
        1360x860 is already under 95% there."""
        try:
            scr = QApplication.primaryScreen()
            if scr is None:
                return
            geo = scr.availableGeometry()
            w = min(self.width(), int(geo.width() * 0.95))
            h = min(self.height(), int(geo.height() * 0.95))
            min_w = min(900, int(geo.width() * 0.8))
            min_h = min(600, int(geo.height() * 0.8))
            self.setMinimumSize(max(640, min_w), max(480, min_h))
            if w != self.width() or h != self.height():
                self.resize(w, h)
        except Exception:
            pass

    def reset_window_size(self):
        """v1.46.0: Reset = fit-to-screen, not blind 1360x860.
        v1.47.0: Reset also re-locks the no-shrink floor to the new size."""
        try:
            self.resize(1360, 860); self._clamp_to_screen()
            self.store.set("window_size", [self.width(), self.height()])
            self.setMinimumSize(self.width(), self.height())
            if getattr(self, "_resize_filter", None) is not None:
                self._resize_filter.MIN_W = self.width()
                self._resize_filter.MIN_H = self.height()
        except Exception:
            pass

    def _scale_chrome(self):
        """v1.46.0: sidebar + details scale with window width, not fixed pixels.
        On a small monitor they shrink to their minimums (sidebar 200, details 240);
        on a wide / 4K monitor they grow (sidebar up to 320, details up to 380),
        so the chrome does not look tiny on a big screen or eat the whole
        window on a small one. Center pages always get what is left."""
        try:
            w = self.width()
            if getattr(self, "side", None) is not None:
                self.side.setMinimumWidth(max(180, min(258, int(w * 0.16))))
                self.side.setMaximumWidth(max(200, min(320, int(w * 0.20))))
            if getattr(self, "details_panel", None) is not None:
                self.details_panel.setMinimumWidth(max(200, min(280, int(w * 0.20))))
                self.details_panel.setMaximumWidth(max(240, min(380, int(w * 0.24))))
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # v1.46.0: scale chrome on every resize, so moving the window to a
        # different-size monitor (or just dragging it bigger/smaller) rescales
        # sidebar + details instead of leaving them at one fixed size.
        try: self._scale_chrome()
        except Exception: pass
        # v1.45.0: below 1150px wide, the summary details panel costs 240-320px
        # the center column needs more. Hide it (Versions already hides it
        # always) and show it again above 1150px — so nothing in the center
        # has to squeeze for a summary panel. This never hides navigation.
        try:
            if getattr(self, "details_panel", None) is not None and getattr(self, "_nav_index", None):
                _cur = self.pages.currentIndex() if getattr(self, "pages", None) is not None else -1
                _is_ver = (_cur == self._nav_index.get("Versions", 1))
                self.details_panel.setVisible((not _is_ver) and self.width() >= 1150)
        except Exception:
            pass
        if getattr(self, "_ready", False):
            s = self.store.settings
            # Never persist a bogus tiny size — it would haunt the next launch.
            if s.get("window_size_autosave") and self.width() >= 900 and self.height() >= 600:
                s["window_size"] = [self.width(), self.height()]; self.store.save()

    def _refresh_active_users(self):
        """v1.71.0: start a header-total fetch unless one is already
        running. Never raises into startup or the timer."""
        try:
            t = getattr(self, "_au_thread", None)
            if t is not None and t.isRunning():
                return
            # v1.71.1: no parent — a parented QThread deleted with the
            # window while a fetch is still running warns (and can
            # crash on exit); detached, it finishes on its own and
            # cleans itself up, and the ref clears on finish so the
            # next refresh can start a new one.
            t = _ActiveUsersThread()
            t.result.connect(self._on_active_users)
            t.finished.connect(lambda: setattr(self, "_au_thread", None))
            t.finished.connect(t.deleteLater)
            self._au_thread = t
            t.start()
        except Exception:
            pass

    def _on_active_users(self, text):
        try:
            if getattr(self, "_presence_live", False):
                return  # v1.71.3: live presence owns the label while on
            self.titlebar.active_users_label.setText(f"Active users: {text}")
        except Exception:
            pass

    def _presence_id(self):
        """v1.71.3: anonymous install UUID for presence, created on the
        UI thread (no store writes off it). Only exists while the
        toggle is on; it identifies one install, nothing else."""
        try:
            pid = (self.store.get("presence_id", "") or "").strip()
            if not pid:
                pid = uuid.uuid4().hex
                self.store.set("presence_id", pid)
            return pid
        except Exception:
            return uuid.uuid4().hex

    def _update_presence(self):
        """v1.71.3: start presence when the toggle is on, stop it when
        off. Starting is idempotent (an already-running thread is not
        duplicated); stopping publishes offline and falls the header
        back to the daily total."""
        try:
            if self.store.get("usage_ping"):
                t = getattr(self, "_presence_thread", None)
                if t is not None and t.isRunning():
                    return
                t = _PresenceThread(self._presence_id())
                t.count.connect(self._on_presence_count)
                t.finished.connect(lambda: setattr(self, "_presence_thread", None))
                t.finished.connect(t.deleteLater)
                self._presence_thread = t
                t.start()
            else:
                self._stop_presence()
        except Exception:
            pass

    def _on_presence_count(self, n):
        try:
            self._presence_live = True
            self.titlebar.active_users_label.setText(f"Active users: {n}")
            self.titlebar.active_users_label.setToolTip("Launchers online right now (opted-in only).")
        except Exception:
            pass

    def _stop_presence(self, refresh=True):
        """v1.71.3: stop the presence thread (it publishes offline +
        DISCONNECT on its way out) and fall the header back to the
        daily total. Waits at most ~2s; if the thread is stuck, the
        broker's Last Will clears presence when the socket dies.
        refresh=False skips the fallback fetch (used on quit, where
        starting a thread is pointless)."""
        try:
            t = getattr(self, "_presence_thread", None)
            if t is not None and t.isRunning():
                try:
                    t.request_stop()
                except Exception:
                    pass
                try:
                    t.wait(2000)
                except Exception:
                    pass
            self._presence_thread = None
        except Exception:
            pass
        try:
            self._presence_live = False
            self.titlebar.active_users_label.setToolTip("Live total of daily check-ins from opted-in launchers.")
        except Exception:
            pass
        if refresh:
            try:
                self._refresh_active_users()
            except Exception:
                pass

    def _maybe_usage_ping(self):
        """v1.71.2: anonymous usage ping, OFF by default. When the
        Settings toggle is on, send at most one SUCCESSFUL ping per day
        to TWO places, both carrying ONLY the launcher version (no
        username, no game data, no body): the project site (per-version
        counts in the private Netlify dashboard) and the public counter
        (the public daily total; the website's Active users now shows live presence instead). v1.71.1
        marked the day BEFORE sending, so a silently failed ping burned
        the whole day and the counter stayed empty with no error shown
        — that is what stranded his first attempt. Now the day is
        marked only when a send succeeds (via the thread's done signal,
        on the UI thread — no store writes off it), so a failed ping
        retries on the next launch or toggle flip. The gate key is new
        (usage_ping_success_day): old usage_ping_last_day marks are
        unproven — written before success-tracking — so they must not
        block a retry. A ping already in flight is not duplicated.
        Never raises into startup."""
        try:
            if not self.store.get("usage_ping"):
                return
            today = datetime.date.today().isoformat()
            if (self.store.get("usage_ping_success_day", "") or "") == today:
                return
            t = getattr(self, "_ping_thread", None)
            if t is not None and t.isRunning():
                return
            t = _UsagePingThread()
            t.done.connect(self._on_usage_ping_done)
            t.finished.connect(t.deleteLater)
            self._ping_thread = t
            t.start()
        except Exception:
            pass

    def _on_usage_ping_done(self, ok):
        try:
            self._ping_thread = None
        except Exception:
            pass
        try:
            if ok:
                self.store.set("usage_ping_success_day", datetime.date.today().isoformat())
        except Exception:
            pass

    def _show_whats_new(self):
        """v1.65.0: one-time What's New dialog for this version."""
        try:
            QMessageBox.information(self, f"What's new in {VERSION}",
                "• Live Active users: the header and website now show launchers actually online right now, not the daily total — closing the launcher clears you within seconds, and a crash clears you too (the broker's last-will). Same opt-in toggle, anonymous install ID only, no username or game data.\n"
                "• Usage ping fix: a failed ping no longer burns the day — the day counts only once a ping actually lands, so a blocked first try retries on your next launch instead of leaving the counter empty until tomorrow. Your first v1.71.2 launch retries right away.\n"
                "• Splash corners fixed: the loading screen is a true rounded pill now — the square pixmap corners no longer poke past the curve.\n"
                "• Active users in the header: the live total from the public counter now sits next to the title, refreshed every minute (dash if it can't be reached).\n"
                "• Loading screen restored: the branded LEGACY ARK Loading... splash is back while the UI builds — it was removed while the window-flashing bugs were still live, and those are fixed now.\n"
                "• Usage counting (from v1.69/70, folded in here): opt-in, off by default — one anonymous ping per day, version only, feeding the public total and the private per-version counts.\n"
                "• Download fix (from v1.68, folded in here): depot folders left over from another build no longer inflate the size number or mix newer files into your install — mismatched folders are wiped before downloading, same-build partials still resume.")
            self.store.set("last_seen_version", VERSION)
        except Exception:
            pass

    def set_status(self, msg):
        """Transient status message. Never raises — safe to call anywhere.
        v1.41.0: the bottom status bar is hidden (his has none), so the
        message also goes to the details panel, where the user can see it."""
        try:
            self.status_label.setText(str(msg) if msg else "Ready")
        except Exception:
            pass
        try:
            if getattr(self, "details_panel", None) is not None:
                self.details_panel.status_label.setText(str(msg) if msg else "Ready")
        except Exception:
            pass

    def _setup_shortcuts(self):
        try:
            from PyQt6.QtGui import QShortcut, QKeySequence
            for i in range(8):
                sc = QShortcut(QKeySequence(f"Ctrl+{i+1}"), self)
                sc.activated.connect(lambda _i=i: self.show_page(_i))
            scf = QShortcut(QKeySequence("Ctrl+F"), self); scf.activated.connect(lambda: (self.show_page(1), self.versions.search.setFocus()))
            scr = QShortcut(QKeySequence("Ctrl+R"), self); scr.activated.connect(self.refresh_all)
            scd = QShortcut(QKeySequence("Ctrl+D"), self); scd.activated.connect(lambda: self.versions._toggle_favorite() if hasattr(self.versions, "_toggle_favorite") else None)
            sce = QShortcut(QKeySequence("Ctrl+E"), self); sce.activated.connect(self.versions._copy_version_info)
            scsf = QShortcut(QKeySequence("Ctrl+Shift+F"), self); scsf.activated.connect(self.versions._clear_filters)
            sc9 = QShortcut(QKeySequence("Ctrl+9"), self); sc9.activated.connect(self.versions._on_play_game)
            sc0 = QShortcut(QKeySequence("Ctrl+0"), self); sc0.activated.connect(lambda: self.reset_window_size())
        except Exception:
            pass
    def _on_sidebar_search(self, text):
        # Sidebar search -> Versions search, like his sidebar search box.
        # Only jump when the user actually typed something, so tab
        # switches don't steal focus.
        try:
            if text:
                self.show_page(self._nav_index["Versions"])
                self.versions.search.setText(text)
        except Exception:
            pass

    def show_page(self, idx):
        self.pages.setCurrentIndex(idx); b = self.nav_group.button(idx)
        if b and not b.isChecked(): b.setChecked(True)
        try:
            if self.store.get("show_status_on_tab", True):
                self.set_status(self.nav_buttons[idx].title)
            if self.store.get("remember_last_tab"):
                self.store.set("startup_tab", self.nav_buttons[idx].title)
        except Exception:
            pass
        # Refresh only the page being shown — refreshing every page on
        # every tab switch was wasted work (each refresh() is
        # self-contained; cross-page data is read live, not cached).
        if self.store.get("refresh_on_tab", True):
            try:
                pg = self.pages.widget(idx)
                if pg is not None and hasattr(pg, "refresh"):
                    pg.refresh()
            except Exception:
                pass
        # v1.41.0 details panel: update + hide on Versions (its own
        # grid + details IS the right panel there).
        try:
            if getattr(self, "details_panel", None) is not None:
                self.details_panel.update_panel(idx)
                # v1.45.0: Versions always hides it; other tabs hide it below 1150px.
                self.details_panel.setVisible((idx != self._nav_index.get("Versions", 1)) and self.width() >= 1150)
        except Exception:
            pass
        self.repaint()

    def refresh_all(self):
        for pg in (self.dashboard, self.versions, self.mods, self.gameoptions, self.servers, self.host, self.backups, self.help, self.settings, self.tools): pg.refresh()
        try:
            if getattr(self, "titlebar", None) is not None and getattr(self.titlebar, "profile_name_label", None) is not None:
                self.titlebar.profile_name_label.setText(str(self.store.get("active_profile", "Default") or "Default"))
            if getattr(self, "details_panel", None) is not None:
                self.details_panel.update_panel(self.pages.currentIndex())
        except Exception:
            pass

    def apply_profile(self, name):
        """Switch player profile: applies its preferred build selection +
        launch args (+ host preset if the name matches one). Never raises."""
        try:
            profiles = self.store.get("profiles", []) or []
            p = next((x for x in profiles if isinstance(x, dict) and x.get("name") == name), None)
            if not p:
                return
            self.store.set("active_profile", p["name"])
            if (p.get("launch_args") or "").strip():
                self.store.set("launch_args", p["launch_args"])
            build = (p.get("build") or "").strip()
            if build:
                v = next((x for x in getattr(self.versions, "versions", []) if x.get("name") == build), None)
                if v:
                    self.versions._select_version(v)
            preset = (p.get("host_preset") or "").strip()
            if preset and hasattr(self.host, "_apply_preset"):
                try:
                    if preset in getattr(self.host, "PRESETS", {}):
                        self.host._apply_preset(preset)
                except Exception:
                    pass
            self.set_status(f"Profile: {p['name']}")
            self.refresh_all()
        except Exception:
            pass

    def apply_sidebar_width(self, w, collapsed=None):
        # v1.31.0: no sidebar anymore (top nav). Kept for callers
        # like Settings reset — it does nothing now.
        return

    def toggle_sidebar(self):
        # v1.31.0: no sidebar to collapse (top nav). No-op.
        return

    def apply_always_on_top(self):
        # v1.28.10 fix — this used to call self.show() unconditionally,
        # and MainWindow.__init__ calls it when always_on_top is on.
        # That showed the main window EARLY, during __init__, at 0,0
        # and unpainted, before centering and before win.show() in
        # main() — the "windows before the app fully loads". Now it
        # only re-shows if the window is already visible (user toggled
        # it after launch, or a settings reset). During startup the
        # flag is just set, and main() shows the window once, centered
        # and fully built.
        _was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(self.store.get("always_on_top")))
        if _was_visible:
            self.show()

    def restart_app(self):
        if getattr(sys, "frozen", False):
            os.execv(sys.executable, [sys.executable])
        else:
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])

def _splash_pixmap():
    """Branded splash shown while the heavy UI builds, so startup shows
    the logo instead of a black/white flashing window."""
    W, H = 460, 300
    pm = QPixmap(W, H)
    pm.fill(QColor(BG))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    logo = brand_pixmap(110)
    p.drawPixmap((W - 110) // 2, 48, logo)
    p.setPen(QColor(TEXT))
    p.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
    p.drawText(QRect(0, 178, W, 36), Qt.AlignmentFlag.AlignCenter, "LEGACY ARK")
    p.setPen(QColor(MUTED))
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(QRect(0, 214, W, 28), Qt.AlignmentFlag.AlignCenter, "Loading...")
    p.setPen(QPen(QColor(BORDER), 1))
    p.drawRoundedRect(1, 1, W - 2, H - 2, 10, 10)
    p.end()
    return pm

def main():
    # Hide the automation flag from bot detection: without this, streaming
    # sites' "are you human" checks refuse clicks from the embedded browser.
    # Must be set before the QApplication exists.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--disable-blink-features=AutomationControlled")
    # Give Windows its own taskbar identity: without this, the taskbar
    # groups the launcher under the generic Python icon.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LegacyARK.Launcher")
        except Exception:
            pass
    app = QApplication(sys.argv); app.setApplicationName(APP_NAME)
    # v1.35.0: Fusion, not Windows native style. Windows' native style
    # ignores QSS border-radius on most QPushButtons — that is why
    # Run all checks / Download / Create server / Delete / tile buttons
    # stayed square while hero Play looked pill, even though QSS said
    # 20px for all of them. Fusion draws the stylesheet as written,
    # so every button actually becomes a pill.
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    # Palette FIRST, before any window is created: without this the
    # very first paint is Windows' default, which flashes on screen
    # before the stylesheet applies. It follows the live theme (not
    # hard-coded dark), and is re-applied after apply_theme() below,
    # since that swaps BG/TEXT/etc. for the saved theme.
    def _set_palette():
        _pal = QPalette()
        _pal.setColor(QPalette.ColorRole.Window, QColor(BG))
        _pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
        _pal.setColor(QPalette.ColorRole.Base, QColor(INPUT_BG))
        _pal.setColor(QPalette.ColorRole.AlternateBase, QColor(CARD))
        _pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
        _pal.setColor(QPalette.ColorRole.Button, QColor(CARD))
        _pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
        _pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
        _pal.setColor(QPalette.ColorRole.HighlightedText, QColor(ON_ACCENT))
        app.setPalette(_pal)
    _set_palette()
    # Safety net: an unexpected error shows a dialog instead of killing
    # the app silently. Deduped so a repeating error doesn't spam.
    _seen_errors = set()
    def _hook(etype, value, tb):
        msg = "".join(__import__("traceback").format_exception(etype, value, tb))
        key = f"{etype.__name__}: {value}"
        try:
            print(msg, file=sys.stderr)
            try:
                with open(_app_dir() / "launcher-error.log", "a", encoding="utf-8") as _f:
                    _f.write(msg + "\n")
            except Exception:
                pass
            if key not in _seen_errors:
                _seen_errors.add(key)
                QMessageBox.critical(None, APP_NAME,
                    "Something went wrong, but the launcher is still running.\n\n"
                    f"{key}\n\nSend a screenshot of this to CML so it can be fixed.")
        except Exception:
            pass
    sys.excepthook = _hook
    # Point size, NOT pixel size: setPixelSize leaves pointSize at -1,
    # and Qt then spams "QFont::setPointSize: Point size <= 0 (-1)"
    # to the console on startup. 10pt ≈ the old 13px at 96 DPI.
    f = QFont("Segoe UI"); f.setPointSize(10); app.setFont(f)
    store = Store()
    # v1.30.0 revamp: if the saved theme is the old Granite default,
    # switch once to Studio so the revamp is actually seen. A theme
    # the user picked on purpose (Ember, ARK Light, etc.) is left alone.
    if store.get("theme") == "granite" and not store.get("theme_migrated_v1300"):
        store.set("theme", "studio"); store.set("theme_migrated_v1300", True)
    # v1.38.0 full Config Editor copy (for ARK, not Apex): switch once
    # to the new theme, even if Studio was saved before — that was the
    # old default, not a deliberate pick for this look. Reversible in
    # Settings > Theme, which applies instantly.
    if not store.get("layout_migrated_v1390"):
        store.set("background_opacity", 0.5); store.set("layout_migrated_v1390", True)
    # v1.40.0: his look needs the photo at 100% (dimmed by the 0.75
    # overlay in paintEvent, not by the slider). v1.39 left existing
    # installs at 50%, which made the photo almost invisible. This
    # runs AFTER the v1.39 block so fresh installs end at 1.0, not 0.5.
    if not store.get("background_migrated_v1400"):
        store.set("background_opacity", 1.0); store.set("background_migrated_v1400", True)
    if not store.get("configeditor_migrated_v1380"):
        store.set("theme", "configeditor"); store.set("configeditor_migrated_v1380", True)
    # v1.62.0 theme restriction: only Ember + Custom. Any saved theme
    # that is not one of those (including the Studio/Config Editor
    # defaults set by the migrations above) is switched once to Ember,
    # so the app never tries to load a deleted theme. Custom is kept.
    if store.get("theme") not in ("ember", "custom"):
        store.set("theme", "ember")
    apply_theme(store.get("theme", "ember"), store)
    _set_palette()
    # v1.71.0: splash screen restored — the v1.28.3 removal happened
    # while the window-flashing bugs were still live; those are fixed
    # now (v1.28.13 parents, v1.28.4/5 opacity + centering), so the
    # branded Loading... screen is safe to show again while the UI
    # builds. It is cosmetic only: any failure here never breaks
    # startup, and it is always closed once the main window appears
    # (or if the build itself fails, so a crash can never leave it
    # stuck on screen).
    splash = None
    try:
        _pm = _splash_pixmap()
        splash = QSplashScreen(_pm)
        try:
            # v1.71.1: true pill shape — the pixmap is a square, so
            # without a mask its black corners poke past the rounded
            # border (his screenshot). Clip the window itself to the
            # rounded rect; a mask failure just falls back to the
            # square splash, never breaks startup.
            _path = QPainterPath()
            _path.addRoundedRect(QRectF(0, 0, _pm.width(), _pm.height()), 10, 10)
            splash.setMask(QRegion(_path.toFillPolygon().toPolygon()))
        except Exception:
            pass
        splash.show()
        app.processEvents()
    except Exception:
        splash = None
    _dump_windows("before-MainWindow")
    store = Store()
    try:
        win = MainWindow(store)
    except Exception:
        try:
            if splash is not None: splash.close()
        except Exception: pass
        raise
    _dump_windows("after-MainWindow-before-show")
    try:
        _scr = app.primaryScreen()
        if _scr is not None:
            _geo = _scr.availableGeometry()
            win.move(_geo.center().x() - win.width() // 2, _geo.center().y() - win.height() // 2)
    except Exception:
        pass
    win.show()
    if store.get("start_maximized"):
        try: win.showMaximized()
        except Exception: pass
    try:
        if splash is not None: splash.finish(win)
    except Exception: pass
    # v1.64.0: the v1.28.8 startup window diagnostic (which wrote
    # launcher-windows.log on every launch) is removed — the flashing
    # bug it hunted was fixed in v1.28.13, so no log file is created.
    # Rich Presence idle status: show "Legacy ARK Launcher / Browsing
    # builds" as soon as the launcher opens (not only when a game
    # launches). v1.60: NOT silent anymore — if presence is ON and it
    # fails, the status bar shows the exact reason, so a broken
    # presence can never look like "it didn't work" with no clue again.
    try:
        if store.get("discord_rich_presence"):
            _ok, _reason = discord_set_idle(store.get("discord_client_id", ""))
            if not _ok:
                win.set_status(f"Discord presence failed: {_reason}")
    except Exception:
        pass
    # (original comment continues below, kept for history)
    # builds" as soon as the launcher opens (not only when a game
    # First-run Steam auto-detect: registry + Program Files locations.
    # Runs once — saves the path silently, notes it in the status bar.
    # Never touches the manual setup flow if nothing is found.
    if not (store.get("steam_path", "") or "").strip() and not store.get("steam_detected_once"):
        try:
            found = _first_run_steam_detect()
            store.set("steam_detected_once", True)
            if found:
                store.set("steam_path", found)
                win.set_status(f"Steam found at {found}")
        except Exception:
            pass
    # Startup Steam-connect overlay: modal, centered over the main
    # window. Only appears when setup is actually needed (no username
    # saved or no steamcmd/ folder). Waits for the main window's first
    # paint before popping — showing the modal mid-paint is what caused
    # the startup flash. Retries until painted so it can't get lost.
    def _show_startup_dialog():
        if not getattr(win, "_painted_once", False):
            QTimer.singleShot(250, _show_startup_dialog)
            return
        # First launch: welcome wizard explains the app before anything else.
        if not store.get("onboarding_done"):
            wiz = WelcomeWizard(win, win)
            r = win.geometry()
            wiz.move(r.center().x() - wiz.width() // 2, r.center().y() - wiz.height() // 2)
            wiz.exec()
        if not (store.get("steam_username", "") or "").strip() or not steamcmd_ready():
            dlg = SteamConnectDialog(store, win)
            r = win.geometry()
            dlg.move(r.center().x() - dlg.width() // 2, r.center().y() - dlg.height() // 2)
            dlg.exec()
    QTimer.singleShot(250, _show_startup_dialog)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()