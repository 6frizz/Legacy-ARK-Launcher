#!/usr/bin/env python3
"""
tek_steamclient.py - Python ctypes bindings for libtek-steamclient-2.dll,
ported from TEK Launcher's src/Utils/TEKSteamClient.cs (410 lines of
P/Invoke declarations against the native tek-steamclient library).

Port source: TEK Launcher by Nuclearistt -
https://github.com/Nuclearistt/TEKLauncher - (C) 2020 Nuclearist, MIT
License (see THIRD-PARTY-NOTICES.md). The native library itself is
TEK's, also MIT, and is NOT bundled with this repo: on first use it is
downloaded from TEK's official release CDN (the same URLs TEK's own
MainWindow uses) into the launcher's data folder.

What the library provides (tek_sc_*):
  * CM client: connect + ANONYMOUS sign-in to Steam's CM network, and
    Workshop queries (tek_sc_cm_ws_get_details / _query_items). This
    is the only sign-in the C# bindings declare - there is no password
    or token API in the binding layer, so nothing in this module ever
    touches a credential. That matches the launcher's standing rule:
    it never asks for, stores, or passes a Steam password.
  * App manager: depot download/update jobs (tek_sc_am_*) against the
    library's own state directory. These are ported as tested
    prototypes (full signatures + wrappers) but are NOT wired into the
    GUI in this version - the launcher's SteamCMD download flow stays
    the shipping path.
  * S3 manifest sync + delta disk-space estimation helpers.

Explicitly NOT here, by design: libtek-injector.dll (tek_inj_run_game,
process injection) and libtek-game-runtime.dll (injected Steamworks
emulation). No bindings, no downloads, no code paths for either.

Windows-only and lazy: importing this module never loads the DLL and
never raises on any platform. Every entry point fails soft with
LibraryUnavailable / TekSteamClientError carrying a human-readable
reason, so the GUI can show *why* TEK CM features are unavailable
instead of crashing.
"""

from __future__ import annotations

import ctypes
import os
import threading
import urllib.request
from dataclasses import dataclass
from enum import IntEnum, IntFlag
from pathlib import Path

__all__ = [
    "DLL_NAME", "DLL_URLS", "LibraryUnavailable", "TekSteamClientError",
    "Error", "ErrorMessages", "ItemId", "CmWsItemDetails", "CmDataWs",
    "AmItemStatus", "AmJobStage", "AmJobState", "AmPatchStatus",
    "AmUpdType", "AmJobDesc", "AmItemDesc", "TekError", "ModDetails",
    "ensure_dll", "availability", "SteamClientLibrary", "LibCtx",
    "CmClient", "AppManager", "workshop_details", "workshop_query",
]

DLL_NAME = "libtek-steamclient-2.dll"
# TEK's official release mirrors (TEK MainWindow.xaml.cs downloads the
# steamclient DLL from exactly these two URLs, in this order).
DLL_URLS = [
    "https://teknology-hub.com/software/tek-steamclient/releases/latest-2/win-x86_64-static/libtek-steamclient-2.dll",
    "https://de.teknology-hub.com/software/tek-steamclient/releases/latest-2/win-x86_64-static/libtek-steamclient-2.dll",
]

_USER_AGENT = "LegacyARKLauncher/1.0 (tek-steamclient bindings)"


class LibraryUnavailable(Exception):
    """The native library cannot be used (wrong platform, not
    downloaded yet, or failed to load). Carries the human reason."""


class TekSteamClientError(Exception):
    """The native library was reached but reported/failed an operation."""


# =====================================================================
# Native structures - StructLayout(LayoutKind.Sequential) in C#.
# The ctypes layouts below are size-checked against the C# layouts in
# tests/test_tek_steamclient.py (64-bit): Error 24, ErrorMessages 48,
# ItemId 16, CmWsItemDetails 80, CmDataWs 56, AmJobDesc 56,
# AmItemDesc 104 bytes.
# =====================================================================

class Error(ctypes.Structure):
    """tek_sc Error: (Type, Primary, Auxiliary, Extra, Uri).
    Success <=> Primary == 0."""
    _fields_ = [
        ("Type", ctypes.c_int32),
        ("Primary", ctypes.c_int32),
        ("Auxiliary", ctypes.c_int32),
        ("Extra", ctypes.c_int32),
        ("Uri", ctypes.c_void_p),
    ]

    @property
    def success(self):
        return self.Primary == 0


