import unittest
import asyncio
import io
import json
from unittest.mock import patch
import live

from live import TranscriptState, accept_sequence, result_status, validate_config
from probe import Rpc


def note(method, text, role='user', event='e1', at=1):
    return {'method': method, '_receivedAtMonotonic': at,
            'params': {'threadId': 't', 'role': role, 'text': text, 'eventId': event}}


class Protocol(unittest.TestCase):
    def test_cancel_idle_is_acknowledged_without_error(self):
        class FakeRpc:
            async def call(self, method, params):
                return {'account': {'type':'chatgpt'}} if method == 'account/read' else {}
            def notify(self, method): pass
            def pump(self): pass
            def prune_notifications(self): pass
            def close(self): pass
        output = []
        data = '\n'.join(json.dumps(m) for m in [{'command':'cancel','generation':4},{'command':'shutdown'}]) + '\n'
        with patch('live.Rpc', FakeRpc), patch('live.sys.stdin', io.StringIO(data)), patch('live.emit', side_effect=lambda kind, **kwargs: output.append({'kind':kind, **kwargs})):
            asyncio.run(live.serve())
        self.assertIn({'kind':'cancelled','generation':4}, output)
        self.assertFalse(any(m['kind']=='error' for m in output))
    def test_deltas_with_same_item_identity_keep_latest_preview(self):
        state = TranscriptState()
        for value in ('uma', 'uma frase'):
            event = note('thread/realtime/transcript/delta', value)
            event['params'].pop('eventId'); event['params']['itemId'] = 'same-item'
            state.consume(event)
        self.assertEqual(state.pending, 'uma frase')
    def test_preview_is_user_only_confirmed_plus_pending_delta(self):
        state = TranscriptState()
        state.consume(note('thread/realtime/transcript/done', 'confirmado', event='done', at=2))
        state.consume(note('thread/realtime/transcript/delta', 'provisorio', event='delta', at=3))
        state.consume(note('thread/realtime/transcript/delta', 'segredo do assistente', role='assistant', event='bad', at=4))
        self.assertEqual(state.text, 'confirmado')
        self.assertEqual(state.pending, 'provisorio')
        self.assertEqual(state.preview(), 'confirmado provisorio')

    def test_duplicate_event_id_does_not_duplicate_final_text(self):
        state = TranscriptState()
        event = note('thread/realtime/transcript/done', 'uma vez', event='same')
        self.assertTrue(state.consume(event)); self.assertFalse(state.consume(event))
        self.assertEqual(state.text, 'uma vez')

    def test_timeout_and_seqloss_never_become_final(self):
        state = TranscriptState(); state.consume(note('thread/realtime/transcript/done', 'ok', event='d', at=1))
        self.assertEqual(result_status(state, 11, 0, .5), 'timeout')
        self.assertEqual(result_status(state, 2, 0, .5, frames_lost=True), 'capture_error')
        pending = TranscriptState(); pending.consume(note('thread/realtime/transcript/delta', 'tail', event='p', at=1))
        self.assertEqual(result_status(pending, 11, 0, .5), 'timeout')

    def test_fifo_sequence_and_stop_prove_no_lost_audio(self):
        capture = {'expected_seq': 0, 'seq_used': False, 'frames_lost': False}
        accept_sequence(capture, {'seq': 0}); accept_sequence(capture, {'seq': 1}); accept_sequence(capture, {'seq': 2}, stopping=True)
        self.assertFalse(capture['frames_lost'])
        capture = {'expected_seq': 0, 'seq_used': False, 'frames_lost': False}
        accept_sequence(capture, {'seq': 0}); accept_sequence(capture, {'seq': 2}); accept_sequence(capture, {'seq': 3}, stopping=True)
        self.assertTrue(capture['frames_lost'])

    def test_legacy_without_sequence_stays_compatible(self):
        capture = {'expected_seq': 0, 'seq_used': False, 'frames_lost': False}
        accept_sequence(capture, {}); accept_sequence(capture, {}, stopping=True)
        self.assertFalse(capture['frames_lost'])

    def test_configuration_is_strict(self):
        self.assertEqual(validate_config({'command': 'configure', 'warmup': True, 'idle_seconds': 10, 'tail_seconds': .5})['idle_seconds'], 10)
        for message in ({'command': 'configure', 'warmup': 1, 'idle_seconds': 10, 'tail_seconds': .5}, {'command': 'configure', 'warmup': True, 'idle_seconds': 9, 'tail_seconds': .5}, {'command': 'configure', 'warmup': True, 'idle_seconds': 10, 'tail_seconds': 2.1}, {'command': 'configure', 'warmup': True, 'idle_seconds': 10, 'tail_seconds': .5, 'x': 1}):
            with self.assertRaisesRegex(RuntimeError, 'INVALID_CONFIG'): validate_config(message)

    def test_pruning_uses_absolute_cursors(self):
        rpc = Rpc.__new__(Rpc); rpc.notifications = [{'params': {'threadId': 'old'}}] * 2050; rpc._notification_base = 0
        rpc.prune_notifications()
        self.assertEqual(rpc._notification_base, 2)
        self.assertEqual(len(rpc.notifications_since(0)), 2048)
        self.assertEqual(rpc.notifications_since(0, 'new'), [])


if __name__ == '__main__':
    unittest.main()
