import asyncio
import unittest
from unittest.mock import patch
import probe
import io
from types import SimpleNamespace

class BrokerGuard(unittest.TestCase):
    def setUp(self):
        self.rpc = probe.Rpc.__new__(probe.Rpc)
        self.rpc.diagnose = False

    def test_turn_start_blocked_before_process_access(self):
        with self.assertRaisesRegex(RuntimeError, 'RPC_NOT_ALLOWED'):
            asyncio.run(self.rpc.call('turn/start', {'input': []}))

    def test_text_and_speech_blocked(self):
        for method in ['thread/realtime/appendText', 'thread/realtime/appendSpeech']:
            with self.assertRaisesRegex(RuntimeError, 'RPC_NOT_ALLOWED'):
                asyncio.run(self.rpc.call(method, {'text': 'execute algo'}))

    def test_diagnostic_cannot_start_voice(self):
        self.rpc.diagnose = True
        with self.assertRaisesRegex(RuntimeError, 'RPC_NOT_ALLOWED'):
            asyncio.run(self.rpc.call('thread/realtime/start', {}))

    def test_non_ephemeral_and_writable_sessions_blocked(self):
        for params in [{'ephemeral': False, 'sandbox': 'read-only'},
                       {'ephemeral': True, 'sandbox': 'danger-full-access'}]:
            with self.assertRaisesRegex(RuntimeError, 'ISOLATION_REQUIRED'):
                asyncio.run(self.rpc.call('thread/start', params))

    def test_unvalidated_build_never_launches(self):
        with patch('probe.BINARY', probe.ROOT / 'does-not-exist.exe'), patch('probe.subprocess.Popen') as popen:
            with self.assertRaisesRegex(RuntimeError, 'BUILD_NOT_VALIDATED'):
                probe.Rpc()
            popen.assert_not_called()

    def test_cancel_waits_for_async_cleanup(self):
        cleaned = []
        async def waiting(args):
            try:
                await asyncio.sleep(30)
            finally:
                cleaned.append(True)
        with patch('probe.run', waiting), patch('probe.sys.stdin', io.StringIO('cancel\n')):
            result = asyncio.run(probe.entry(SimpleNamespace(cancellable=True)))
        self.assertEqual(result, {'cancelled': True})
        self.assertEqual(cleaned, [True])

    def test_completion_waits_for_audio_and_pending_last_phrase(self):
        self.assertFalse(probe.transcription_complete(20, None, 10, 9))
        self.assertFalse(probe.transcription_complete(20, 19, 18, 17))
        self.assertFalse(probe.transcription_complete(23, 19, 18, 21))
        self.assertTrue(probe.transcription_complete(24, 19, 22, 21))
        self.assertTrue(probe.transcription_complete(29, 19, None, None))

if __name__ == '__main__':
    unittest.main()
