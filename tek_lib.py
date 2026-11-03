#!/usr/bin/env python3
"""
tek_lib.py - engine-room systems ported from TEK Launcher (C#) to Python.

Port source: TEK Launcher by Nuclearistt - https://github.com/Nuclearistt/TEKLauncher
Original C# (C) 2020 Nuclearist, released under the MIT License (see
THIRD-PARTY-NOTICES.md in this repo). This module is a clean-room-style
idiomatic Python re-implementation of TEK's *non-UI* systems:

  * Utils/VDFNode.cs        -> VDF (Valve KeyValues) parser + writer
  * Steam/App.cs            -> Steam install + library detection
                               (libraryfolders.vdf / appmanifest_*.acf)
  * Servers/UdpClient.cs    -> UDP transact helper for Source queries
  * Servers/Server.cs       -> A2S_INFO / A2S_PLAYER / A2S_RULES queries
  * Servers/Info.cs         -> server/cluster extra-info model
  * Servers/Description.cs  -> server description model
  * ARK/MapCode.cs          -> MapCode enum
  * ARK/DLC.cs              -> DLC table (app/depot ids, install check)
  * ARK/Mod.cs              -> mod.info name reader + installed-mod scan
  * ARK/Game.cs             -> culture codes / standard launch params (data)

Deliberately NOT ported (see THIRD-PARTY-NOTICES.md):
  * Utils/TEKInjector.cs - DLL injection into the game/Steam process.
    Anything TEK launches through the injector is re-expressed here via
    steam:// URLs / SteamCMD depot commands, which is what the launcher
    already uses.
  * Utils/TEKSteamClient.cs - bindings for the proprietary native
    libtek-steamclient library (Steam CM downloads). The launcher uses
    Valve's official SteamCMD + the public Steam Web API instead.
  * Steam/Api.cs - raw steamclient64.dll vtable interop. Replaced by
    plain file detection (this module) and steam:// URLs.
  * TEK's launcher self-updater (teknology-hub mirrors + self-replacing
    exe). The launcher's own configurable version.json updater stays:
    it fits this repo's zip distribution, TEK's replaces a single exe.

Differences from TEK worth knowing:
  * TEK's Server.Query() *rejects* any server that is not running
    TEKWrapper or that has BattlEye enabled. This port never gates:
    vanilla servers are first-class (the GUI's Servers tab already made
    the same call for its built-in queries). SEARCHKEYWORDS_s is still
    parsed for the mod list when a server publishes it.
  * TEK's VDF parser is line-based and assumes well-formed quoting.
    This parser is a real tokenizer: it handles unquoted tokens,
    escapes, // comments and [$WIN32]-style conditional tags.
  * TEK uses one shared UDP socket for all servers; this port opens a
    short-lived socket per query (same pattern as the GUI's existing
    A2S code, and friendlier to Python threading).

Pure Python standard library only - tek_lib must never import PyQt6,
so it can be unit-tested headlessly and imported from anywhere.
"""

from __future__ import annotations

import os
import re
import socket
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

__all__ = [
    # VDF
    "VDFNode", "parse_vdf", "parse_vdf_node", "dump_vdf",
    # Steam detection
    "SteamLibrary", "AppManifest", "AppInstall", "find_steam_path",
    "get_library_folders", "parse_appmanifest", "find_app_install",
    "detect_ark_install", "ARK_APP_ID",
    # A2S
    "MapCode", "ServerInfo", "PlayerEntry", "ServerRules", "ServerStatus",
    "parse_a2s_info", "parse_a2s_players", "parse_a2s_rules",
    "a2s_info", "a2s_players", "a2s_rules", "query_server",
    "MAP_DISPLAY_NAMES", "SERVER_MAP_NAMES",
    # ARK data
    "DLC", "DLC_LIST", "dlc_for_map", "PRIMITIVE_PLUS_APP_ID",
    "PRIMITIVE_PLUS_DEPOT_ID", "InstalledMod", "read_mod_info_name",
    "read_mod_info_file", "find_installed_mods",
    "ServerDescription", "ServerExtraInfo", "validate_extra_info",
    "CULTURE_CODES", "STANDARD_LAUNCH_PARAMETERS",
    "steam_connect_url", "depot_download_command",
]

ARK_APP_ID = 346110


# =====================================================================
# VDF (Valve KeyValues) - port of Utils/VDFNode.cs
# =====================================================================

