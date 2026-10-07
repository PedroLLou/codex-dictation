"""Freeze exact PyInstaller COLLECT outputs, never a directory scan."""
import ast
import hashlib
import json
from pathlib import Path, PureWindowsPath
import sys

def digest(path):
    sha=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): sha.update(chunk)
    return sha.hexdigest()

def main():
    output=Path(sys.argv[1] if len(sys.argv)>1 else 'dist').resolve()
    declared=ast.literal_eval(Path('package-build/Ditado Codex/COLLECT-00.toc').read_text(encoding='utf-8'))[0]
    files={}
    for name,source,kind in declared:
        parts=PureWindowsPath(name)
        if parts.is_absolute() or '..' in parts.parts: raise RuntimeError('Unsafe build output path')
        relative=Path(*parts.parts)
        if kind!='EXECUTABLE': relative=Path('_internal')/relative
        relative=Path('app-bin')/relative
        if not (output/relative).is_file(): raise RuntimeError('Missing declared build output: '+str(relative))
        files[relative.as_posix()]=digest(output/relative)
    (output/'bundle-files.json').write_text(json.dumps(files,indent=2,sort_keys=True),encoding='utf-8')
    print('Build manifest:',len(files),'declared files')

if __name__=='__main__': main()
