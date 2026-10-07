import unittest
from unittest.mock import patch
import sys
import runtime_paths
from desktop_integration import _ps_quote

class RuntimeTests(unittest.TestCase):
    def test_source_uses_its_interpreter(self):
        with patch.object(sys,'frozen',False,create=True):
            self.assertEqual(runtime_paths.backend_command(),[sys.executable,str(runtime_paths.ROOT/'live.py')])
    def test_packaged_uses_native_service_not_recursive_gui(self):
        with patch.object(sys,'frozen',True,create=True),patch('pathlib.Path.is_file',return_value=True):
            self.assertEqual(runtime_paths.backend_command(),[str(runtime_paths.ROOT/'app-bin/Ditado Codex Service.exe')])
    def test_packaged_missing_service_fails_closed(self):
        with patch.object(sys,'frozen',True,create=True),patch('pathlib.Path.is_file',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'PACKAGED_SERVICE_MISSING'): runtime_paths.backend_command()
    def test_shortcut_paths_escape_apostrophes(self):
        self.assertEqual(_ps_quote("D:/User's/App"),"'D:/User''s/App'")

if __name__=='__main__': unittest.main()
