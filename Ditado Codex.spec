from PyInstaller.utils.hooks import collect_data_files

a = Analysis(['gui.py'], pathex=[SPECPATH],
    datas=collect_data_files('customtkinter'),
    hiddenimports=['pystray._win32'],
    excludes=['matplotlib', 'pandas', 'scipy', 'pytest', 'IPython'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
    name='Ditado Codex', console=False, icon='assets/ditado-codex.ico',
    version='version-info.txt', upx=False)
b = Analysis(['live.py'], pathex=[SPECPATH], hiddenimports=['numpy'],
    excludes=['matplotlib', 'pandas', 'pytest', 'IPython'])
broker_pyz = PYZ(b.pure)
broker = EXE(broker_pyz, b.scripts, [], exclude_binaries=True,
    name='Ditado Codex Service', console=True, icon='assets/ditado-codex.ico', upx=False)
coll = COLLECT(exe, broker, a.binaries, a.datas, b.binaries, b.datas,
    name='app-bin', upx=False)
