import json
import os
import tempfile
import unittest

from transcheck import config
from transcheck.config import TransCheckError


class Config(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, name):
        return os.path.join(self.dir.name, name)

    def test_defaults_and_file_created(self):
        cfg = config.load_config(self.dir.name)
        self.assertEqual(cfg, config.DEFAULT_CONFIG)
        with open(self.path("config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), config.DEFAULT_CONFIG)

    def test_no_file_when_not_asked(self):
        config.load_config(self.dir.name, create=False)
        self.assertFalse(os.path.exists(self.path("config.json")))

    def test_user_values_win_and_unknown_fields_are_ignored(self):
        with open(self.path("config.json"), "w", encoding="utf-8-sig") as f:
            json.dump({"topmost": False, "max_chars": 100, "hotkey_fix": "ctrl+alt+h", "старое_поле": 1}, f)
        cfg = config.load_config(self.dir.name)
        self.assertFalse(cfg["topmost"])
        self.assertEqual(cfg["max_chars"], 100)
        self.assertEqual(cfg["hotkey_fix"], "ctrl+alt+h")
        self.assertNotIn("старое_поле", cfg)

    def test_bad_values(self):
        for bad, text in (
            ({"topmost": "да"}, "topmost"),
            ({"max_chars": True}, "max_chars"),
            ({"max_chars": "5"}, "max_chars"),
            ({"max_chars": 0}, "max_chars"),
        ):
            with self.subTest(bad=bad):
                with open(self.path("config.json"), "w", encoding="utf-8") as f:
                    json.dump(bad, f)
                with self.assertRaises(TransCheckError) as cm:
                    config.load_config(self.dir.name)
                self.assertIn(text, str(cm.exception))

    def test_broken_json(self):
        with open(self.path("config.json"), "w", encoding="utf-8") as f:
            f.write("{ не json")
        with self.assertRaises(TransCheckError) as cm:
            config.load_config(self.dir.name)
        self.assertIn("config.json", str(cm.exception))
        with open(self.path("config.json"), "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        with self.assertRaises(TransCheckError):
            config.load_config(self.dir.name)

    def test_hotkeys(self):
        self.assertEqual(config.parse_hotkey("ctrl+alt+k"), (0x2 | 0x1, ord("K")))
        self.assertEqual(config.parse_hotkey("Ctrl + Shift + F5"), (0x2 | 0x4, 0x74))
        self.assertEqual(config.parse_hotkey("win+1"), (0x8, ord("1")))
        for bad in ("k", "ctrl+", "ctrl+alt+я", "ctrl+foo+k", "ctrl+alt+f13"):
            with self.subTest(bad=bad):
                with self.assertRaises(TransCheckError):
                    config.parse_hotkey(bad)

    def test_duplicate_hotkeys_are_rejected(self):
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["hotkey_fix"] = cfg["hotkey_check"]
        with self.assertRaises(TransCheckError) as cm:
            config.parse_all_hotkeys(cfg)
        self.assertIn("одна и та же", str(cm.exception))
        self.assertEqual(set(config.parse_all_hotkeys(config.DEFAULT_CONFIG)), set(config.HOTKEY_FIELDS))

    def test_rules_extra_template_and_reading(self):
        path = config.ensure_rules_extra(self.dir.name)
        self.assertTrue(os.path.isfile(path))
        text = config.read_rules_extra(self.dir.name)
        self.assertIn("=>", text)
        from transcheck.rules_ru import parse_extra_rules

        rules, problems = parse_extra_rules(text)
        self.assertEqual((rules, problems), ([], []))  # в шаблоне все примеры закомментированы
        with open(path, "w", encoding="utf-8") as f:
            f.write("оч => очень\n")
        rules, problems = parse_extra_rules(config.read_rules_extra(self.dir.name))
        self.assertEqual([r.replacement for r in rules], ["очень"])

    def test_rules_extra_not_overwritten(self):
        path = self.path("rules_extra.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("мое => моё\n")
        config.ensure_rules_extra(self.dir.name)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "мое => моё\n")

    def test_rules_extra_wrong_encoding(self):
        with open(self.path("rules_extra.txt"), "wb") as f:
            f.write("оч => очень".encode("cp1251"))
        with self.assertRaises(TransCheckError) as cm:
            config.read_rules_extra(self.dir.name)
        self.assertIn("UTF-8", str(cm.exception))

    def test_missing_rules_extra_is_empty(self):
        self.assertEqual(config.read_rules_extra(self.dir.name), "")


if __name__ == "__main__":
    unittest.main()
