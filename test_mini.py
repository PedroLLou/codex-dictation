import os
import tkinter as tk
import unittest
from unittest.mock import Mock,patch
from gui_v2 import App
from win_integration import CaptureTarget, IS_WINDOWS
import tempfile
from pathlib import Path
from settings import SettingsStore

class MiniTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk(); self.root.withdraw()
        self.temp=tempfile.TemporaryDirectory()
        with patch('gui_v2.sd.query_devices',return_value=[]): self.app=App(self.root,start_services=False,settings_store=SettingsStore(Path(self.temp.name)/'settings.json'))
        self.app.ready=True
    def tearDown(self):
        self.app.close(force=True); self.temp.cleanup()
    def test_toggle_captures_external_target(self):
        self.app.mini=Mock()
        target=CaptureTarget(100,999999,101,999999,True)
        with patch('gui_v2.capture_target',return_value=target),patch.object(self.app,'start') as start:
            self.app.mini_toggle(); start.assert_called_once_with(target)
    def test_own_window_is_not_a_target(self):
        self.app.mini=Mock(); self.app.mini_record=Mock()
        with patch('gui_v2.capture_target',return_value=CaptureTarget(100,os.getpid(),101,os.getpid(),True)),patch.object(self.app,'start') as start:
            self.app.mini_toggle(); start.assert_not_called()
    def test_auto_insert_can_be_enabled_for_capture_without_changing_preference(self):
        self.app.capture_auto_paste=True; self.app.target=object()
        with patch('gui_v2.paste_text',return_value=(True,'')) as paste: self.app.append_text('frase',allow_paste=True)
        paste.assert_called_once(); self.assertFalse(self.app.prefs['auto_paste'])
    def test_visibility_follows_t3_without_repeated_show_calls(self):
        self.app.mini=Mock(); self.app.mini_tooltips=[Mock()]
        with patch('gui_v2.foreground_is_t3',return_value=True):
            self.app.sync_mini_visibility(); self.app.sync_mini_visibility()
        self.app.mini.deiconify.assert_called_once()
        with patch('gui_v2.foreground_is_t3',return_value=False):
            self.app.sync_mini_visibility(); self.app.sync_mini_visibility()
        self.app.mini.withdraw.assert_called_once()
        self.app.mini_tooltips[0].leave.assert_called_once()
        with patch('gui_v2.foreground_is_t3',return_value=True): self.app.sync_mini_visibility()
        self.assertEqual(self.app.mini.deiconify.call_count,2)
    def test_visibility_hides_when_foreground_cannot_be_read(self):
        self.app.mini=Mock(); self.app.mini_visible=True
        with patch('gui_v2.foreground_is_t3',side_effect=OSError): self.app.sync_mini_visibility()
        self.app.mini.withdraw.assert_called_once()
    @unittest.skipUnless(IS_WINDOWS,'Windows')
    def test_native_mini_has_only_two_buttons_and_nonactivating_style(self):
        from win_integration import _user32
        self.root.deiconify(); self.root.update()
        with patch('gui_v2.foreground_is_t3',return_value=True): self.app.enter_mini()
        self.root.update()
        self.assertIsNotNone(self.app.mini)
        hwnd=_user32.GetAncestor(self.app.mini.winfo_id(),2)
        self.assertTrue(_user32.GetWindowLongW(hwnd,-20)&0x08000000)
        self.assertTrue(_user32.GetWindowLongW(hwnd,-20)&0x00040000)
        self.assertFalse(_user32.GetWindowLongW(hwnd,-20)&0x00000080)
        self.assertEqual(int(_user32.GetWindow(hwnd,4) or 0),0)  # GW_OWNER
        import customtkinter as ctk
        panel=self.app.mini_record.master
        self.assertEqual(sum(isinstance(child,ctk.CTkButton) for child in panel.winfo_children()),2)
        for child in panel.winfo_children():
            if isinstance(child,ctk.CTkButton):
                self.assertLessEqual(child.winfo_x()+child.winfo_width(),panel.winfo_width())
        foreground=_user32.GetForegroundWindow()
        with patch('gui_v2.foreground_is_t3',return_value=False): self.app.sync_mini_visibility()
        self.root.update(); self.assertFalse(self.app.mini.winfo_ismapped())
        with patch('gui_v2.foreground_is_t3',return_value=True): self.app.sync_mini_visibility()
        self.root.update(); self.assertTrue(self.app.mini.winfo_ismapped())
        self.assertEqual(_user32.GetForegroundWindow(),foreground)
        self.app.exit_mini(); self.root.update()
        self.assertIsNone(self.app.mini); self.assertTrue(self.root.winfo_ismapped())
    @unittest.skipUnless(IS_WINDOWS,'Windows')
    def test_foreground_matches_t3_executable_names_only(self):
        from win_integration import foreground_is_t3
        with patch('win_integration._user32.GetForegroundWindow',return_value=123),patch('win_integration._window_pid',return_value=42):
            for name in ('t3 code.exe','t3 code (nightly).exe'):
                with patch('win_integration._process_name',return_value=name): self.assertTrue(foreground_is_t3())
            for name in ('chrome.exe','notepad.exe','', 't3-resource-monitor.exe'):
                with patch('win_integration._process_name',return_value=name): self.assertFalse(foreground_is_t3())

if __name__=='__main__': unittest.main()
