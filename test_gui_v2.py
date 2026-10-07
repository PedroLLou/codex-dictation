import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
import gui_v2
from settings import SettingsStore
from audio_capture import AudioCapture

class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk(); self.root.withdraw()
        with patch('gui_v2.sd.query_devices', return_value=[]):
            self.app = gui_v2.App(self.root, start_services=False, settings_store=SettingsStore(Path(self.temp.name) / 'settings.json'))
        self.app.client = Mock(); self.app.client.done.is_set.return_value = True; self.app.client.cleanup_error = False
        self.app.ready = True
    def tearDown(self):
        self.app.client.done.is_set.return_value = True
        self.app.close(force=True); self.temp.cleanup()
    def result(self, status, text='Olá', partial=''):
        self.app.handle_backend(dict(kind='result', generation=self.app.generation, status=status, text=text, partialText=partial))
    def test_final_appends_and_releases_audio(self):
        self.app.retained = {'integrity': True}
        self.result('final'); self.assertEqual(self.app.text.get('1.0', 'end-1c'), 'Olá'); self.assertIsNone(self.app.retained)
    def test_partial_requires_acceptance_and_never_pastes(self):
        self.app.prefs['auto_paste'] = True; self.app.target = object()
        with patch('gui_v2.paste_text') as paste:
            self.result('timeout', 'Primeira', 'segunda')
            self.assertEqual(self.app.text.get('1.0', 'end-1c'), '')
            self.app.accept_partial(); paste.assert_not_called()
        self.assertEqual(self.app.text.get('1.0', 'end-1c'), 'Primeira\nsegunda')
    def test_stale_generation_ignored(self):
        self.app.generation = 4
        self.app.handle_backend(dict(kind='result', generation=3, status='final', text='velho'))
        self.assertEqual(self.app.text.get('1.0', 'end-1c'), '')
    def test_paste_only_opt_in_with_target(self):
        with patch('gui_v2.paste_text', return_value=(True, '')) as paste:
            self.result('final'); paste.assert_not_called()
            self.app.generation += 1
            self.app.prefs['auto_paste'] = True; self.app.target = object()
            self.result('final'); paste.assert_called_once()
    def test_dictionary_undo_preserves_edited_text(self):
        self.app.prefs.update(dictionary_enabled=True, dictionary=[{'from':'codex', 'to':'Codex'}])
        self.app.append_text('codex'); self.app.undo_correction()
        self.assertEqual(self.app.text.get('1.0','end-1c'), 'codex')
        self.app.clear_text(); self.app.append_text('codex'); self.app.text.insert('1.0', 'editado '); self.app.undo_correction()
        self.assertEqual(self.app.text.get('1.0','end-1c'), 'editado Codex')
    def test_history_bounded_no_files(self):
        for i in range(25): self.app.append_text(str(i))
        self.assertEqual(len(self.app.history), 20)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
    def test_cancel_invalidates_and_forgets(self):
        self.app.partial = 'texto'; self.app.retained = {'integrity':True}; self.app.cancel()
        self.assertEqual(self.app.generation, 1); self.assertIsNone(self.app.retained); self.assertEqual(self.app.partial, '')
    def test_failure_retains_recorded_audio(self):
        self.app.recording = True; self.app.capture.frames = 10; self.app.capture.chunks = [np.ones(10)]
        self.result('capture_error', '')
        self.assertEqual(self.app.retained['frames'], 10)
    def test_late_final_after_failure_is_partial(self):
        self.app.retained = {'integrity':True, 'frames':10}
        self.app.fail('falha'); self.result('final')
        self.assertEqual(self.app.text.get('1.0','end-1c'), '')
        self.assertIsNotNone(self.app.retained); self.assertEqual(self.app.partial, 'Olá')
    def test_reconnect_is_single_flight(self):
        self.app.client.done.is_set.return_value = False
        self.app.reconnect(); self.app.reconnect()
        self.app.client.close.assert_called_once(); self.assertTrue(self.app.reconnecting)
    def test_duplicate_final_is_ignored(self):
        self.result('final'); self.result('final')
        self.assertEqual(self.app.text.get('1.0','end-1c'), 'Olá')
        self.assertEqual(len(self.app.history), 1)
    def test_partial_cannot_be_upgraded_by_late_final(self):
        self.result('timeout', 'parcial'); self.result('final', 'final tardio')
        self.assertEqual(self.app.text.get('1.0','end-1c'), '')
        self.assertEqual(self.app.partial, 'parcial')
    def test_missing_device_preserves_pending_recording(self):
        original = {'integrity':True, 'frames':10}
        self.app.retained = original; self.app.partial = 'texto pendente'
        with patch('gui_v2.messagebox.askyesno', return_value=True): self.app.start()
        self.assertIs(self.app.retained, original); self.assertEqual(self.app.partial, 'texto pendente')
    def test_local_failure_waits_for_cancel_before_recovery(self):
        self.app.client.done.is_set.return_value = False
        self.app.retained = {'integrity':True, 'frames':10}
        self.app.fail('falha de envio')
        self.assertTrue(self.app.busy)
        self.app.client.interrupt.assert_called_once_with({'command':'cancel','generation':0})
        self.app.handle_backend({'kind':'cancelled','generation':0})
        self.assertFalse(self.app.busy); self.assertIsNotNone(self.app.retained)
    def test_late_result_cannot_bypass_cancel_barrier(self):
        self.app.client.done.is_set.return_value = False
        self.app.retained = {'integrity':True, 'frames':10}
        self.app.fail('falha'); self.result('final')
        self.assertTrue(self.app.busy)
        self.app.handle_backend({'kind':'cancelled','generation':0})
        self.assertFalse(self.app.busy)
    def test_preview_after_terminal_does_not_reappear(self):
        self.result('final')
        self.app.handle_backend({'kind':'preview','generation':0,'text':'prévia antiga'})
        self.assertEqual(self.app.preview.get('1.0','end-1c'), '')

class AudioTests(unittest.TestCase):
    def test_delivery_failure_retains_chunk(self):
        capture = AudioCapture(Mock(side_effect=RuntimeError()))
        capture.recording = True; capture.maximum = 100
        import sounddevice as sd
        with self.assertRaises(sd.CallbackAbort): capture.callback(np.ones((10,1)),10,None,None)
        self.assertEqual(capture.frames, 10); self.assertTrue(capture.integrity)
    def test_device_loss_invalidates_recovery(self):
        capture = AudioCapture(Mock()); capture.recording = True; capture.maximum = 100
        import sounddevice as sd
        with self.assertRaises(sd.CallbackAbort): capture.callback(np.ones((10,1)),10,None,True)
        self.assertFalse(capture.integrity)

if __name__ == '__main__': unittest.main()
