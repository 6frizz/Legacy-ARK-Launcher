"""Headless unit tests for tek_lib.py (pure stdlib - no PyQt6, no network).

Run:  python3 -m unittest discover -s tests -v
Covers the ported TEK systems that can be verified without Windows,
Steam, or a live server: the VDF parser, appmanifest/libraryfolders
parsing, A2S packet *parsing* against crafted response bytes, and the
ARK data tables (DLC / MapCode / mod.info / extra-info validation).
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tek_lib as tek


LIBRARYFOLDERS_MODERN = '''
"libraryfolders"
{
    "0"
    {
        "path"      "C:\\\\Program Files (x86)\\\\Steam"
        "label"     ""
        "contentid" "123456789"
        "apps"
        {
            "346110"    "123456789012"
            "228980"    "1029384756"
        }
    }
    "1"
    {
        "path"      "D:\\\\SteamLibrary"
        "label"     "Games drive"
        "apps"
        {
            "346110"    "9876543210"
        }
    }
}
'''

LIBRARYFOLDERS_LEGACY = '''
"LibraryFolders"
{
    "TimeNextStatsReport"   "1700000000"
    "ContentStatsID"        "555"
    "1"     "E:\\\\SteamGames"
}
'''

APPMANIFEST_ARK = '''
"AppState"
{
    "appid"     "346110"
    "name"      "ARK: Survival Evolved"
    "installdir"    "ARK"
    "buildid"   "15076640"
    "LastUpdated"   "1700000001"
    "SizeOnDisk"    "123456789012"
    "StateFlags"    "4"
    "InstalledDepots"
    {
        "346111"
        {
            "manifest"  "3573350150089021565"
        }
        "375351"
        {
            "manifest"  "1176229965482063944"
        }
    }
}
'''


def _cstr(s):
    return s.encode() + b"\x00"


def craft_a2s_info():
    body = b"\xff\xff\xff\xff\x49"          # header + 'I'
    body += b"\x11"                          # protocol 17
    body += _cstr("CML Test Server - (v358.17)")
    body += _cstr("TheIsland")
    body += _cstr("ark_survival_evolved")
    body += _cstr("ARK: Survival Evolved")
    # A2S_INFO carries the AppID in a 16-bit field, so 346110 wraps.
    body += struct.pack("<H", 346110 & 0xFFFF)
    body += bytes([3, 70, 0])                # players, max, bots
    body += b"d" + b"w"                      # dedicated, windows
    body += bytes([0, 1])                    # public, VAC
    body += _cstr("358.17")
    return body


def craft_a2s_players():
    body = b"\xff\xff\xff\xff\x44"          # header + 'D'
    body += bytes([2])
    body += bytes([0]) + _cstr("Matthew") + struct.pack("<if", 12, 3661.0)
    body += bytes([1]) + _cstr("Frizz") + struct.pack("<if", -3, 59.5)
    return body


def craft_a2s_rules():
    rules = [
        ("ClusterId_s", "CMLCluster"),
        ("NUMOPENPUBCONN", "67"),
        ("SESSIONISPVE_i", "1"),
        ("SERVERUSESBATTLEYE_b", "false"),
        ("SEARCHKEYWORDS_s", "TEKWrapper 450987,731604 https://example.com/info.json"),
    ]
    body = b"\xff\xff\xff\xff\x45" + struct.pack("<h", len(rules))
    for k, v in rules:
        body += _cstr(k) + _cstr(v)
    return body


class TestVDF(unittest.TestCase):
    def test_modern_libraryfolders(self):
        data = tek.parse_vdf(LIBRARYFOLDERS_MODERN)
        libs = data["libraryfolders"]
        self.assertEqual(libs["0"]["path"], "C:\\Program Files (x86)\\Steam")
        self.assertEqual(libs["0"]["apps"]["346110"], "123456789012")
        self.assertEqual(libs["1"]["label"], "Games drive")

    def test_node_lookup_is_case_insensitive(self):
        root = tek.parse_vdf_node(APPMANIFEST_ARK)
        self.assertEqual(root.key, "AppState")
        self.assertEqual(root["APPID"].value, "346110")
        self.assertEqual(root.get_value("BuildID"), "15076640")
        depots = root["installeddepots"]
        self.assertEqual(depots["375351"].get_value("manifest"),
                         "1176229965482063944")

    def test_escapes_and_comments(self):
        text = ('// a comment\n"root"\n{\n\t"a" "x \\"y\\" z" // tail\n'
                '\t"b" "plain"\n}\n')
        data = tek.parse_vdf(text)
        self.assertEqual(data["root"]["a"], 'x "y" z')
        self.assertEqual(data["root"]["b"], "plain")

    def test_dump_roundtrip(self):
        root = tek.parse_vdf_node(APPMANIFEST_ARK)
        again = tek.parse_vdf_node(tek.dump_vdf(root))
        self.assertEqual(again.to_dict(), root.to_dict())

    def test_empty_input(self):
        self.assertEqual(tek.parse_vdf(""), {})
        self.assertIsNone(tek.parse_vdf_node(""))


class TestSteamDetection(unittest.TestCase):
    def test_parse_appmanifest(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "appmanifest_346110.acf"
            p.write_text(APPMANIFEST_ARK, encoding="utf-8")
            m = tek.parse_appmanifest(p)
        self.assertIsNotNone(m)
        self.assertEqual(m.app_id, 346110)
        self.assertEqual(m.installdir, "ARK")
        self.assertEqual(m.build_id, "15076640")
        self.assertTrue(m.is_fully_installed)
        self.assertEqual(m.installed_depots[346111], "3573350150089021565")
        self.assertEqual(m.installed_depots[375351], "1176229965482063944")

    def test_library_folders_from_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            steam = Path(td)
            (steam / "config").mkdir()
            (steam / "config" / "libraryfolders.vdf").write_text(
                LIBRARYFOLDERS_MODERN, encoding="utf-8")
            libs = tek.get_library_folders(steam)
        paths = [str(l.path) for l in libs]
        self.assertIn(str(steam), paths)                 # install itself
        self.assertTrue(any("SteamLibrary" in p for p in paths))
        lib2 = [l for l in libs if "SteamLibrary" in str(l.path)][0]
        self.assertEqual(lib2.apps.get("346110"), 9876543210)

    def test_legacy_library_folders(self):
        root = tek.parse_vdf_node(LIBRARYFOLDERS_LEGACY)
        self.assertEqual(root.get_value("1"), "E:\\SteamGames")


class TestA2SParsing(unittest.TestCase):
    def test_info(self):
        info = tek.parse_a2s_info(craft_a2s_info())
        self.assertIsNotNone(info)
        self.assertEqual(info.name, "CML Test Server")       # version split off
        self.assertEqual(info.version, "358.17")
        self.assertEqual(info.map_raw, "TheIsland")
        self.assertEqual(info.map_code, tek.MapCode.TheIsland)
        self.assertEqual(info.map_display, "The Island")
        self.assertEqual(info.folder, "ark_survival_evolved")
        self.assertEqual(info.app_id, 346110 & 0xFFFF)
        self.assertEqual((info.players, info.max_players, info.bots), (3, 70, 0))
        self.assertTrue(info.vac_secured)
        self.assertFalse(info.passworded)

    def test_info_rejects_garbage(self):
        self.assertIsNone(tek.parse_a2s_info(b"\x00\x01\x02"))
        self.assertIsNone(tek.parse_a2s_info(b"\xff\xff\xff\xff\x41\x01\x02\x03\x04"))

    def test_players(self):
        players = tek.parse_a2s_players(craft_a2s_players())
        self.assertEqual(len(players), 2)
        self.assertEqual(players[0].name, "Matthew")
        self.assertEqual(players[0].score, 12)
        self.assertEqual(players[0].duration_str, "1:01:01")
        self.assertEqual(players[1].duration_str, "0:59")

    def test_rules_and_ark_views(self):
        rules = tek.parse_a2s_rules(craft_a2s_rules())
        self.assertIsInstance(rules, tek.ServerRules)
        self.assertEqual(rules.cluster_id, "CMLCluster")
        self.assertTrue(rules.is_pve)
        self.assertEqual(rules.open_slots, 67)
        self.assertEqual(rules.player_count(70), 3)
        self.assertFalse(rules.uses_battleye)
        self.assertEqual(rules.mod_ids, [450987, 731604])
        self.assertEqual(rules.info_file_url, "https://example.com/info.json")

    def test_rules_mod_ids_spread_layout(self):
        # TEKWrapper quirk TEK comments on: mods spread over several
        # whitespace-separated tokens instead of one comma list.
        rules = tek.ServerRules(
            {"SEARCHKEYWORDS_s": "TEKWrapper 111, 222, https://x.example/i.json"})
        self.assertEqual(rules.mod_ids, [111, 222])
        self.assertEqual(rules.info_file_url, "https://x.example/i.json")

    def test_status_player_count_prefers_rules(self):
        info = tek.parse_a2s_info(craft_a2s_info())
        rules = tek.parse_a2s_rules(craft_a2s_rules())
        status = tek.ServerStatus(info=info, rules=rules)
        self.assertTrue(status.online)
        self.assertEqual(status.player_count, 3)  # 70 max - 67 open


class TestArkData(unittest.TestCase):
    def test_dlc_table_matches_tek(self):
        by_key = {d.launcher_key: d for d in tek.DLC_LIST}
        self.assertEqual((by_key["center"].app_id, by_key["center"].depot_id),
                         (473850, 346114))
        self.assertEqual((by_key["scorched"].app_id, by_key["scorched"].depot_id),
                         (512540, 375351))
        self.assertEqual((by_key["genesis"].app_id, by_key["genesis"].depot_id),
                         (1113410, 473857))
        self.assertEqual((by_key["aquatica"].app_id, by_key["aquatica"].depot_id),
                         (3537070, 3537070))
        self.assertEqual(len(tek.DLC_LIST), 11)

    def test_dlc_umap_derivation(self):
        by_key = {d.launcher_key: d for d in tek.DLC_LIST}
        self.assertEqual(by_key["scorched"].umap_name, "ScorchedEarth_P.umap")
        self.assertEqual(by_key["valguero"].umap_name, "Valguero_P.umap")
        self.assertEqual(by_key["center"].umap_name, "TheCenter.umap")
        self.assertEqual(by_key["genesis"].folder_name, "Genesis")
        self.assertEqual(by_key["fjordur"].folder_name, "FjordurOfficial")
        self.assertEqual(by_key["fjordur"].umap_name, "Fjordur.umap")
        self.assertEqual(by_key["aquatica"].folder_name, "Abyss")
        self.assertEqual(by_key["aquatica"].umap_name, "Aquatica.umap")

    def test_dlc_for_map(self):
        self.assertEqual(tek.dlc_for_map(tek.MapCode.TheCenter).launcher_key, "center")
        self.assertEqual(tek.dlc_for_map(tek.MapCode.Genesis2).launcher_key, "genesis")
        self.assertEqual(tek.dlc_for_map(tek.MapCode.LostIsland).launcher_key, "lost_island")
        self.assertEqual(tek.dlc_for_map(tek.MapCode.Aquatica).launcher_key, "aquatica")
        self.assertEqual(tek.dlc_for_map(tek.MapCode.CrystalIsles).launcher_key, "crystal_isles")

    def test_map_display(self):
        self.assertEqual(tek.SERVER_MAP_NAMES["Gen2"], tek.MapCode.Genesis2)
        self.assertEqual(tek.SERVER_MAP_NAMES["Abyss"], tek.MapCode.Aquatica)
        self.assertEqual(tek.MAP_DISPLAY_NAMES[tek.MapCode.Genesis2], "Genesis Part 2")

    def test_mod_info_name(self):
        name = "Structures Plus"
        data = struct.pack("<i", len(name) + 1) + name.encode() + b"\x00"
        self.assertEqual(tek.read_mod_info_name(data), name)
        self.assertEqual(tek.read_mod_info_name(b""), "")
        self.assertEqual(tek.read_mod_info_name(b"\x00\x00\x00\x00"), "")

    def test_extra_info_validation(self):
        ok = tek.ServerExtraInfo.from_dict({
            "HosterName": "Matthew", "Discord": "https://discord.gg/abc",
            "ServerDescription": {"Other": ["a", "b"]}})
        self.assertEqual(tek.validate_extra_info(ok), [])
        bad = tek.ServerExtraInfo.from_dict({
            "Discord": "https://example.com/nope",
            "ClusterDescription": {"Other": ["x"] * 7}})
        problems = tek.validate_extra_info(bad)
        self.assertEqual(len(problems), 2)

    def test_urls(self):
        self.assertEqual(tek.steam_connect_url("1.2.3.4", 7777),
                         "steam://connect/1.2.3.4:7777")
        self.assertIn("download_depot 346110 346114 123",
                      tek.depot_download_command(346110, 346114, "123", "C:/x"))


if __name__ == "__main__":
    unittest.main()
