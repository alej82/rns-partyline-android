import ast
import json
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from partyline_android import i18n


def setUpModule():
    i18n.reset_for_tests("es")


def tearDownModule():
    i18n.reset_for_tests("es")


def _load_master():
    with open(os.path.join(ROOT, "app", "assets", "i18n", "translations.json"), encoding="utf-8") as catalog_file:
        return json.load(catalog_file)


def _load_language(code):
    with open(os.path.join(ROOT, "app", "assets", "i18n", f"{code}.json"), encoding="utf-8") as catalog_file:
        return json.load(catalog_file)


class TranslationLookupTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("es")

    def test_spanish_lookup(self):
        self.assertEqual(i18n.t("connect.subtitle"), "Cliente Android · protocolo 1")

    def test_english_lookup(self):
        self.assertEqual(i18n.t("connect.subtitle", lang="en"), "Android client · protocol 1")

    def test_explicit_language_overrides_current(self):
        i18n.set_language("es")
        self.assertEqual(i18n.t("session.tabs.rooms", lang="en"), "Rooms")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(i18n.t("connect.subtitle", lang="fr"), "Android client · protocol 1")

    def test_unknown_key_returns_key(self):
        self.assertEqual(i18n.t("does.not.exist"), "does.not.exist")

    def test_named_interpolation(self):
        text = i18n.t("chat.user.joined", lang="en", name="Luis")
        self.assertEqual(text, "Luis connected")

    def test_spanish_interpolation(self):
        text = i18n.t("chat.user.moved", name="Luis", room="Música")
        self.assertEqual(text, "Luis se movió a «Música»")

    def test_missing_placeholder_is_left_visible(self):
        text = i18n.t("connect.status.identity")
        self.assertIn("{hash}", text)

    def test_set_language_returns_code(self):
        self.assertEqual(i18n.set_language("en"), "en")
        self.assertEqual(i18n.current_language(), "en")
        self.assertEqual(i18n.set_language("es"), "es")

    def test_available_languages(self):
        languages = i18n.available_languages()
        self.assertEqual(languages["en"], "English")
        self.assertEqual(languages["es"], "Español")

    def test_explicit_language_preferences(self):
        self.assertEqual(i18n.resolve_language("es"), "es")
        self.assertEqual(i18n.resolve_language("en"), "en")
        self.assertEqual(i18n.resolve_language("es_ES"), "es")

    def test_unsupported_system_language_falls_back_to_english(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            i18n, "is_android", return_value=False
        ), patch.object(i18n.locale, "getlocale", return_value=("fr_FR", None)):
            self.assertEqual(i18n.resolve_language("system"), "en")


class CatalogIntegrityTests(unittest.TestCase):
    def test_master_entries_have_english_and_context(self):
        master = _load_master()
        for key, entry in master["strings"].items():
            self.assertIn("en", entry, key)
            context = entry.get("context") or {}
            self.assertIn("symbol", context, key)
            self.assertIn("ui", context, key)
            self.assertTrue(context.get("file"), key)

    def test_spanish_matches_master_keys(self):
        master = _load_master()["strings"]
        spanish = _load_language("es")
        self.assertEqual(set(master), set(spanish))

    def test_placeholder_parity(self):
        master = _load_master()["strings"]
        spanish = _load_language("es")
        for key, entry in master.items():
            self.assertEqual(
                i18n.placeholder_names(entry["en"]),
                i18n.placeholder_names(spanish[key]),
                key,
            )

    def test_context_files_exist(self):
        master = _load_master()
        for key, entry in master["strings"].items():
            path = os.path.join(ROOT, entry["context"]["file"])
            self.assertTrue(os.path.exists(path), f"{key}: {path}")

    def test_every_key_is_referenced(self):
        master = _load_master()
        keys = set(master["strings"])
        reserved = set(master["meta"].get("reserved") or [])
        used = set()
        for directory, _subdirectories, files in os.walk(os.path.join(ROOT, "app")):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(directory, filename)
                with open(path, encoding="utf-8") as source_file:
                    tree = ast.parse(source_file.read(), path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        if node.value in keys:
                            used.add(node.value)
        self.assertEqual(keys - used, reserved)
        self.assertEqual(used - keys, set())


class VendoredLanguageTests(unittest.TestCase):
    def tearDown(self):
        i18n.configure("es")

    def test_spanish_client_catalog(self):
        i18n.configure("es")
        from partyline import i18n as client_i18n

        self.assertEqual(
            client_i18n._("still looking for a path to the server"),
            "buscando una ruta al servidor",
        )

    def test_spanish_client_audio_error(self):
        i18n.configure("es")
        from partyline import i18n as client_i18n

        self.assertEqual(
            client_i18n._("audio setup failed: {0}"),
            "no se pudo configurar el audio: {0}",
        )

    def test_missing_client_translation_stays_source_english(self):
        i18n.configure("es")
        from partyline import i18n as client_i18n

        self.assertEqual(client_i18n._("link closed by server"), "link closed by server")

    def test_english_client_catalog(self):
        i18n.configure("en")
        from partyline import i18n as client_i18n

        self.assertEqual(
            client_i18n._("still looking for a path to the server"),
            "still looking for a path to the server",
        )


if __name__ == "__main__":
    unittest.main()
