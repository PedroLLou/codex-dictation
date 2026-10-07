import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from i18n import tr
from settings import SettingsStore


class LocalizationTests(unittest.TestCase):
    def test_portuguese_is_default_and_english_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            self.assertEqual(store.load()["language"], "pt-BR")
            saved = store.save({"language": "en"})
            self.assertEqual(saved["language"], "en")
            self.assertEqual(store.load()["language"], "en")

    def test_invalid_language_falls_back_to_portuguese(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            self.assertEqual(store.save({"language": "fr"})["language"], "pt-BR")

    def test_ui_strings_translate_but_user_text_is_unchanged(self):
        self.assertEqual(tr("Histórico", "en"), "History")
        self.assertEqual(tr("Histórico", "pt-BR"), "Histórico")
        self.assertEqual(tr("Concluído · 1.2 s após parar", "en"), "Done · 1.2 s after stopping")
        self.assertEqual(tr("Linha 2: origem duplicada.", "en"), "Line 2: duplicate source.")
        transcript = "Please leave this transcript exactly as dictated."
        self.assertEqual(tr(transcript, "en"), transcript)

    def test_english_interface_keeps_transcript_verbatim(self):
        import gui_v2
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = tk.Tk()
            root.withdraw()
            app = None
            try:
                store = SettingsStore(Path(directory) / "settings.json")
                store.save({"language": "en"})
                with patch("gui_v2.sd.query_devices", return_value=[]):
                    app = gui_v2.App(root, start_services=False, settings_store=store)
                self.assertEqual(app.status.get(), "Ready")
                self.assertEqual(app.quick_switches["topmost"].cget("text"), "Always on top")
                app.append_text("Keep this dictated text: São Paulo.")
                self.assertEqual(app.text.get("1.0", "end-1c"), "Keep this dictated text: São Paulo.")
                # Saving unrelated preferences must not silently switch en to pt-BR.
                with patch.object(app,'install_windows'),patch('gui_v2.startup_enabled',return_value=False):
                    app.preferences()
                    import customtkinter as ctk
                    dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
                    def children(widget):
                        for child in widget.winfo_children():
                            yield child; yield from children(child)
                    combos=[w for w in children(dialog) if isinstance(w,ctk.CTkComboBox)]
                    self.assertIn('English',[w.get() for w in combos])
                    save=next(w for w in children(dialog) if isinstance(w,ctk.CTkButton) and w.cget('text')=='Save preferences')
                    save.invoke()
                    self.assertEqual(store.load()['language'],'en')
            finally:
                if app is not None:
                    app.close(force=True)
                else:
                    root.destroy()


if __name__ == "__main__":
    unittest.main()
