import unittest
from unittest.mock import patch

import win_integration as wi


class BindingTests(unittest.TestCase):
    def test_common_bindings(self):
        self.assertEqual(wi.parse_binding("Ctrl+Alt+Space"), (0x0003, 0x20))
        self.assertEqual(wi.parse_binding("Ctrl+Alt+D"), (0x0003, ord("D")))
        self.assertEqual(wi.parse_binding("Shift+F12"), (0x0004, 0x7B))

    def test_invalid_bindings_rejected(self):
        for value in ("", "Ctrl+Ctrl+A", "Alt+", "Space+Ctrl", "Ctrl+F25", "Meta+K"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                wi.parse_binding(value)


class InsertionTests(unittest.TestCase):
    def test_uia_identity_is_required_and_bound_to_runtime_id_pid_and_password(self):
        target = wi.CaptureTarget(10, 20, 30, 20, True, (1, 2, 3), 20, 50004,
                                  False, True, True, "uia")
        safe_identity = ((1, 2, 3), 20, 50004, False, True, True, 30)
        with patch.object(wi, "_focused_uia_identity", return_value=safe_identity):
            self.assertTrue(wi._uia_target_matches(target))
        for changed in (
            ((1, 2, 4), 20, 50004, False, True, True, 30),  # another input, same HWND
            ((1, 2, 3), 21, 50004, False, True, True, 30),  # different process
            ((1, 2, 3), 20, 50004, True, True, True, 30),   # password
            ((1, 2, 3), 20, 50004, False, False, True, 30), # disabled
            ((1, 2, 3), 20, 50004, False, True, False, 30), # focus moved
            None,
        ):
            with self.subTest(changed=changed), patch.object(wi, "_focused_uia_identity", return_value=changed):
                self.assertFalse(wi._uia_target_matches(target))

    def test_uia_errors_fail_closed(self):
        target = wi.CaptureTarget(10, 20, 30, 20, True, (1,), 20, 50004,
                                  False, True, True, "uia")
        with patch.object(wi, "_focused_uia_identity", side_effect=RuntimeError("UIA unavailable")):
            self.assertFalse(wi._uia_target_matches(target))

    def test_refuses_untrusted_and_unsafe_text_before_input(self):
        with patch.object(wi, "IS_WINDOWS", True), patch.object(wi, "_safe_target") as safe, \
                patch.object(wi, "_user32", create=True) as user32:
            safe.return_value = (False, "Original window is no longer foreground")
            self.assertEqual(wi.paste_text(object(), "hello"),
                             (False, "Original window is no longer foreground"))
            user32.SendInput.assert_not_called()
            self.assertFalse(wi.paste_text(object(), "line1\nline2")[0])
            self.assertFalse(wi.paste_text(object(), "")[0])
            user32.SendInput.assert_not_called()

    def test_unicode_input_is_utf16_and_never_uses_clipboard(self):
        captured = {}

        def send(count, ptr, size):
            arr = wi.ctypes.cast(ptr, wi.ctypes.POINTER(wi._INPUT * count)).contents
            captured["units"] = [arr[i].ki.wScan for i in range(0, count, 2)]
            captured["flags"] = [arr[i].ki.dwFlags for i in range(count)]
            captured["size"] = size
            return count

        with patch.object(wi, "IS_WINDOWS", True), patch.object(wi, "_safe_target", return_value=(True, "")), \
                patch.object(wi, "_user32", create=True) as user32:
            user32.SendInput.side_effect = send
            self.assertEqual(wi.paste_text(wi.CaptureTarget(1, 2, 3, 2), "A😀"), (True, "Text inserted"))
        self.assertEqual(captured["units"], [0x41, 0xD83D, 0xDE00])
        self.assertEqual(captured["flags"], [4, 6, 4, 6, 4, 6])
        self.assertEqual(captured["size"], wi.ctypes.sizeof(wi._INPUT))

    def test_partial_input_reports_failure(self):
        with patch.object(wi, "IS_WINDOWS", True), patch.object(wi, "_safe_target", return_value=(True, "")), \
                patch.object(wi, "_user32", create=True) as user32:
            user32.SendInput.return_value = 1
            self.assertEqual(wi.paste_text(wi.CaptureTarget(1, 2, 3, 2), "ok"),
                             (False, "Windows accepted only part of the Unicode input"))


class OptionalPlatformTests(unittest.TestCase):
    def test_non_windows_capture_is_explicitly_unavailable(self):
        with patch.object(wi, "IS_WINDOWS", False):
            with self.assertRaises(wi.WindowsUnavailable):
                wi.capture_target()

    def test_hold_mode_validation_is_platform_independent(self):
        with self.assertRaises(ValueError):
            wi.Hotkeys(lambda event: None, mode="press-and-hope")


if __name__ == "__main__":
    unittest.main()
