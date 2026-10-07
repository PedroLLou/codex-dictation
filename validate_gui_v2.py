"""Integração GUI→fila→broker→voz com WAV sintético; nenhum microfone é aberto."""
import json
import tempfile
import time
import tkinter as tk
import wave
import sys
import os
from pathlib import Path
from unittest.mock import patch
import numpy as np
from gui_v2 import App, ROOT
from settings import SettingsStore

def main():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk(); root.withdraw()
        store = SettingsStore(Path(directory) / 'preferences.json')
        store.save({'language':'en'})
        with patch.object(App, 'install_windows'):
            app = App(root, settings_store=store)
        root.title('Ditado Codex — validação isolada')
        def wait(predicate, seconds=40):
            deadline = time.monotonic() + seconds
            while not predicate():
                if time.monotonic() > deadline: raise RuntimeError('GUI_VALIDATION_TIMEOUT: ' + app.status.get())
                root.update(); time.sleep(.01)
        try:
            wait(lambda: app.ready)
            fixture = ROOT / 'tests/fixtures/frase-sintetica.wav'
            if not fixture.is_file(): fixture = ROOT.parent / 'ditado-local/validacao/frase-sintetica.wav'
            with wave.open(str(fixture)) as source:
                rate = source.getframerate(); samples = np.frombuffer(source.readframes(int(rate*4.2)), '<i2').astype(np.float32)/32768
            app.generation += 1; app.sequence = 0; app.recording = True
            app.capture.recording = True; app.capture.rate = rate; app.capture.maximum = rate*120
            app.client.send({'command':'prepare','generation':app.generation})
            for offset in range(0, len(samples), rate//50):
                chunk = samples[offset:offset+rate//50]
                app.capture.callback(chunk[:,None],len(chunk),None,None)
                root.update(); time.sleep(len(chunk)/rate)
            stopped = time.monotonic(); app.stop()
            wait(lambda: not app.busy)
            text = app.text.get('1.0','end-1c')
            assert text.lower().count('teste de ditado') == 1, (app.status.get(), text)
            assert app.retained is None
            first_seconds = round(time.monotonic()-stopped,2)
            app.retained = {'rate':rate,'chunks':[samples[o:o+rate//50].copy() for o in range(0,len(samples),rate//50)], 'frames':len(samples), 'integrity':True}
            app.fail('Falha simulada para recuperar o áudio sintético')
            wait(lambda: not app.busy)
            app.recover(); wait(lambda: not app.busy)
            assert app.retained is None, app.status.get()
            assert app.text.get('1.0','end-1c').lower().count('teste de ditado') == 2
            result = {'validation':'GUI_V2_OK','microphoneOpened':False,'recoveryPassed':True,'afterStopSeconds':first_seconds,'text':text}
            result.update(frozen=bool(getattr(sys,'frozen',False)), executable=sys.executable, pid=os.getpid(), root=str(ROOT))
            print(json.dumps(result, ensure_ascii=True),flush=True)
            report = 'packaged-validation.json' if getattr(sys,'frozen',False) else 'gui-validation.json'
            (ROOT/report).write_text(json.dumps(result, ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            client = app.client; app.close(force=True)
            if client: client.wait(16)
            try: root.update()
            except tk.TclError: pass

if __name__ == '__main__': main()
