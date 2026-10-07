"""Teste de ciclo de vida Win32, sem áudio, teclas sintéticas ou texto de campos."""
import json
import threading
from win_integration import _focused_uia_identity, Hotkeys, InstanceGuard, Tray

def main():
    errors = []; results = []
    def read():
        try: results.append(_focused_uia_identity() is not None)
        except Exception as exc: errors.append(type(exc).__name__)
    thread = threading.Thread(target=read); thread.start(); thread.join(8); read()
    assert not thread.is_alive(), 'UIA_TIMEOUT'
    guard = InstanceGuard('Ditado Codex · teste interno')
    duplicate = InstanceGuard('Ditado Codex · teste interno')
    assert guard.acquire()
    assert not duplicate.acquire()
    guard.release()
    hotkeys = Hotkeys(lambda action: None, 'Ctrl+Alt+Shift+F12')
    hotkeys.start(); hotkeys.set_active(True); hotkeys.set_active(False); hotkeys.close()
    tray = Tray(lambda action: None)
    tray_started = tray.start(); tray.update(); tray.close()
    result = {'validation':'WINDOWS_LIFECYCLE_OK','uiaCalls':len(results),'uiaErrors':errors,'trayStarted':tray_started,'inputSent':False,'microphoneOpened':False}
    print(json.dumps(result),flush=True)
    assert not errors, errors

if __name__ == '__main__': main()