class VDFNode:
    """One node of a parsed VDF document: a key, plus either a scalar
    value (leaf) or a list of child nodes (object).

    Mirrors TEK's VDFNode: children are looked up case-insensitively
    and the first match wins (``node["path"]`` / ``node.get("path")``).
    """

    __slots__ = ("key", "value", "children")

    def __init__(self, key, value=None, children=None):
        self.key = key
        self.value = value
        self.children = children  # None for a leaf, list[VDFNode] for an object

    @property
    def is_object(self):
        return self.children is not None

    def get(self, key, default=None):
        """First child whose key matches case-insensitively (TEK semantics)."""
        if self.children:
            wanted = key.lower()
            for child in self.children:
                if child.key.lower() == wanted:
                    return child
        return default

    def __getitem__(self, key):
        child = self.get(key)
        if child is None:
            raise KeyError(key)
        return child

    def __contains__(self, key):
        return self.get(key) is not None

    def get_value(self, key, default=None):
        child = self.get(key)
        return child.value if child is not None else default

    def to_dict(self):
        """Plain-dict view. Duplicate keys collapse into a list, in
        document order (libraryfolders/appmanifests rely on this for
        repeated sections such as InstalledDepots entries)."""
        if not self.is_object:
            return self.value
        out = {}
        for child in self.children:
            val = child.to_dict()
            if child.key in out:
                prev = out[child.key]
                if isinstance(prev, list):
                    prev.append(val)
                else:
                    out[child.key] = [prev, val]
            else:
                out[child.key] = val
        return out

    def __repr__(self):
        if self.is_object:
            return f"VDFNode({self.key!r}, children={len(self.children)})"
        return f"VDFNode({self.key!r}, value={self.value!r})"


def _vdf_tokens(text):
    """Tokenize VDF text into strings and the symbols '{' / '}'.

    Handles quoted strings (with \\" and \\\\ escapes), bare unquoted
    tokens, // line comments, and skips [conditional] tags such as
    [$WIN32] that may follow a key/value pair or an object.
    """
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            nl = text.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if ch in "{}":
            tokens.append(ch)
            i += 1
            continue
        if ch == "[":
            # Conditional tag - not part of the data, skip it.
            end = text.find("]", i)
            i = n if end < 0 else end + 1
            continue
        if ch == '"':
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n and text[i + 1] in '"\\':
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append("".join(buf))
            continue
        # Bare token: runs until whitespace or a structural character.
        start = i
        while i < n and text[i] not in ' \t\r\n{}"':
            i += 1
        tokens.append(text[start:i])
    return tokens


def _vdf_parse_block(tokens, pos):
    """Parse children until '}' or end of tokens. Returns (children, pos)."""
    children = []
    while pos < len(tokens):
        tok = tokens[pos]
        if tok == "}":
            return children, pos + 1
        if tok == "{":
            # Stray brace with no key - skip defensively.
            pos += 1
            continue
        key = tok
        pos += 1
        if pos < len(tokens) and tokens[pos] == "{":
            sub, pos = _vdf_parse_block(tokens, pos + 1)
            children.append(VDFNode(key, children=sub))
        elif pos < len(tokens):
            children.append(VDFNode(key, value=tokens[pos]))
            pos += 1
        else:
            children.append(VDFNode(key, value=""))
    return children, pos


def parse_vdf_node(text):
    """Parse VDF text and return the root VDFNode (the first top-level
    key), mirroring TEK's ``new VDFNode(reader)``. Returns None for
    empty/invalid input."""
    if not text:
        return None
    if text.startswith("\ufeff"):
        text = text[1:]
    tokens = _vdf_tokens(text)
    if not tokens:
        return None
    children, _ = _vdf_parse_block(tokens, 0)
    return children[0] if children else None


def parse_vdf(text):
    """Parse VDF text into plain dicts: ``{root_key: {...}}``.

    Leaf values are strings; objects are dicts; a repeated key becomes
    a list of values in document order. Returns {} on empty input.
    """
    if not text:
        return {}
    if text.startswith("\ufeff"):
        text = text[1:]
    tokens = _vdf_tokens(text)
    children, _ = _vdf_parse_block(tokens, 0)
    root = VDFNode("", children=children)
    return root.to_dict()


def dump_vdf(node, indent_level=0):
    """Serialize a VDFNode back to VDF text, mirroring TEK's
    VDFNode.Write(): tab indentation, quoted keys/values."""
    tabs = "\t" * indent_level
    if not node.is_object:
        return f'{tabs}"{node.key}"\t\t"{node.value or ""}"\n'
    out = [f'{tabs}"{node.key}"\n{tabs}{{\n']
    for child in node.children:
        out.append(dump_vdf(child, indent_level + 1))
    out.append(f"{tabs}}}\n")
    return "".join(out)


# =====================================================================
# Steam install + library detection - port of Steam/App.cs
# (the file-based half; TEK's Steam/App also drives the native Steam
# client API for ownership - that half is NOT ported, see docstring)
# =====================================================================

@dataclass
class SteamLibrary:
    """One entry of steamapps/libraryfolders.vdf."""
    path: Path
    label: str = ""
    apps: dict = field(default_factory=dict)  # appid (str) -> size on disk (int)

    @property
    def steamapps_dir(self):
        return self.path / "steamapps"

    def appmanifest_path(self, app_id):
        return self.steamapps_dir / f"appmanifest_{app_id}.acf"

    def has_app(self, app_id):
        return str(app_id) in self.apps or self.appmanifest_path(app_id).is_file()


