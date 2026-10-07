# Dependency source and rebuild information

Codex app-server: https://github.com/openai/codex/tree/a956835d020762cb2b570053af06f643a11c0ecc . Complete changes: `../patches/codex-dictation.patch`. Copyright/license: `codex-NOTICE` and `codex-LICENSE`. This distribution does not use a stock unmodified app-server.

Python runtime: https://www.python.org/downloads/release/python-31315/ . Python/Tcl/Tk and package license texts are included by the bundle and `python-licenses/`.

PyAV 16.1.0: https://github.com/PyAV-Org/PyAV/tree/v16.1.0 . Wheel build/dependency scripts: https://github.com/PyAV-Org/PyAV/blob/v16.1.0/scripts/build-deps . The unmodified PyAV Windows wheel contains dynamically loaded FFmpeg libraries. FFmpeg reports version **8.0.1**, license **LGPL version 3 or later**. Upstream corresponding source: https://ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz . A copy of the source archive and PyAV sources accompanies the GitHub release in `third-party-sources.zip`.

pystray 0.19.5: https://github.com/moses-palmer/pystray/tree/v0.19.5 (LGPL-3.0). Source archive also accompanies the release. GPL/LGPL texts are under `python-licenses/pystray/`.

The FFmpeg libraries are unmodified shared libraries. Their reported configuration is in `FFMPEG-BUILD.txt`; follow PyAV's upstream Windows wheel build workflow and dependency scripts to rebuild. They live under `app-bin/_internal/av.libs/` and can be replaced with compatible rebuilt DLLs. pystray is a Python dependency: replace/rebuild it in the virtual environment and rerun `build-desktop.ps1`. This project does not forbid debugging or reverse engineering needed to modify these dependencies.

Other dependencies and versions: `PYTHON-DEPENDENCIES.md` and `../requirements-lock.txt`. Copyright/license texts: `python-licenses/`. Build-only PyInstaller: https://pyinstaller.org/ , GPL-2.0 with bootloader exception; the packaged executable does not change the app's source license.
