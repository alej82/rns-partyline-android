import json
import os
import stat
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

os.environ.setdefault("PARTYLINE_CONFIG_DIR", "/tmp/partyline-android-tests/config")
os.environ.setdefault("PARTYLINE_RNS_DIR", "/tmp/partyline-android-tests/rns")

from partyline_android.servers import SavedServers
from partyline_android.settings import MobileSettings


class MobileSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "settings.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_defaults(self):
        settings = MobileSettings(path=self.path)
        self.assertEqual(settings["name"], "")
        self.assertIsNone(settings["input"])
        self.assertIsNone(settings["output"])
        self.assertEqual(settings["tx_gain_db"], 0.0)
        self.assertFalse(settings["mic_agc"])
        self.assertTrue(settings["keep_screen_on"])

    def test_save_and_load_round_trip(self):
        settings = MobileSettings(path=self.path)
        settings.apply(
            name="  Nodo  ",
            input="Mic",
            output="Spk",
            tx_gain_db=3.5,
            mic_agc=True,
            keep_screen_on=False,
        )
        settings.save()
        loaded = MobileSettings(path=self.path)
        self.assertEqual(loaded["name"], "Nodo")
        self.assertEqual(loaded["input"], "Mic")
        self.assertEqual(loaded["output"], "Spk")
        self.assertEqual(loaded["tx_gain_db"], 3.5)
        self.assertTrue(loaded["mic_agc"])
        self.assertFalse(loaded["keep_screen_on"])
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_invalid_json_falls_back_to_defaults(self):
        with open(self.path, "w") as stored:
            stored.write("{not json")
        settings = MobileSettings(path=self.path)
        self.assertEqual(settings["name"], "")
        self.assertEqual(settings["tx_gain_db"], 0.0)
        self.assertTrue(settings["keep_screen_on"])

    def test_unknown_keys_are_ignored(self):
        with open(self.path, "w") as stored:
            json.dump({"name": "Nodo", "theme": "dark", "window": [1, 2]}, stored)
        settings = MobileSettings(path=self.path)
        self.assertNotIn("theme", settings)
        self.assertNotIn("window", settings)
        self.assertEqual(settings["name"], "Nodo")

    def test_invalid_values_fall_back(self):
        with open(self.path, "w") as stored:
            json.dump({"tx_gain_db": "loud", "input": "", "mic_agc": 0}, stored)
        settings = MobileSettings(path=self.path)
        self.assertEqual(settings["tx_gain_db"], 0.0)
        self.assertIsNone(settings["input"])
        self.assertFalse(settings["mic_agc"])


class SavedServersTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "servers.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_upsert_creates_and_updates_one_entry_per_hash(self):
        servers = SavedServers(path=self.path)
        entry = servers.upsert(
            "AABBCCDDEEFF00112233445566778899",
            room="Lobby",
            password="sala",
            server_password="servidor",
            name="Servidor",
            last_used=10.0,
        )
        self.assertEqual(len(servers.entries), 1)
        self.assertEqual(entry["label"], "Servidor · Lobby")
        servers.upsert(
            "aabbccddeeff00112233445566778899",
            room="Otra",
            password="nueva",
            last_used=20.0,
        )
        self.assertEqual(len(servers.entries), 1)
        self.assertEqual(entry["room"], "Otra")
        self.assertEqual(entry["password"], "nueva")
        self.assertEqual(entry["name"], "Servidor")
        self.assertEqual(entry["label"], "Servidor · Otra")
        self.assertEqual(entry["last_used"], 20.0)

    def test_order_and_most_recent(self):
        servers = SavedServers(path=self.path)
        servers.upsert("aa" * 16, name="Viejo", last_used=100.0)
        servers.upsert("bb" * 16, name="Nuevo", last_used=200.0)
        servers.upsert("cc" * 16, name="Medio", last_used=150.0)
        ordered = [entry["name"] for entry in servers.ordered()]
        self.assertEqual(ordered, ["Nuevo", "Medio", "Viejo"])
        self.assertEqual(servers.most_recent()["name"], "Nuevo")

    def test_label_falls_back_to_hash_prefix(self):
        servers = SavedServers(path=self.path)
        entry = servers.upsert("00112233445566778899aabbccddeeff")
        self.assertEqual(entry["label"], "00112233")

    def test_remove_and_persistence(self):
        servers = SavedServers(path=self.path)
        first = servers.upsert("aa" * 16, room="Lobby")
        servers.upsert("bb" * 16, room="Otra")
        servers.remove(first)
        self.assertIsNone(servers.find("aa" * 16))
        reloaded = SavedServers(path=self.path)
        self.assertEqual(len(reloaded.entries), 1)
        self.assertEqual(reloaded.entries[0]["hash"], "bb" * 16)

    def test_find_is_case_insensitive(self):
        servers = SavedServers(path=self.path)
        servers.upsert("AABBCCDDEEFF00112233445566778899")
        self.assertIsNotNone(servers.find("aabbccddeeff00112233445566778899"))

    def test_invalid_file_falls_back_to_empty(self):
        with open(self.path, "w") as stored:
            stored.write("[not json")
        servers = SavedServers(path=self.path)
        self.assertEqual(servers.entries, [])


if __name__ == "__main__":
    unittest.main()
