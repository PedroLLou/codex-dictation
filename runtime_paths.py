"""Paths shared by source and the packaged desktop interface."""
from pathlib import Path
import sys

ROOT = (Path(sys.executable).resolve().parent.parent if getattr(sys, 'frozen', False)
        else Path(__file__).resolve().parent)

def backend_python():
    return str(ROOT / '.venv/Scripts/python.exe') if getattr(sys, 'frozen', False) else sys.executable

def backend_command():
    if getattr(sys, 'frozen', False):
        service = ROOT / 'app-bin/Ditado Codex Service.exe'
        if not service.is_file(): raise RuntimeError('PACKAGED_SERVICE_MISSING')
        return [str(service)]
    return [sys.executable, str(ROOT / 'live.py')]