@dataclass
class AppManifest:
    """Parsed appmanifest_<appid>.acf (an AppState VDF document)."""
    app_id: int
    name: str = ""
    installdir: str = ""
    build_id: str = ""
    last_updated: int = 0
    size_on_disk: int = 0
    state_flags: int = 0
    installed_depots: dict = field(default_factory=dict)  # depot id (int) -> manifest id (str)
    raw: dict = field(default_factory=dict)

    @property
    def is_fully_installed(self):
        # Steam StateFlags: 4 = FullyInstalled.
        return bool(self.state_flags & 4)


@dataclass
class AppInstall:
    """A located app install: which library, its manifest, and the
    folder the game files actually live in."""
    library: SteamLibrary
    manifest: AppManifest
    manifest_path: Path

    @property
    def install_path(self):
        return self.library.steamapps_dir / "common" / self.manifest.installdir


def find_steam_path():
    """Locate the Steam installation folder, TEK-style (registry first).

    Windows: HKLM InstallPath (both registry views), then HKCU
    SteamPath. Falls back to the standard Program Files locations.
    Returns a Path, or None when Steam cannot be found. Never raises.
    """
    candidates = []
    if os.name == "nt":
        try:
            import winreg
            queries = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            ]
            for hive, sub, val in queries:
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        candidates.append(str(winreg.QueryValueEx(k, val)[0]))
                except OSError:
                    continue
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
            base = os.environ.get(env, "")
            if base:
                candidates.append(os.path.join(base, "Steam"))
        candidates += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    else:
        home = Path.home()
        candidates += [str(home / ".local" / "share" / "Steam"),
                       str(home / ".steam" / "steam")]
    for cand in candidates:
        if not cand:
            continue
        p = Path(str(cand).replace("/", os.sep) if os.name == "nt" else cand)
        try:
            if (p / "steam.exe").is_file() or (os.name != "nt" and p.is_dir()):
                return p
        except OSError:
            continue
    return None


