"""Teste sintético: falar durante conexão e depois com voz já preparada."""
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
        rate = source.getframerate()
        assert source.getnchannels() == 1 and source.getsampwidth() == 2
        pcm = source.readframes(int(rate * 4.2))
    incoming = queue.Queue()
    child = subprocess.Popen([sys.executable, str(ROOT / 'live.py')], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    def read():
        for line in child.stdout:
            incoming.put((time.monotonic(), json.loads(line)))
    threading.Thread(target=read, daemon=True).start()
    seen = []
    def send(message):
        child.stdin.write(json.dumps(message) + '\n')
        child.stdin.flush()
    def wait(kind):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            received, item = incoming.get(timeout=max(.1, deadline - time.monotonic()))
            seen.append((received, item))
            if item['kind'] != 'preview': print(json.dumps(item), flush=True)
            if item['kind'] == 'error':
                raise RuntimeError(item.get('reason', item.get('error', 'VOICE_ERROR')))
            if item['kind'] == kind:
                return item
        raise RuntimeError('VALIDATION_TIMEOUT')
    results = []
    try:
        wait('ready')
        for generation in (1, 2):
            if generation == 2:
                wait('prepared')
            click = time.monotonic()
            send({'command': 'prepare', 'generation': generation})
            # Começa a enviar imediatamente; não aguarda voice_ready.
            size = rate // 50 * 2
            for position in range(0, len(pcm), size):
                target = click + position / (rate * 2)
                if target > time.monotonic():
                    time.sleep(target - time.monotonic())
                send({'command': 'audio', 'generation': generation, 'rate': rate,
                    'pcm': base64.b64encode(pcm[position:position + size]).decode('ascii')})
            send({'command': 'stop', 'generation': generation})
            result = wait('result')
            assert 'teste de ditado' in result['text'].lower(), result['text']
            assert result.get('status') == 'final', result
            assert result['text'].lower().count('teste de ditado') == 1, 'TRANSCRIPT_DUPLICATED'
            ready_at = next(at for at, message in seen if message['kind'] == 'voice_ready'
                and message['generation'] == generation)
            result['networkReadyAfterClickSeconds'] = round(ready_at - click, 3)
            results.append(result)
        assert results[1]['networkReadyAfterClickSeconds'] < .5
        (ROOT / 'start-validation.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
        print('START_VALIDATION_OK', flush=True)
    finally:
        send({'command': 'shutdown'})
        child.wait(timeout=15)

if __name__ == '__main__':
    main()
