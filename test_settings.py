import json
import tempfile
import unittest
from pathlib import Path

from settings import (
    DEFAULTS,
    SettingsStore,
    apply_dictionary,
    format_dictionary,
    parse_dictionary,
)


class SettingsStoreTests(unittest.TestCase):
    def test_defaults_and_atomic_save_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "userdata" / "settings.json"
            store = SettingsStore(path)
            self.assertEqual(store.load(), DEFAULTS)
            saved = store.save({"auto_paste": True, "idle_seconds": 45, "unknown": "ignored"})
            self.assertTrue(saved["auto_paste"])
            self.assertEqual(saved["idle_seconds"], 45)
            self.assertNotIn("unknown", saved)
            self.assertEqual(store.load(), saved)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_corrupt_preferences_are_preserved_and_warn(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = "{bad json"
            path.write_text(original, encoding="utf-8")
            store = SettingsStore(path)
            self.assertEqual(store.load(), DEFAULTS)
            self.assertTrue(store.load_warning)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_bad_fields_fall_back_individually_and_unknowns_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({
                "auto_paste": "yes", "idle_seconds": 999, "tail_seconds": True,
                "hotkey_mode": "press-and-pray", "dictionary": [{"from": "x", "to": 2}],
                "topmost": True, "transcripts": ["must not persist"],
            }), encoding="utf-8")
            loaded = SettingsStore(path).load()
            self.assertFalse(loaded["auto_paste"])
            self.assertEqual(loaded["idle_seconds"], 30)
            self.assertEqual(loaded["tail_seconds"], 0.7)
            self.assertEqual(loaded["hotkey_mode"], "toggle")
            self.assertEqual(loaded["dictionary"], [])
            self.assertTrue(loaded["topmost"])
            self.assertNotIn("transcripts", loaded)

    def test_numeric_bounds_and_rule_limits(self):
        self.assertEqual(DEFAULTS["max_record_seconds"], 120)
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            loaded = store.save({"idle_seconds": 10, "tail_seconds": 2, "max_record_seconds": 15})
            self.assertEqual((loaded["idle_seconds"], loaded["tail_seconds"], loaded["max_record_seconds"]), (10, 2.0, 15))
            self.assertEqual(store.save({"idle_seconds": 9})["idle_seconds"], 30)
        with self.assertRaises(ValueError):
            parse_dictionary("x = " + "y" * 257)


class DictionaryTests(unittest.TestCase):
    def test_whole_words_case_and_phrase_boundaries(self):
        rules = parse_dictionary("New York = NYC\nana = Ana")
        self.assertEqual(
            apply_dictionary("New York, new yorker; BANANA, ANA!", rules, True),
            "NYC, new yorker; BANANA, Ana!",
        )
        self.assertEqual(apply_dictionary("New York", rules, False), "New York")

    def test_unicode_word_boundaries_and_punctuation(self):
        rules = [{"from": "cafe", "to": "CAFÉ"}, {"from": "São Paulo", "to": "SP"}]
        self.assertEqual(apply_dictionary("cafe! cafézinho; São Paulo.", rules, True), "CAFÉ! cafézinho; SP.")

    def test_single_pass_longest_first_and_literal_replacement(self):
        rules = [{"from": "a", "to": "$\\b"}, {"from": "a b", "to": "x"}, {"from": "x", "to": "cascaded"}]
        self.assertEqual(apply_dictionary("a b, a", rules, True), "x, $\\b")
        self.assertEqual(apply_dictionary("x", rules, True), "cascaded")

    def test_parse_format_reject_empty_and_duplicates(self):
        rules = parse_dictionary("  vc = você  \n\nIA = Inteligência Artificial")
        self.assertEqual(format_dictionary(rules), "vc = você\nIA = Inteligência Artificial")
        for invalid in (" = vazio", "origem = ", "A = um\na = dois", "linha sem separador"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_dictionary(invalid)


if __name__ == "__main__":
    unittest.main()