class ErrorMessages(ctypes.Structure):
    _fields_ = [
        ("Type", ctypes.c_int32),
        ("TypeStr", ctypes.c_void_p),
        ("Primary", ctypes.c_void_p),
        ("Auxiliary", ctypes.c_void_p),
        ("Extra", ctypes.c_void_p),
        ("UriType", ctypes.c_void_p),
    ]


class ItemId(ctypes.Structure):
    _fields_ = [
        ("AppId", ctypes.c_uint32),
        ("DepotId", ctypes.c_uint32),
        ("WorkshopItemId", ctypes.c_uint64),
    ]


class CmWsItemDetails(ctypes.Structure):
    _fields_ = [
        ("Id", ctypes.c_uint64),
        ("ManifestId", ctypes.c_uint64),
        ("LastUpdated", ctypes.c_int64),
        ("Name", ctypes.c_void_p),
        ("PreviewUrl", ctypes.c_void_p),
        ("Children", ctypes.c_void_p),
        ("NumChildren", ctypes.c_int32),
        ("AppId", ctypes.c_uint32),
        ("Result", Error),
    ]


class CmDataWs(ctypes.Structure):
    _fields_ = [
        ("Details", ctypes.POINTER(CmWsItemDetails)),
        ("NumDetails", ctypes.c_int32),
        ("NumReturnedDetails", ctypes.c_int32),
        ("TotalItems", ctypes.c_int32),
        ("Result", Error),
        ("Event", ctypes.c_void_p),
    ]


class AmItemStatus(IntFlag):
    Job = 1 << 0
    UpdAvailable = 1 << 1


class AmJobStage(IntEnum):
    FetchingData = 0
    DwManifest = 1
    DwPatch = 2
    Verifying = 3
    Downloading = 4
    Pathcing = 5  # (sic) - TEK's own spelling in the C# enum
    Installing = 6
    Deleting = 7
    Finalizing = 8


class AmJobState(IntEnum):
    Stopped = 0
    Running = 1
    PausePending = 2


class AmPatchStatus(IntEnum):
    Unknown = 0
    Unused = 1
    Used = 2


class AmUpdType(IntFlag):
    State = 1 << 0
    Stage = 1 << 1
    Progress = 1 << 2
    DeltaCreated = 1 << 3


class AmJobDesc(ctypes.Structure):
    _fields_ = [
        ("State", ctypes.c_int32),
        ("Stage", ctypes.c_int32),
        ("ProgressCurrent", ctypes.c_int64),
        ("ProgressTotal", ctypes.c_int64),
        ("SourceManifestId", ctypes.c_uint64),
        ("TargetManifestId", ctypes.c_uint64),
        ("PatchStatus", ctypes.c_int32),
        ("Delta", ctypes.c_void_p),
    ]


class AmItemDesc(ctypes.Structure):
    _fields_ = [
        ("Next", ctypes.c_void_p),  # AmItemDesc* in C#
        ("Id", ItemId),
        ("Status", ctypes.c_int32),
        ("CurrentManifestId", ctypes.c_uint64),
        ("LatestManifestId", ctypes.c_uint64),
        ("Job", AmJobDesc),
    ]


# CmCallbackFunc in C#: void (nint client, void* data, void* userData)
CM_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_void_p)
# AmJobUpdFunc in C#: void (ref AmItemDesc desc, AmUpdType upd_mask)
AM_JOB_UPD = ctypes.CFUNCTYPE(None, ctypes.POINTER(AmItemDesc),
                              ctypes.c_int32)


def _read_utf8(ptr):
    if not ptr:
        return ""
    try:
        return ctypes.string_at(ptr).decode("utf-8", "replace")
    except (ValueError, UnicodeDecodeError):
        return ""


