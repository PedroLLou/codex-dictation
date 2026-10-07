"""Captura limitada em memória, sem acesso à interface ou à rede."""
import threading
import time
import numpy as np
import sounddevice as sd


class AudioCapture:
    def __init__(self, on_chunk):
        self.on_chunk = on_chunk
        self.stream = None
        self.chunks = []
        self.rate = 48000
        self.frames = 0
        self.level = 0.0
        self.fault = ''
        self.integrity = True
        self.limit = False
        self.recording = False
        self.lock = threading.Lock()

    def start(self, device, rate, seconds=120):
        self.rate = int(rate)
        self.maximum = self.rate * seconds
        self.chunks = []
        self.frames = 0
        self.fault = ''
        self.integrity = True
        self.limit = False
        self.level = 0.0
        self.started = time.monotonic()
        try:
            self.stream = sd.InputStream(device=device, samplerate=self.rate,
                channels=1, dtype='float32', blocksize=max(1, self.rate // 50), callback=self.callback)
            self.recording = True
            self.stream.start()
        except Exception:
            self.stop()
            raise

    def callback(self, data, frames, timing, status):
        if not self.recording:
            return
        if status:
            self.integrity = False
            self.fault = 'O microfone perdeu parte do áudio. Confira o dispositivo.'
            raise sd.CallbackAbort
        remaining = self.maximum - self.frames
        if remaining <= 0:
            self.limit = True
            raise sd.CallbackStop
        samples = data[:remaining, 0].copy()
        with self.lock:
            self.chunks.append(samples)
            self.frames += len(samples)
        self.level = float(np.sqrt(np.mean(samples ** 2)))
        try:
            self.on_chunk(samples, self.rate)
        except Exception:
            self.fault = 'O envio de áudio foi interrompido. A gravação ficou guardada para recuperação.'
            raise sd.CallbackAbort
        if self.frames >= self.maximum:
            self.limit = True
            raise sd.CallbackStop

    def stop(self):
        self.recording = False
        stream, self.stream = self.stream, None
        if stream:
            try:
                stream.stop()
            except Exception:
                pass
            finally:
                try: stream.close()
                except Exception: pass
        self.level = 0.0

    def snapshot(self):
        with self.lock:
            return {'rate': self.rate, 'chunks': list(self.chunks), 'frames': self.frames,
                'integrity': self.integrity}

    def clear(self):
        with self.lock:
            self.chunks = []
            self.frames = 0

    def has_speech(self):
        with self.lock:
            return (self.frames >= self.rate * .4 and
                    any(np.max(np.abs(c), initial=0) >= .0005 for c in self.chunks))
