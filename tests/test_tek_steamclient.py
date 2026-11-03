"""Headless tests for tek_steamclient.py (ctypes bindings port).

No DLL exists on this Linux VM and none is expected: the tests verify
that importing is side-effect free, that the ctypes structure layouts
match the C# StructLayout sizes (64-bit), that every tek_sc_* function
TEKSteamClient.cs declares has a prototype in _Native's declaration
list, and that using the library fails SOFT (LibraryUnavailable with a
reason) instead of crashing.

Run:  python3 -m unittest discover -s tests -v
"""
import ctypes
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tek_steamclient as tsc


class TestStructureSizes(unittest.TestCase):
    """Sizes computed from the C# StructLayout(Sequential) layouts."""

    def test_sizes(self):
        expected = {
            "Error": (tsc.Error, 24),
            "ErrorMessages": (tsc.ErrorMessages, 48),
            "ItemId": (tsc.ItemId, 16),
            "CmWsItemDetails": (tsc.CmWsItemDetails, 80),
            "CmDataWs": (tsc.CmDataWs, 56),
            "AmJobDesc": (tsc.AmJobDesc, 56),
            "AmItemDesc": (tsc.AmItemDesc, 104),
        }
        for name, (cls, size) in expected.items():
            self.assertEqual(ctypes.sizeof(cls), size, name)

    def test_field_offsets(self):
        self.assertEqual(ctypes.sizeof(tsc.ItemId) and
                         tsc.ItemId.WorkshopItemId.offset, 8)
        self.assertEqual(tsc.CmWsItemDetails.Result.offset, 56)
        self.assertEqual(tsc.CmDataWs.Event.offset, 48)
        self.assertEqual(tsc.AmItemDesc.Job.offset, 48)
        self.assertEqual(tsc.Error.Uri.offset, 16)

    def test_error_success_semantics(self):
        err = tsc.Error()
        self.assertTrue(err.success)          # Primary defaults to 0
        err.Primary = 5
        self.assertFalse(err.success)


class TestPrototypeCoverage(unittest.TestCase):
    """Every tek_sc_* entry point declared in TEKSteamClient.cs must
    have a prototype line in tek_steamclient.py's _Native."""

    EXPECTED = [
        "tek_sc_version", "tek_sc_load_locale", "tek_sc_lib_init",
        "tek_sc_lib_cleanup", "tek_sc_err_get_msgs",
        "tek_sc_err_release_msgs", "tek_sc_s3c_sync_manifest",
        "tek_sc_cm_client_create", "tek_sc_cm_client_destroy",
        "tek_sc_cm_set_user_data", "tek_sc_cm_connect",
        "tek_sc_cm_disconnect", "tek_sc_cm_sign_in_anon",
        "tek_sc_cm_ws_get_details", "tek_sc_cm_ws_query_items",
        "tek_sc_dd_estimate_disk_space", "tek_sc_am_create",
        "tek_sc_am_destroy", "tek_sc_am_set_ws_dir",
        "tek_sc_am_get_item_desc", "tek_sc_am_item_descs_lock",
        "tek_sc_am_item_descs_unlock", "tek_sc_am_check_for_upds",
        "tek_sc_am_create_job", "tek_sc_am_run_job",
        "tek_sc_am_pause_job", "tek_sc_am_cancel_job",
    ]

    def test_all_entry_points_declared(self):
        src = Path(tsc.__file__).read_text(encoding="utf-8")
        for name in self.EXPECTED:
            self.assertIn(f"d.{name}.argtypes", src, name)
            self.assertIn(f"d.{name}.restype", src, name)
        self.assertEqual(len(self.EXPECTED), 27)


class TestFailSoft(unittest.TestCase):
    def test_availability_off_windows(self):
        ok, reason = tsc.availability()
        if sys.platform.startswith("win"):
            self.skipTest("running on Windows")
        self.assertFalse(ok)
        self.assertIn("Windows", reason)

    def test_library_load_fails_soft(self):
        lib = tsc.SteamClientLibrary("/nonexistent/libtek-steamclient-2.dll")
        with self.assertRaises(tsc.LibraryUnavailable):
            _ = lib.native

    def test_workshop_details_fails_soft_off_windows(self):
        # Must raise LibraryUnavailable (platform or download), never
        # crash with an OSError/ctypes error escaping.
        with self.assertRaises(tsc.LibraryUnavailable):
            tsc.workshop_details([450987], "/nonexistent-dir-xyz")

    def test_no_injector_bindings(self):
        # The injector / game-runtime exclusion is structural: no
        # prototypes are declared for them and no download URL names
        # them. (The module docstring mentions them only to say they
        # are excluded.)
        src = Path(tsc.__file__).read_text(encoding="utf-8")
        self.assertNotIn("d.tek_inj", src)
        for url in tsc.DLL_URLS:
            self.assertIn("libtek-steamclient-2.dll", url)
        self.assertEqual(tsc.DLL_NAME, "libtek-steamclient-2.dll")


if __name__ == "__main__":
    unittest.main()