class TekError:
    """Python wrapper for the native Error struct, mirroring the C#
    Error.Message / Error.AuxMessage formatting (which resolves the
    numeric codes through tek_sc_err_get_msgs)."""

    def __init__(self, native, error):
        self._native = native  # _Native or None (message stays numeric)
        self.error = error
        self.type = error.Type
        self.primary = error.Primary
        self.auxiliary = error.Auxiliary
        self.extra = error.Extra

    @property
    def success(self):
        return self.primary == 0

    def _messages(self):
        if self._native is None:
            return None
        msgs = self._native.err_get_msgs(ctypes.byref(self.error))
        try:
            return {
                "type_str": _read_utf8(msgs.TypeStr),
                "primary": _read_utf8(msgs.Primary),
                "auxiliary": _read_utf8(msgs.Auxiliary),
                "extra": _read_utf8(msgs.Extra),
                "uri_type": _read_utf8(msgs.UriType),
                "uri": _read_utf8(self.error.Uri),
            }
        finally:
            self._native.err_release_msgs(ctypes.byref(msgs))

    @property
    def message(self):
        msgs = self._messages()
        if msgs is None:
            return (f"tek-steamclient error (type {self.type}, "
                    f"primary {self.primary}, auxiliary {self.auxiliary})")
        msg = (f"An error has occurred\nType: ({self.type}) {msgs['type_str']}\n"
               f"Primary message: ({self.primary}) {msgs['primary']}")
        if msgs["auxiliary"]:
            msg += f"\nAuxiliary message: ({self.auxiliary}) {msgs['auxiliary']}"
        if msgs["extra"]:
            msg += f"\n{msgs['extra']}"
        if self.error.Uri:
            msg += f"\n{msgs['uri_type']}: {msgs['uri']}"
        return msg

    @property
    def aux_message(self):
        msgs = self._messages()
        if msgs is None:
            return f"error {self.primary}/{self.auxiliary}"
        if not msgs["auxiliary"]:
            msg = msgs["primary"]
        else:
            msg = f"({self.auxiliary}) {msgs['auxiliary']}"
        if msgs["extra"]:
            msg += f" ({msgs['extra']})"
        return msg

    def __repr__(self):
        return (f"TekError(success={self.success}, type={self.type}, "
                f"primary={self.primary}, auxiliary={self.auxiliary})")


@dataclass
class ModDetails:
    """ARK/Mod.cs ModDetails record, Python-shaped (LastUpdated kept
    as Unix seconds instead of .NET ticks)."""
    app_id: int
    status: int          # 1 ok, 2 deleted/private (aux 9), 0 other failure
    last_updated: int    # Unix epoch seconds
    mod_id: int
    manifest_id: int
    name: str
    preview_url: str


# =====================================================================
# DLL acquisition + loading
# =====================================================================

