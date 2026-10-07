"""Validação remota opcional, apenas WAV sintético existente, sem microfone."""
import base64
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import wave

ROOT = Path(__file__).resolve().parent

def main():
    with wave.open(str(ROOT.parent / 'ditado-local' / 'validacao' / 'frase-sintetica.wav')) as source:
        assert source.getnchannels() == 1 and source.getsampwidth() == 2
        rate = source.getframerate()
        pcm = source.readframes(source.getnframes())
    messages = queue.Queue()
    child = subprocess.Popen([sys.executable, str(ROOT / 'live.py')], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    def reader():
        for line in child.stdout:
            messages.put(json.loads(line))
    threading.Thread(target=reader, daemon=True).start()
    def send(message):
        child.stdin.write(json.dumps(message) + '\n')
        child.stdin.flush()
    def wait(kind, timeout=40):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = messages.get(timeout=max(.1, deadline - time.monotonic()))
            if item['kind'] != 'preview': print(json.dumps(item), flush=True)
            if item['kind'] == 'error':
                raise RuntimeError(item['error'])
            if item['kind'] == kind:
                return item
        raise RuntimeError('VALIDATION_TIMEOUT')
    results = []
    try:
        wait('ready')
        for generation, audio in [(1, pcm), (2, pcm[:int(rate * 4.2) * 2])]:
            click = time.monotonic()
            send({'command': 'prepare', 'generation': generation})
            ready = wait('voice_ready')
            started = time.monotonic()
            size = rate // 50 * 2
            for position in range(0, len(audio), size):
                target = started + position / (rate * 2)
                if target > time.monotonic():
                    time.sleep(target - time.monotonic())
                send({'command': 'audio', 'generation': generation, 'rate': rate,
                    'pcm': base64.b64encode(audio[position:position + size]).decode('ascii')})
            send({'command': 'stop', 'generation': generation})
            stopped = time.monotonic()
            result = wait('result', timeout=20)
            result['observedAfterStopSeconds'] = round(time.monotonic() - stopped, 2)
            result['observedPreparationSeconds'] = round(started - click, 2)
            result['brokerConnectSeconds'] = ready['connectSeconds']
            assert result['text']
            assert result.get('status') == 'final', result
            results.append(result)
        assert 'antes de enviar' in results[0]['text'].lower()
        assert 'apague este arquivo' in results[0]['text'].lower()
        assert 'teste de ditado' in results[1]['text'].lower()
        assert results[1]['text'].lower().count('teste de ditado') == 1
        (ROOT / 'live-validation.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
        print('LIVE_VALIDATION_OK', flush=True)
    finally:
        send({'command': 'shutdown'})
        child.wait(timeout=15)

if __name__ == '__main__':
    main()
