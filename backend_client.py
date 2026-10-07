"""Cliente do broker: fila limitada, IDs de processo e término verificável."""
import base64
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import numpy as np
from process_job import ProcessJob

from runtime_paths import ROOT, backend_command


class BackendClient:
    def __init__(self, callback):
        self.callback = callback
        self.process = None
        self.queue = queue.Queue(maxsize=512)
        self.done = threading.Event()
        self.done.set()
        self.closing = False
        self.thread = None
        self.cleanup_error = False
        self.job = None

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError('O serviço anterior ainda está encerrando.')
        self.done.clear()
        self.closing = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def send(self, message):
        if self.done.is_set() or self.closing:
            raise RuntimeError('O serviço de ditado está desconectado.')
        self.queue.put_nowait(message)

    def send_audio(self, samples, rate, generation, sequence):
        self.send({'command': 'audio', 'generation': generation, 'rate': rate,
            'seq': sequence, '_samples': samples})

    def interrupt(self, message):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.queue.put_nowait(message)

    def run(self):
        process = None
        try:
            self.job = ProcessJob()
            process = subprocess.Popen(backend_command(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
            self.process = process
            self.job.attach(process)
            def send_loop():
                try:
                    while True:
                        item = self.queue.get()
                        if item is None:
                            return
                        message = dict(item)
                        samples = message.pop('_samples', None)
                        if samples is not None:
                            message['pcm'] = base64.b64encode(
                                (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()).decode('ascii')
                        process.stdin.write(json.dumps(message) + '\n')
                        process.stdin.flush()
                        if message.get('command') == 'shutdown':
                            return
                except (OSError, ValueError):
                    if not self.closing:
                        self.callback({'kind': 'fatal', 'error': 'PIPE_CLOSED'})
            sender = threading.Thread(target=send_loop, daemon=True)
            sender.start()
            for line in process.stdout:
                if len(line) > 2_000_000:
                    raise RuntimeError('INVALID_BROKER_MESSAGE')
                message = json.loads(line)
                self.callback(message)
            process.wait()
            if not self.closing:
                self.callback({'kind': 'fatal', 'error': 'BROKER_CLOSED'})
        except Exception as exc:
            if not self.closing:
                self.callback({'kind': 'fatal', 'error': type(exc).__name__})
        finally:
            self.interrupt(None)
            try:
                if process and process.poll() is None:
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.cleanup_error = True
            finally:
                if self.job: self.job.close(); self.job = None
                if process and process.poll() is not None: self.cleanup_error = False
                if not self.cleanup_error: self.process = None
                self.done.set()

    def close(self):
        if self.closing:
            return
        self.closing = True
        if not self.done.is_set():
            self.interrupt({'command': 'shutdown'})
            def watchdog():
                if not self.done.wait(10):
                    if self.job: self.job.close()
                    process = self.process
                    if process and process.poll() is None:
                        # Escopo restrito ao broker que esta instância iniciou.
                        try:
                            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                        except (OSError, subprocess.TimeoutExpired): self.cleanup_error = True
            threading.Thread(target=watchdog, daemon=True).start()

    def wait(self, seconds=12):
        return self.done.wait(seconds)
