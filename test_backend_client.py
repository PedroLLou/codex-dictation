import queue
import subprocess
import unittest
from unittest.mock import Mock, patch
from backend_client import BackendClient

class ClientTests(unittest.TestCase):
    def test_queue_has_bound_and_cancel_discards_audio(self):
        client = BackendClient(Mock()); client.done.clear()
        for _ in range(512): client.send({'command':'audio'})
        with self.assertRaises(queue.Full): client.send({'command':'audio'})
        client.interrupt({'command':'cancel'})
        self.assertEqual(client.queue.qsize(), 1); self.assertEqual(client.queue.get()['command'], 'cancel')
    def test_cleanup_timeout_signals_completion(self):
        client = BackendClient(Mock()); client.done.clear()
        proc = Mock(); proc.stdout = []; proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired('fake', 3)
        with patch('backend_client.ProcessJob') as job, patch('backend_client.subprocess.Popen', return_value=proc):
            client.run()
        self.assertTrue(client.done.is_set()); self.assertTrue(client.cleanup_error); job.return_value.close.assert_called_once()
    def test_close_is_idempotent_and_requests_shutdown(self):
        client = BackendClient(Mock()); client.done.clear()
        with patch('backend_client.threading.Thread') as thread:
            client.close(); client.close()
        self.assertEqual(client.queue.get()['command'], 'shutdown'); thread.assert_called_once()

if __name__ == '__main__': unittest.main()