def _coerce_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def get_library_folders(steam_path):
    """All Steam libraries for an install, from libraryfolders.vdf.

    Supports both the modern format (each library is an object with
    "path" / "apps") and the legacy format (numeric keys whose value
    is the path). The Steam install itself is always included first,
    matching how Steam treats its own folder. Never raises.
    """
    libraries = []
    seen = set()

    def _add(path_str, label="", apps=None):
        if not path_str:
            return
        p = Path(str(path_str).replace("\\\\", "\\") if os.name == "nt" else str(path_str))
        key = str(p).lower()
        if key in seen:
            return
        seen.add(key)
        libraries.append(SteamLibrary(path=p, label=label or "",
                                      apps=dict(apps or {})))

    if steam_path is None:
        return libraries
    steam_path = Path(steam_path)
    _add(str(steam_path))
    for vdf_path in (steam_path / "config" / "libraryfolders.vdf",
                     steam_path / "steamapps" / "libraryfolders.vdf"):
        try:
            if not vdf_path.is_file():
                continue
            root = parse_vdf_node(vdf_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if root is None or not root.is_object:
            continue
        for child in root.children:
            if child.is_object:
                apps = {}
                apps_node = child.get("apps")
                if apps_node is not None and apps_node.is_object:
                    for app in apps_node.children:
                        apps[app.key] = _coerce_int(app.value)
                _add(child.get_value("path"), child.get_value("label", ""), apps)
            elif child.value:
                # Legacy format: "1"  "D:\\SteamLibrary"
                _add(child.value)
    return libraries


def parse_appmanifest(manifest_path):
    """Parse one appmanifest_*.acf into an AppManifest, or None."""
    try:
        text = Path(manifest_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    root = parse_vdf_node(text)
    if root is None or not root.is_object:
        return None
    depots = {}
    depots_node = root.get("InstalledDepots")
    if depots_node is not None and depots_node.is_object:
        for depot in depots_node.children:
            manifest_id = depot.get_value("manifest", "") if depot.is_object else ""
            depots[_coerce_int(depot.key, -1)] = str(manifest_id)
        depots.pop(-1, None)
    return AppManifest(
        app_id=_coerce_int(root.get_value("appid")),
        name=root.get_value("name", "") or "",
        installdir=root.get_value("installdir", "") or "",
        build_id=str(root.get_value("buildid", "") or ""),
        last_updated=_coerce_int(root.get_value("LastUpdated")),
        size_on_disk=_coerce_int(root.get_value("SizeOnDisk")),
        state_flags=_coerce_int(root.get_value("StateFlags")),
        installed_depots=depots,
        raw=root.to_dict(),
    )


def find_app_install(app_id=ARK_APP_ID, steam_path=None):
    """Find an installed Steam app across all libraries (TEK looks up
    ARK 346110 this way in Steam/App.UpdateUserStatus). Returns an
    AppInstall, or None when the app is not installed via Steam."""
    if steam_path is None:
        steam_path = find_steam_path()
    if steam_path is None:
        return None
    for library in get_library_folders(steam_path):
        manifest_path = library.appmanifest_path(app_id)
        if manifest_path.is_file():
            manifest = parse_appmanifest(manifest_path)
            if manifest is not None:
                return AppInstall(library=library, manifest=manifest,
                                  manifest_path=manifest_path)
    return None


def detect_ark_install(steam_path=None):
    """One-call summary for the GUI: Steam path, libraries, and the
    Steam-installed ARK (app 346110) with the DLC depots it carries.

    Returns a dict:
      {steam_path, libraries: [SteamLibrary], install: AppInstall|None,
       dlc_depots: {launcher_key: depot_id}} - dlc_depots only lists
       TEK-table DLCs whose depot appears in the ARK manifest's
       InstalledDepots. Note this describes the *Steam* install of
       current ARK; the launcher's own per-build CML-ARK folders are a
       separate mechanism and are not reported here.
    """
    if steam_path is None:
        steam_path = find_steam_path()
    out = {"steam_path": steam_path, "libraries": [], "install": None,
           "dlc_depots": {}}
    if steam_path is None:
        return out
    out["libraries"] = get_library_folders(steam_path)
    install = find_app_install(ARK_APP_ID, steam_path)
    out["install"] = install
    if install is not None:
        present = {}
        for dlc in DLC_LIST:
            if dlc.depot_id in install.manifest.installed_depots:
                present[dlc.launcher_key] = dlc.depot_id
        out["dlc_depots"] = present
    return out


# =====================================================================
# ARK data models - ports of ARK/MapCode.cs, ARK/DLC.cs, ARK/Mod.cs,
# ARK/Game.cs (data tables), Servers/Info.cs, Servers/Description.cs
# =====================================================================

class MapCode(IntEnum):
    """ARK maps, in TEK's MapCode order (the order matters: TEK's
    DLC.Get() does arithmetic on it)."""
    TheIsland = 0
    TheCenter = 1
    ScorchedEarth = 2
    Ragnarok = 3
    Aberration = 4
    Extinction = 5
    Valguero = 6
    Genesis = 7
    CrystalIsles = 8
    Genesis2 = 9
    LostIsland = 10
    Fjordur = 11
    Aquatica = 12
    Mod = 13


# Raw map strings an ARK server can report in A2S_INFO -> MapCode
# (TEK Server.cs s_mapNames, same order as the enum minus TheIsland's
# slot handling there; "Abyss" is Aquatica's internal name).
SERVER_MAP_NAMES = {
    "TheIsland": MapCode.TheIsland,
    "TheCenter": MapCode.TheCenter,
    "ScorchedEarth": MapCode.ScorchedEarth,
    "Ragnarok": MapCode.Ragnarok,
    "Aberration": MapCode.Aberration,
    "Extinction": MapCode.Extinction,
    "Valguero_P": MapCode.Valguero,
    "Genesis": MapCode.Genesis,
    "CrystalIsles": MapCode.CrystalIsles,
    "Gen2": MapCode.Genesis2,
    "LostIsland": MapCode.LostIsland,
    "Fjordur": MapCode.Fjordur,
    "Abyss": MapCode.Aquatica,
}

MAP_DISPLAY_NAMES = {
    MapCode.TheIsland: "The Island",
    MapCode.TheCenter: "The Center",
    MapCode.ScorchedEarth: "Scorched Earth",
    MapCode.Ragnarok: "Ragnarok",
    MapCode.Aberration: "Aberration",
    MapCode.Extinction: "Extinction",
    MapCode.Valguero: "Valguero",
    MapCode.Genesis: "Genesis Part 1",
    MapCode.CrystalIsles: "Crystal Isles",
    MapCode.Genesis2: "Genesis Part 2",
    MapCode.LostIsland: "Lost Island",
    MapCode.Fjordur: "Fjordur",
    MapCode.Aquatica: "Aquatica",
    MapCode.Mod: "Mod map",
}


@dataclass(frozen=True)
class DLC:
    """One row of TEK's ARK/DLC.cs table, plus the launcher's
    versions.json key for the same DLC."""
    name: str
    app_id: int
    depot_id: int
    is_mod_folder: bool   # True: content lives under Content/Mods, else Content/Maps
    has_p_suffix: bool    # True: the .umap file name ends in _P
    launcher_key: str     # key used by versions.json / DEPOT_MAP in the GUI

    @property
    def folder_name(self):
        # TEK DLC.cs depot switch.
        if self.depot_id == 473857:
            return "Genesis"
        if self.depot_id == 1887561:
            return "FjordurOfficial"
        if self.depot_id == 3537070:
            return "Abyss"
        return self.name.replace(" ", "")

    @property
    def map_code(self):
        if self.depot_id == 1887561:
            return MapCode.Fjordur
        if self.depot_id == 3537070:
            return MapCode.Aquatica
        return MapCode[self.folder_name]

    @property
    def umap_name(self):
        if self.depot_id == 1887561:
            base = "Fjordur"
        elif self.depot_id == 3537070:
            base = "Aquatica"
        else:
            base = self.map_code.name
        return base + ("_P" if self.has_p_suffix else "") + ".umap"

    def content_dir(self, game_path):
        kind = "Mods" if self.is_mod_folder else "Maps"
        return Path(game_path) / "ShooterGame" / "Content" / kind / self.folder_name

    def umap_path(self, game_path):
        return self.content_dir(game_path) / self.umap_name

    def is_installed(self, game_path):
        """TEK DLC.IsInstalled: the DLC's .umap exists (Genesis counts
        as installed when either of its two maps is present)."""
        try:
            if self.umap_path(game_path).is_file():
                return True
            if self.map_code == MapCode.Genesis:
                gen2 = (Path(game_path) / "ShooterGame" / "Content" / "Maps"
                        / "Genesis2" / "Gen2.umap")
                return gen2.is_file()
        except OSError:
            pass
        return False


# TEK ARK/DLC.cs List, verbatim (name, app id, depot id, isMod, has_P),
# with the launcher's versions.json key appended per row.
DLC_LIST = [
    DLC("The Center",        473850,  346114, True,  False, "center"),
    DLC("Scorched Earth",    512540,  375351, False, True,  "scorched"),
    DLC("Ragnarok",          642250,  375354, True,  False, "ragnarok"),
    DLC("Aberration",        708770,  375357, False, True,  "aberration"),
    DLC("Extinction",        887380,  473851, False, False, "extinction"),
    DLC("Valguero",          1100810, 473854, True,  True,  "valguero"),
    DLC("Genesis Part 1 & 2", 1113410, 473857, False, False, "genesis"),
    DLC("Crystal Isles",     1270830, 1318685, True,  False, "crystal_isles"),
    DLC("Lost Island",       1691800, 1691801, True,  False, "lost_island"),
    DLC("Fjordur",           1887560, 1887561, True,  False, "fjordur"),
    DLC("Aquatica",          3537070, 3537070, False, False, "aquatica"),
]

# Primitive+ is a total conversion, not a map DLC, so TEK's DLC table
# omits it; the launcher's versions.json carries it, so its ids live
# here for completeness.
PRIMITIVE_PLUS_APP_ID = 508150
PRIMITIVE_PLUS_DEPOT_ID = 346117


def dlc_for_map(code):
    """TEK DLC.Get(): the DLC that provides a map. Genesis2 resolves
    to the Genesis row (one depot carries both maps)."""
    code = MapCode(code)
    if code == MapCode.Genesis2:
        return DLC_LIST[6]
    index = int(code) - 1
    if code > MapCode.Genesis2:
        index -= 1
    if index < 0 or index >= len(DLC_LIST):
        raise ValueError(f"no DLC provides map {code!r}")
    return DLC_LIST[index]


def read_mod_info_name(data):
    """Extract a mod's internal name from mod.info bytes (ARK/Mod.cs):
    a little-endian int32 string length (including the NUL terminator)
    followed by the UTF-8 name. Returns "" for empty/malformed data."""
    if not data or len(data) < 4:
        return ""
    size = struct.unpack_from("<i", data, 0)[0]
    if size <= 1:
        return ""
    return data[4:4 + size - 1].decode("utf-8", "replace")


def read_mod_info_file(mod_info_path):
    try:
        return read_mod_info_name(Path(mod_info_path).read_bytes())
    except OSError:
        return ""


@dataclass
class InstalledMod:
    """An installed Workshop mod, TEK ARK/Mod.cs layout."""
    mod_id: int
    name: str = ""
    compressed_dir: Path = None   # <game>/Mods/<id> (workshop content)
    mods_dir: Path = None         # <game>/ShooterGame/Content/Mods/<id>
    mod_file: Path = None         # <game>/ShooterGame/Content/Mods/<id>.mod


def find_installed_mods(game_path):
    """Scan <game>/Mods for numeric Workshop folders and read each
    mod.info name (TEK Mod.InitializeList's discovery half; the Steam
    detail/update lookups stay with the GUI's existing Web-API code)."""
    base = Path(game_path) / "Mods"
    out = []
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return out
    for entry in entries:
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        mod_id = int(entry.name)
        mods_dir = (Path(game_path) / "ShooterGame" / "Content" / "Mods"
                    / entry.name)
        out.append(InstalledMod(
            mod_id=mod_id,
            name=read_mod_info_file(entry / "mod.info"),
            compressed_dir=entry,
            mods_dir=mods_dir,
            mod_file=Path(str(mods_dir) + ".mod"),
        ))
    return out


@dataclass
class ServerDescription:
    """Servers/Description.cs: rates + free-text lines for a server
    or cluster info file."""
    max_dino_lvl: int = None
    taming: float = None
    experience: float = None
    harvesting: float = None
    breeding: float = None
    stacks: float = None
    other: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        def pick(*keys):
            for k in keys:
                if k in data:
                    return data[k]
            return None
        other = pick("Other", "other") or []
        return cls(
            max_dino_lvl=pick("MaxDinoLvl", "max_dino_lvl"),
            taming=pick("Taming", "taming"),
            experience=pick("Experience", "experience"),
            harvesting=pick("Harvesting", "harvesting"),
            breeding=pick("Breeding", "breeding"),
            stacks=pick("Stacks", "stacks"),
            other=list(other) if isinstance(other, (list, tuple)) else [],
        )


@dataclass
class ServerExtraInfo:
    """Servers/Info.cs: the optional info-file a server/cluster owner
    can publish (TEK fetches its URL from SEARCHKEYWORDS_s)."""
    hoster_name: str = None
    server_name: str = None
    cluster_name: str = None
    icon_url: str = None
    discord: str = None
    server_description: ServerDescription = None
    cluster_description: ServerDescription = None

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        def pick(*keys):
            for k in keys:
                if k in data:
                    return data[k]
            return None
        return cls(
            hoster_name=pick("HosterName", "hoster_name"),
            server_name=pick("ServerName", "server_name"),
            cluster_name=pick("ClusterName", "cluster_name"),
            icon_url=pick("IconUrl", "icon_url"),
            discord=pick("Discord", "discord"),
            server_description=ServerDescription.from_dict(
                pick("ServerDescription", "server_description")),
            cluster_description=ServerDescription.from_dict(
                pick("ClusterDescription", "cluster_description")),
        )


def validate_extra_info(info):
    """TEK Server.Query()'s acceptance rules for an info file, as a
    list of problems ([] = acceptable): a Discord link must be a real
    discord.gg invite URL, and each description may carry at most 6
    free-text lines."""
    problems = []
    if info is None:
        return ["no info"]
    if info.discord is not None and not str(info.discord).startswith("https://discord.gg/"):
        problems.append("discord is not a discord.gg invite URL")
    for label, desc in (("server", info.server_description),
                        ("cluster", info.cluster_description)):
        if desc is not None and len(desc.other or []) > 6:
            problems.append(f"{label} description has more than 6 lines")
    return problems


# ARK/Game.cs data tables (the launch *mechanism* in TEK is the
# injector - not ported; these are just the data it carried).
CULTURE_CODES = ["ca", "cs", "da", "de", "en", "es", "eu", "fi", "fr",
                 "hu", "it", "ja", "ka", "ko", "nl", "pl", "pt_BR", "ru",
                 "sv", "th", "tr", "uk", "zh", "zh-Hans-CN", "zh-TW"]
STANDARD_LAUNCH_PARAMETERS = ["-d3d10", "-nosplash", "-nomansky",
                              "-nomemorybias", "-lowmemory", "-norhithread",
                              "-novsync", "-preventhibernation"]


def steam_connect_url(host, game_port):
    """steam://connect URL - the legitimate re-expression of TEK's
    'join this server' action (no injector involved)."""
    return f"steam://connect/{host}:{int(game_port)}"


def depot_download_command(app_id, depot_id, manifest_id,
                           install_dir, steamcmd="steamcmd"):
    """A SteamCMD depot-download command line (Valve's official CLI) -
    the legitimate re-expression of TEK Steam Client download jobs."""
    return (f"{steamcmd} +login anonymous +download_depot "
            f"{int(app_id)} {int(depot_id)} {manifest_id} "
            f"+quit  # target dir: {install_dir}")


# =====================================================================
# A2S server queries - ports of Servers/UdpClient.cs + Servers/Server.cs
# (Source engine query protocol: A2S_INFO 0x54, A2S_PLAYER 0x55,
#  A2S_RULES 0x56, challenge reply 0x41)
# =====================================================================

_A2S_HEADER = b"\xff\xff\xff\xff"
_A2S_SPLIT_HEADER = b"\xff\xff\xff\xfe"
_A2S_INFO_REQUEST = _A2S_HEADER + b"\x54Source Engine Query\x00"
# GoldSource-style split packets carry a 2-byte size after the part
# number; Source packets may not. Both layouts seen in the wild are
# handled by _reassemble, same as the GUI's existing A2S code.


@dataclass
class ServerInfo:
    """Parsed A2S_INFO response (Servers/Server.cs Query, INFO half)."""
    name: str = ""
    version: str = ""
    map_raw: str = ""
    map_code: MapCode = MapCode.Mod
    map_display: str = ""
    folder: str = ""
    game: str = ""
    app_id: int = 0
    protocol: int = 0
    players: int = 0
    max_players: int = 0
    bots: int = 0
    server_type: str = ""
    environment: str = ""
    passworded: bool = False
    vac_secured: bool = False
    ping_ms: float = None
    host: str = ""
    query_port: int = 0

    @property
    def address(self):
        return f"{self.host}:{self.query_port}"


@dataclass
class PlayerEntry:
    """One row of an A2S_PLAYER response."""
    index: int
    name: str
    score: int
    duration_seconds: float

    @property
    def duration_str(self):
        total = int(self.duration_seconds)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class ServerRules(dict):
    """A2S_RULES as a dict, with typed views of the ARK rules TEK's
    Server.Query() reads. Unlike TEK, nothing here rejects a server:
    missing/odd rules just yield None."""

    @property
    def cluster_id(self):
        return self.get("ClusterId_s") or None

    @property
    def is_pve(self):
        val = self.get("SESSIONISPVE_i")
        if val == "1":
            return True
        if val == "0":
            return False
        return None

    @property
    def open_slots(self):
        try:
            return int(self.get("NUMOPENPUBCONN", ""))
        except (TypeError, ValueError):
            return None

    def player_count(self, max_players):
        """True player count: ARK's INFO player field is unreliable,
        NUMOPENPUBCONN (open public slots) is authoritative."""
        open_slots = self.open_slots
        if open_slots is None or max_players is None:
            return None
        return max(0, max_players - open_slots)

    @property
    def uses_battleye(self):
        val = self.get("SERVERUSESBATTLEYE_b")
        if val == "true":
            return True
        if val == "false":
            return False
        return None

    @property
    def mod_ids(self):
        """Workshop ids from SEARCHKEYWORDS_s, when published. TEK's
        layout: 'TEKWrapper <mods> <info-url>', where <mods> is either
        a comma-separated list in one token or - due to a TEKWrapper
        quirk - comma-and-space separated across several tokens.
        Non-TEKWrapper servers simply yield []."""
        raw = self.get("SEARCHKEYWORDS_s")
        if not raw:
            return []
        tokens = raw.split()
        if len(tokens) < 3 or tokens[0] != "TEKWrapper":
            return []
        ids = []
        try:
            if len(tokens) > 3:
                for tok in tokens[1:-1]:
                    ids.append(int(tok.rstrip(",")))
            elif tokens[1] != "0":
                ids = [int(x) for x in tokens[1].split(",") if x]
        except ValueError:
            return []
        return ids

    @property
    def info_file_url(self):
        raw = self.get("SEARCHKEYWORDS_s")
        if not raw:
            return None
        tokens = raw.split()
        if not tokens or tokens[0] != "TEKWrapper":
            return None
        if len(tokens) > 3:
            # Spread layout: the URL, when present, is the last token.
            return tokens[-1] if tokens[-1].startswith("http") else None
        if len(tokens) == 3 and tokens[2] != "0":
            return tokens[2]
        return None


@dataclass
class ServerStatus:
    """Everything one query round-trip learned about a server."""
    info: ServerInfo = None
    rules: ServerRules = None
    players: list = None

    @property
    def online(self):
        return self.info is not None

    @property
    def player_count(self):
        if self.rules is not None and self.info is not None:
            counted = self.rules.player_count(self.info.max_players)
            if counted is not None:
                return counted
        return self.info.players if self.info is not None else 0


def _read_cstr(buf, pos):
    end = buf.find(b"\x00", pos)
    if end < 0:
        return "", len(buf)
    return buf[pos:end].decode("utf-8", "replace"), end + 1


def parse_a2s_info(buf):
    """Parse an A2S_INFO response payload (after any reassembly).
    Returns a ServerInfo, or None when the packet is not a valid
    ARK/Source INFO reply. TEK additionally requires the folder to be
    'ark_survival_evolved'; that check is left to callers via
    ServerInfo.folder so the parser stays reusable."""
    try:
        if len(buf) < 6 or buf[:4] != _A2S_HEADER or buf[4] != 0x49:
            return None
        pos = 5
        protocol = buf[pos]
        pos += 1
        name, pos = _read_cstr(buf, pos)
        map_raw, pos = _read_cstr(buf, pos)
        folder, pos = _read_cstr(buf, pos)
        game, pos = _read_cstr(buf, pos)
        if pos + 9 > len(buf):
            return None
        app_id = struct.unpack_from("<H", buf, pos)[0]
        pos += 2
        players, max_players, bots = buf[pos], buf[pos + 1], buf[pos + 2]
        server_type = chr(buf[pos + 3])
        environment = chr(buf[pos + 4])
        passworded = buf[pos + 5] != 0
        vac_secured = buf[pos + 6] != 0
        pos += 7
        version, pos = _read_cstr(buf, pos)
        # ARK folds its build into the server name: "Name - (v123.4)".
        if " - (v" in name:
            base, ver = name.rsplit(" - (v", 1)
            version = ver.rstrip(")")
            name = base
        map_code = SERVER_MAP_NAMES.get(map_raw, MapCode.Mod)
        display = MAP_DISPLAY_NAMES.get(map_code, map_raw)
        if map_code == MapCode.Mod:
            display = map_raw
        return ServerInfo(
            name=name, version=version, map_raw=map_raw,
            map_code=map_code, map_display=display, folder=folder,
            game=game, app_id=app_id, protocol=protocol,
            players=players, max_players=max_players, bots=bots,
            server_type=server_type, environment=environment,
            passworded=passworded, vac_secured=vac_secured)
    except (IndexError, struct.error):
        return None


def parse_a2s_players(buf):
    """Parse an A2S_PLAYER response payload into [PlayerEntry]."""
    try:
        if len(buf) < 6 or buf[:4] != _A2S_HEADER or buf[4] != 0x44:
            return None
        count = buf[5]
        pos = 6
        out = []
        for _ in range(count):
            if pos >= len(buf):
                break
            index = buf[pos]
            pos += 1
            name, pos = _read_cstr(buf, pos)
            if pos + 8 > len(buf):
                break
            score = struct.unpack_from("<i", buf, pos)[0]
            duration = struct.unpack_from("<f", buf, pos + 4)[0]
            pos += 8
            out.append(PlayerEntry(index=index, name=name, score=score,
                                   duration_seconds=duration))
        return out
    except (IndexError, struct.error):
        return None


def parse_a2s_rules(buf):
    """Parse an A2S_RULES response payload into a ServerRules dict."""
    try:
        if len(buf) < 7 or buf[:4] != _A2S_HEADER or buf[4] != 0x45:
            return None
        count = struct.unpack_from("<h", buf, 5)[0]
        out = ServerRules()
        pos = 7
        for _ in range(max(0, count)):
            name, pos = _read_cstr(buf, pos)
            if pos >= len(buf):
                break
            value, pos = _read_cstr(buf, pos)
            if name:
                out[name] = value
        return out
    except (IndexError, struct.error):
        return None


def _reassemble(sock, first):
    """Reassemble a split (0xFFFFFFFE) response. `first` is the first
    fragment already received; further fragments are read from sock.
    Returns the joined payload, or None if fragments are incomplete."""
    parts = {}
    total = None
    buf = first
    while buf is not None:
        if len(buf) < 10 or buf[:4] != _A2S_SPLIT_HEADER:
            break
        total = buf[8]
        num = buf[9]
        rest = buf[10:]
        if len(rest) >= 2:
            size = struct.unpack_from("<H", rest, 0)[0]
            if size == len(rest) - 2:
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
    return b"".join(parts[i] for i in sorted(parts))


def _a2s_transact(ip, port, request, timeout):
    """Send one query datagram and return the (reassembled) response,
    or None. Handles the 0x41 challenge reply by resending with the
    challenge appended - the caller builds `request` so that appending
    4 bytes is correct for its query type. Mirrors TEK UdpClient.
    Transact (2000 ms there; the timeout parameter here)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(request, (ip, int(port)))
        data, _addr = sock.recvfrom(4096)
        if len(data) == 9 and data[:4] == _A2S_HEADER and data[4] == 0x41:
            sock.sendto(request + data[5:9], (ip, int(port)))
            data, _addr = sock.recvfrom(4096)
        if data[:4] == _A2S_SPLIT_HEADER:
            return _reassemble(sock, data)
        return data
    except OSError:
        return None
    finally:
        sock.close()


def _resolve(host):
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def a2s_info(host, query_port, timeout=2.0):
    """One A2S_INFO query. Returns ServerInfo (with ping_ms and the
    queried address filled in), or None if the server did not answer."""
    ip = _resolve(host)
    if ip is None:
        return None
    started = time.perf_counter()
    data = _a2s_transact(ip, query_port, _A2S_INFO_REQUEST, timeout)
    if data is None:
        return None
    info = parse_a2s_info(data)
    if info is None:
        return None
    info.ping_ms = (time.perf_counter() - started) * 1000.0
    info.host = host
    info.query_port = int(query_port)
    return info


def a2s_players(host, query_port, timeout=2.0):
    """One A2S_PLAYER query: [{PlayerEntry}] or None. The request is
    built so the generic challenge resend in _a2s_transact produces
    the correct packet (header + 0x55 + challenge)."""
    ip = _resolve(host)
    if ip is None:
        return None
    request = _A2S_HEADER + b"\x55\xff\xff\xff\xff"
    data = _a2s_transact(ip, query_port, request, timeout)
    if data is None:
        return None
    return parse_a2s_players(data)


def a2s_rules(host, query_port, timeout=2.0):
    """One A2S_RULES query: ServerRules or None."""
    ip = _resolve(host)
    if ip is None:
        return None
    request = _A2S_HEADER + b"\x56\xff\xff\xff\xff"
    data = _a2s_transact(ip, query_port, request, timeout)
    if data is None:
        return None
    return parse_a2s_rules(data)


def query_server(host, query_port, timeout=2.0, with_players=False):
    """Full status for one server: INFO (+ RULES, + PLAYER list when
    asked). Rules/players are only fetched when INFO answered, like
    TEK's Server.Query(). Returns a ServerStatus (info=None = offline
    or unreachable)."""
    info = a2s_info(host, query_port, timeout=timeout)
    if info is None:
        return ServerStatus(info=None, rules=None, players=None)
    rules = a2s_rules(host, query_port, timeout=timeout)
    players = a2s_players(host, query_port, timeout=timeout) if with_players else None
    return ServerStatus(info=info, rules=rules, players=players)
