import asyncio
import unittest
import numpy as np
from live import LiveAudio, user_messages
from types import SimpleNamespace

class Audio(unittest.TestCase):
    def test_finish_drains_audio_before_marking_end_and_then_sends_silence(self):
        async def exercise():
            track = LiveAudio()
            pcm = np.full(960 * 2, 1000, dtype='<i2').tobytes()
            track.push(pcm, 48000)
            track.finish()
            first = await track.recv()
            self.assertIsNone(track.audio_ended)
            second = await track.recv()
            self.assertIsNotNone(track.audio_ended)
            third = await track.recv()
            self.assertEqual(first.pts, 0)
            self.assertEqual(second.pts, 960)
            self.assertTrue(np.all(first.to_ndarray() == 1000))
            self.assertTrue(np.all(third.to_ndarray() == 0))
            track.stop()
        asyncio.run(exercise())

    def test_new_capture_drops_cancelled_audio_and_resets_end(self):
        track = LiveAudio()
        track.push(np.ones(960, dtype='<i2').tobytes(), 48000)
        track.finish()
        track.begin()
        self.assertEqual(track.buffer, b'')
        self.assertIsNone(track.audio_ended)
        self.assertFalse(track.finishing)
        track.stop()

    def test_fifo_audio_sent_before_connection_is_kept_in_order(self):
        async def exercise():
            track = LiveAudio()
            track.push(np.full(960, 100, dtype='<i2').tobytes(), 48000)
            track.push(np.full(960, 200, dtype='<i2').tobytes(), 48000)
            track.finish()  # equivalent to stop arriving before the first recv
            first, second = await track.recv(), await track.recv()
            self.assertTrue(np.all(first.to_ndarray() == 100))
            self.assertTrue(np.all(second.to_ndarray() == 200))
            track.stop()
        asyncio.run(exercise())

    def test_invalid_chunk_or_rate_is_rejected(self):
        track = LiveAudio()
        for pcm, rate in [(b'x', 48000), (bytes(48000 * 2 + 2), 48000), (b'xx', 1234)]:
            with self.assertRaises(RuntimeError):
                track.push(pcm, rate)
        track.stop()

    def test_previous_session_and_assistant_text_never_enter_new_result(self):
        method = 'thread/realtime/transcript/done'
        rpc = SimpleNamespace(notifications=[
            {'method': method, 'params': {'threadId': 'old', 'role': 'user', 'text': 'antigo'}},
            {'method': method, 'params': {'threadId': 'new', 'role': 'assistant', 'text': 'resposta'}},
            {'method': method, 'params': {'threadId': 'new', 'role': 'user', 'text': 'novo'}}])
        found = user_messages(rpc, 0, method, 'new')
        self.assertEqual([m['params']['text'] for m in found], ['novo'])

if __name__ == '__main__':
    unittest.main()
