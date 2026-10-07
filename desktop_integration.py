"""Opt-in, per-user shortcuts. Never changes machine-wide startup settings."""
import base64
import os
from pathlib import Path
import subprocess
from runtime_paths import ROOT

LINK_NAME = 'Codex Dictation.lnk'

def startup_link():
    return Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup' / LINK_NAME

def startup_enabled():
    return os.name == 'nt' and startup_link().is_file()

def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"

def create_shortcut(startup=False):
    exe = ROOT / 'app-bin/Ditado Codex.exe'
    if not exe.is_file(): raise RuntimeError('PACKAGED_APP_MISSING')
    destination = _ps_quote(startup_link()) if startup else "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'Codex Dictation.lnk')"
    script = f"""$ErrorActionPreference='Stop'
$path={destination}
$shell=New-Object -ComObject WScript.Shell
$link=$shell.CreateShortcut($path)
$link.TargetPath={_ps_quote(exe)}
$link.WorkingDirectory={_ps_quote(ROOT)}
$link.IconLocation={_ps_quote(str(exe)+',0')}
$link.Description='Codex Dictation - experimental Windows voice dictation'
$link.Save()
"""
    encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    if result.returncode: raise RuntimeError('SHORTCUT_CREATION_FAILED')

def set_startup(enabled):
    if enabled: create_shortcut(startup=True)
    else: startup_link().unlink(missing_ok=True)