def ensure_dll(dest_dir, timeout=60):
    """Make sure libtek-steamclient-2.dll exists in dest_dir,
    downloading it from TEK's official mirrors if not (TEK does the
    same on startup). Returns the DLL Path. Raises LibraryUnavailable
    with the per-mirror reasons when every download fails."""
    dest = Path(dest_dir) / DLL_NAME
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    errors = []
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise LibraryUnavailable(f"cannot create {dest.parent}: {e}")
    for url in DLL_URLS:
        tmp = dest.with_suffix(".dll.part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp, \
                    open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
            if tmp.stat().st_size == 0:
                raise OSError("empty download")
            tmp.replace(dest)
            return dest
        except Exception as e:  # noqa: BLE001 - collect and try next mirror
            errors.append(f"{url}: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    raise LibraryUnavailable(
        "could not download libtek-steamclient-2.dll - " + "; ".join(errors))


def availability(dll_path=None):
    """(usable, reason) probe that never raises and never loads the
    DLL: platform + presence checks only."""
    if os.name != "nt":
        return False, "TEK Steam Client features need Windows (native DLL)."
    if dll_path is not None and not Path(dll_path).is_file():
        return False, f"{DLL_NAME} is not downloaded yet."
    return True, ""


class _Native:
    """The loaded DLL with every tek_sc_* prototype declared, in the
    same order as TEKSteamClient.cs's Native Functions region."""

    def __init__(self, dll_path):
        self._dll = ctypes.CDLL(str(dll_path))
        d = self._dll
        vp, i32, u32, u64, i64 = (ctypes.c_void_p, ctypes.c_int32,
                                  ctypes.c_uint32, ctypes.c_uint64,
                                  ctypes.c_int64)
        # tek_sc_version() -> string pointer
        d.tek_sc_version.argtypes = []
        d.tek_sc_version.restype = vp
        self.version = d.tek_sc_version
        # tek_sc_load_locale(utf16 path)
        d.tek_sc_load_locale.argtypes = [ctypes.c_wchar_p]
        d.tek_sc_load_locale.restype = None
        self.load_locale = d.tek_sc_load_locale
        # tek_sc_lib_init(bool I1, bool I1) -> ctx
        d.tek_sc_lib_init.argtypes = [ctypes.c_bool, ctypes.c_bool]
        d.tek_sc_lib_init.restype = vp
        self.lib_init = d.tek_sc_lib_init
        d.tek_sc_lib_cleanup.argtypes = [vp]
        d.tek_sc_lib_cleanup.restype = None
        self.lib_cleanup = d.tek_sc_lib_cleanup
        # error message resolution
        d.tek_sc_err_get_msgs.argtypes = [ctypes.POINTER(Error)]
        d.tek_sc_err_get_msgs.restype = ErrorMessages
        self.err_get_msgs = d.tek_sc_err_get_msgs
        d.tek_sc_err_release_msgs.argtypes = [ctypes.POINTER(ErrorMessages)]
        d.tek_sc_err_release_msgs.restype = None
        self.err_release_msgs = d.tek_sc_err_release_msgs
        # tek_sc_s3c_sync_manifest(ctx, utf8 url, timeoutMs) -> Error
        d.tek_sc_s3c_sync_manifest.argtypes = [vp, ctypes.c_char_p, i32]
        d.tek_sc_s3c_sync_manifest.restype = Error
        self.s3c_sync_manifest = d.tek_sc_s3c_sync_manifest
        # CM client
        d.tek_sc_cm_client_create.argtypes = [vp, vp]
        d.tek_sc_cm_client_create.restype = vp
        self.cm_client_create = d.tek_sc_cm_client_create
        d.tek_sc_cm_client_destroy.argtypes = [vp]
        d.tek_sc_cm_client_destroy.restype = None
        self.cm_client_destroy = d.tek_sc_cm_client_destroy
        d.tek_sc_cm_set_user_data.argtypes = [vp, vp]
        d.tek_sc_cm_set_user_data.restype = None
        self.cm_set_user_data = d.tek_sc_cm_set_user_data
        d.tek_sc_cm_connect.argtypes = [vp, vp, i32, vp]
        d.tek_sc_cm_connect.restype = None
        self.cm_connect = d.tek_sc_cm_connect
        d.tek_sc_cm_disconnect.argtypes = [vp]
        d.tek_sc_cm_disconnect.restype = None
        self.cm_disconnect = d.tek_sc_cm_disconnect
        d.tek_sc_cm_sign_in_anon.argtypes = [vp, vp, i32]
        d.tek_sc_cm_sign_in_anon.restype = None
        self.cm_sign_in_anon = d.tek_sc_cm_sign_in_anon
        d.tek_sc_cm_ws_get_details.argtypes = [vp, ctypes.POINTER(CmDataWs), vp, i32]
        d.tek_sc_cm_ws_get_details.restype = None
        self.cm_ws_get_details = d.tek_sc_cm_ws_get_details
        d.tek_sc_cm_ws_query_items.argtypes = [vp, ctypes.POINTER(CmDataWs),
                                               u32, i32, ctypes.c_char_p, vp, i32]
        d.tek_sc_cm_ws_query_items.restype = None
        self.cm_ws_query_items = d.tek_sc_cm_ws_query_items
        # delta
        d.tek_sc_dd_estimate_disk_space.argtypes = [vp]
        d.tek_sc_dd_estimate_disk_space.restype = i64
        self.dd_estimate_disk_space = d.tek_sc_dd_estimate_disk_space
        # app manager
        d.tek_sc_am_create.argtypes = [vp, ctypes.c_wchar_p, ctypes.POINTER(Error)]
        d.tek_sc_am_create.restype = vp
        self.am_create = d.tek_sc_am_create
        d.tek_sc_am_destroy.argtypes = [vp]
        d.tek_sc_am_destroy.restype = None
        self.am_destroy = d.tek_sc_am_destroy
        d.tek_sc_am_set_ws_dir.argtypes = [vp, ctypes.c_wchar_p]
        d.tek_sc_am_set_ws_dir.restype = Error
        self.am_set_ws_dir = d.tek_sc_am_set_ws_dir
        d.tek_sc_am_get_item_desc.argtypes = [vp, ctypes.POINTER(ItemId)]
        d.tek_sc_am_get_item_desc.restype = ctypes.POINTER(AmItemDesc)
        self.am_get_item_desc = d.tek_sc_am_get_item_desc
        d.tek_sc_am_item_descs_lock.argtypes = [vp]
        d.tek_sc_am_item_descs_lock.restype = None
        self.am_item_descs_lock = d.tek_sc_am_item_descs_lock
        d.tek_sc_am_item_descs_unlock.argtypes = [vp]
        d.tek_sc_am_item_descs_unlock.restype = None
        self.am_item_descs_unlock = d.tek_sc_am_item_descs_unlock
        d.tek_sc_am_check_for_upds.argtypes = [vp, i32]
        d.tek_sc_am_check_for_upds.restype = Error
        self.am_check_for_updates = d.tek_sc_am_check_for_upds
        d.tek_sc_am_create_job.argtypes = [vp, ctypes.POINTER(ItemId), u64,
                                           ctypes.c_bool,
                                           ctypes.POINTER(ctypes.POINTER(AmItemDesc))]
        d.tek_sc_am_create_job.restype = Error
        self.am_create_job = d.tek_sc_am_create_job
        d.tek_sc_am_run_job.argtypes = [vp, ctypes.POINTER(AmItemDesc), vp]
        d.tek_sc_am_run_job.restype = Error
        self.am_run_job = d.tek_sc_am_run_job
        d.tek_sc_am_pause_job.argtypes = [ctypes.POINTER(AmItemDesc)]
        d.tek_sc_am_pause_job.restype = None
        self.am_pause_job = d.tek_sc_am_pause_job
        d.tek_sc_am_cancel_job.argtypes = [vp, ctypes.POINTER(AmItemDesc)]
        d.tek_sc_am_cancel_job.restype = Error
        self.am_cancel_job = d.tek_sc_am_cancel_job

    def version_string(self):
        return _read_utf8(self.version())


class SteamClientLibrary:
    """Lazy loader/holder for the native library. Construction never
    loads anything; .native raises LibraryUnavailable with the reason
    when the DLL cannot be used."""

    def __init__(self, dll_path):
        self.dll_path = Path(dll_path)
        self._native = None

    @property
    def native(self):
        if self._native is None:
            ok, reason = availability(self.dll_path)
            if not ok:
                raise LibraryUnavailable(reason)
            try:
                self._native = _Native(self.dll_path)
            except OSError as e:
                raise LibraryUnavailable(
                    f"failed to load {self.dll_path}: {e}") from e
        return self._native

    def version_string(self):
        return self.native.version_string()


# =====================================================================
# High-level wrappers - mirror TEKSteamClient.cs's LibCtx / CmClient /
# AppManager classes, including the CM connect -> anonymous sign-in ->
# retry ladder from CmClient.GetModDetails / QueryMods.
# =====================================================================

class LibCtx:
    """tek_sc_lib_init context (C# LibCtx SafeHandle)."""

    def __init__(self, library, use_file_cache=True, disable_lws_logs=True):
        self._native = library.native
        self.handle = self._native.lib_init(use_file_cache, disable_lws_logs)
        if not self.handle:
            raise TekSteamClientError(
                "Failed to initialize tek-steamclient library context")
        self._closed = False

    def close(self):
        if not self._closed and self.handle:
            self._native.lib_cleanup(self.handle)
            self.handle = None
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def sync_s3_manifest(self, url, timeout_ms=16000):
        err = self._native.s3c_sync_manifest(
            self.handle, url.encode("utf-8"), timeout_ms)
        return TekError(self._native, err)


class CmClient:
    """CM client (C# CmClient SafeHandle) with TEK's retry ladder:
    try the Workshop call; on 'not signed in' (aux 30) sign in
    anonymously; on 'not connected' (aux 29) connect first, then loop.
    """

    def __init__(self, lib_ctx):
        self._native = lib_ctx._native
        self._ctx = lib_ctx
        self.handle = self._native.cm_client_create(lib_ctx.handle, None)
        if not self.handle:
            raise TekSteamClientError("Failed to create a CM client")
        self._event = threading.Event()
        self._data_ws = None  # CmDataWs of the in-flight operation
        self._closed = False
        # Callback objects must stay referenced for as long as the
        # native side can call them.
        self._cb_conn = CM_CALLBACK(self._on_conn_or_signin)
        self._cb_signin = CM_CALLBACK(self._on_conn_or_signin)
        self._cb_disconn = CM_CALLBACK(self._on_disconn)
        self._cb_ws = CM_CALLBACK(self._on_ws)

    # -- native callbacks ------------------------------------------------
    def _on_conn_or_signin(self, _client, data, _user_data):
        # CbConn/CbSignedIn in C#: data is an Error*, and the current
        # CmDataWs (passed as the client's user data) receives it.
        try:
            if data and self._data_ws is not None:
                err = ctypes.cast(data, ctypes.POINTER(Error)).contents
                self._data_ws.Result = err
        finally:
            self._event.set()

    def _on_disconn(self, _client, _data, _user_data):
        pass  # C#'s CbDisconn is empty too

    def _on_ws(self, _client, _data, _user_data):
        # CbMd in C#: the CmDataWs itself arrives as `data`; the
        # native side has already filled it in - just wake the waiter.
        self._event.set()

    # -- lifecycle -------------------------------------------------------
    def close(self):
        if not self._closed and self.handle:
            try:
                self._native.cm_disconnect(self.handle)
            finally:
                self._native.cm_client_destroy(self.handle)
                self.handle = None
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    # -- TEK's connect/sign-in ladder ------------------------------------
    def _run_with_ladder(self, data_ws, start_op, timeout_ms=10000):
        """Run start_op() (a Workshop call) with TEK's retry ladder.
        Returns True when the op ultimately succeeded."""
        self._data_ws = data_ws
        self._native.cm_set_user_data(
            self.handle, ctypes.cast(ctypes.byref(data_ws), ctypes.c_void_p))
        wait_s = max(timeout_ms, 1000) / 1000.0 + 5.0
        while True:
            self._event.clear()
            start_op()
            self._event.wait(wait_s)
            if data_ws.Result.success:
                return True
            if data_ws.Result.Auxiliary != 30:  # not a "signed out" error
                return False
            self._event.clear()
            self._native.cm_sign_in_anon(
                self.handle,
                ctypes.cast(self._cb_signin, ctypes.c_void_p), timeout_ms)
            self._event.wait(wait_s)
            if data_ws.Result.success:
                continue
            if data_ws.Result.Auxiliary != 29:  # not a "not connected" error
                return False
            self._event.clear()
            self._native.cm_connect(
                self.handle, ctypes.cast(self._cb_conn, ctypes.c_void_p),
                timeout_ms, ctypes.cast(self._cb_disconn, ctypes.c_void_p))
            self._event.wait(wait_s)
            if not data_ws.Result.success:
                return False
            # connected - loop back and sign in / retry the op

    @staticmethod
    def _details_from_entries(entries, count):
        out = []
        for i in range(count):
            item = entries[i]
            status = 1 if item.Result.success else (2 if item.Result.Auxiliary == 9 else 0)
            out.append(ModDetails(
                app_id=item.AppId, status=status,
                last_updated=item.LastUpdated, mod_id=item.Id,
                manifest_id=item.ManifestId, name=_read_utf8(item.Name),
                preview_url=_read_utf8(item.PreviewUrl)))
        return out

    def get_mod_details(self, mod_ids, timeout_ms=10000):
        """CmClient.GetModDetails: details for specific Workshop ids.
        Anonymous sign-in only - no credentials involved."""
        ids = [int(m) for m in mod_ids]
        entries = (CmWsItemDetails * len(ids))()
        for i, mod_id in enumerate(ids):
            entries[i].Id = mod_id
        data_ws = CmDataWs()
        data_ws.Details = entries
        data_ws.NumDetails = len(ids)

        def op():
            self._native.cm_ws_get_details(
                self.handle, ctypes.byref(data_ws),
                ctypes.cast(self._cb_ws, ctypes.c_void_p), timeout_ms)

        if not self._run_with_ladder(data_ws, op, timeout_ms):
            return []
        return self._details_from_entries(entries, len(ids))

    def query_mods(self, page=1, search=None, app_id=346110,
                   timeout_ms=10000):
        """CmClient.QueryMods: one 20-item Workshop browse page.
        Returns (details, total_items)."""
        entries = (CmWsItemDetails * 20)()
        data_ws = CmDataWs()
        data_ws.Details = entries
        data_ws.NumDetails = 20
        search_bytes = search.encode("utf-8") if search else None

        def op():
            self._native.cm_ws_query_items(
                self.handle, ctypes.byref(data_ws), int(app_id), int(page),
                search_bytes, ctypes.cast(self._cb_ws, ctypes.c_void_p),
                timeout_ms)

        if not self._run_with_ladder(data_ws, op, timeout_ms):
            return [], 0
        count = max(0, min(data_ws.NumReturnedDetails, 20))
        return self._details_from_entries(entries, count), data_ws.TotalItems


class AppManager:
    """App manager (C# AppManager SafeHandle): depot download/update
    jobs against the library's state directory. Ported completely but
    not GUI-wired in this version (SteamCMD remains the download
    path); construction failure is reported via creation_error,
    exactly like C# (which does not throw)."""

    def __init__(self, lib_ctx, path):
        self._native = lib_ctx._native
        err = Error()
        self.handle = self._native.am_create(lib_ctx.handle, str(path),
                                             ctypes.byref(err))
        self.creation_error = TekError(self._native, err)
        self._closed = False

    @property
    def valid(self):
        return bool(self.handle)

    def close(self):
        if not self._closed and self.handle:
            self._native.am_destroy(self.handle)
            self.handle = None
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def set_workshop_dir(self, path):
        err = self._native.am_set_ws_dir(self.handle, str(path))
        return TekError(self._native, err)

    def lock_item_descs(self):
        self._native.am_item_descs_lock(self.handle)

    def unlock_item_descs(self):
        self._native.am_item_descs_unlock(self.handle)

    def get_item_desc(self, item_id):
        """AmGetItemDesc -> POINTER(AmItemDesc) or None."""
        return self._native.am_get_item_desc(
            self.handle, ctypes.byref(item_id))

    def check_for_updates(self, timeout_ms=10000):
        err = self._native.am_check_for_updates(self.handle, timeout_ms)
        return TekError(self._native, err)

    def run_job(self, item_id, manifest_id, force_verify=False,
                upd_handler=None):
        """AppManager.RunJob, mirrored: reuse the running job's desc
        when one exists, otherwise create the job, then run it.
        upd_handler is an AM_JOB_UPD callback (kept referenced by the
        caller for the job's lifetime) or None.
        Returns (TekError, desc-pointer-or-None)."""
        desc = self.get_item_desc(item_id)
        if not desc or not (desc.contents.Status & int(AmItemStatus.Job)):
            desc = ctypes.POINTER(AmItemDesc)()
            err = self._native.am_create_job(
                self.handle, ctypes.byref(item_id), int(manifest_id),
                bool(force_verify), ctypes.byref(desc))
            tek_err = TekError(self._native, err)
            if not tek_err.success:
                return tek_err, None
        handler_ptr = (ctypes.cast(upd_handler, ctypes.c_void_p)
                       if upd_handler is not None else None)
        err = self._native.am_run_job(self.handle, desc, handler_ptr)
        return TekError(self._native, err), desc

    def pause_job(self, desc):
        self._native.am_pause_job(desc)

    def cancel_job(self, desc):
        err = self._native.am_cancel_job(self.handle, desc)
        return TekError(self._native, err)

    def estimate_delta_disk_space(self, delta_ptr):
        return self._native.dd_estimate_disk_space(delta_ptr)


# =====================================================================
# One-call helpers for the GUI (run these on a worker thread - they do
# network + native calls). Both download the DLL on first use, like TEK.
# =====================================================================

def _open_library(dll_dir):
    # Platform first: never download a Windows DLL on a non-Windows
    # machine just to fail loading it afterwards.
    ok, reason = availability()
    if not ok:
        raise LibraryUnavailable(reason)
    dll_path = ensure_dll(dll_dir)
    return SteamClientLibrary(dll_path)


def workshop_details(mod_ids, dll_dir, timeout_ms=10000):
    """Details for Workshop ids via the CM client (anonymous sign-in).
    Returns [ModDetails]. Raises LibraryUnavailable / TekSteamClientError
    with a human reason on failure."""
    library = _open_library(dll_dir)
    with LibCtx(library) as ctx:
        with CmClient(ctx) as cm:
            return cm.get_mod_details(mod_ids, timeout_ms=timeout_ms)


def workshop_query(search=None, page=1, app_id=346110, dll_dir=None,
                   timeout_ms=10000):
    """One Workshop browse page via the CM client.
    Returns ([ModDetails], total_items)."""
    if dll_dir is None:
        raise LibraryUnavailable("no DLL directory configured")
    library = _open_library(dll_dir)
    with LibCtx(library) as ctx:
        with CmClient(ctx) as cm:
            return cm.query_mods(page=page, search=search, app_id=app_id,
                                 timeout_ms=timeout_ms)
