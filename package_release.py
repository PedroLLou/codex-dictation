"""Fresh release from explicit reviewed manifests, never directory scans."""
from pathlib import Path
import json
import shutil
import tempfile
import zipfile
from export_bundle_manifest import digest

ROOT=Path(__file__).resolve().parent
VERSION='0.3.0'

def safe_member(name):
    path=Path(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name: raise RuntimeError('Unsafe release path')
    if path.name.lower().startswith('.env') or path.name.lower() in {'auth.json','credentials.json'}: raise RuntimeError('Private file rejected')
    return path

def collect_files(root,stage):
    files={}
    runtime=json.loads((stage/'bundle-files.json').read_text(encoding='utf-8'))
    for name,expected in runtime.items():
        relative=safe_member(name)
        if relative.parts[0]!='app-bin': raise RuntimeError('Invalid runtime manifest member')
        source=stage/relative
        if digest(source)!=expected: raise RuntimeError('Build output changed: '+name)
        files[name]=source
    for name in json.loads((root/'release-files.json').read_text(encoding='utf-8')):
        safe_member(name)
        source=root/name
        if name=='README.md' and (root/'README-public.md').is_file(): source=root/'README-public.md'
        if not source.is_file(): raise RuntimeError('Missing reviewed release file: '+name)
        files[name]=source
    stamp=json.loads((root/'validated-build.json').read_text(encoding='utf-8-sig'))
    binary=root/'target/release/codex-app-server.exe'
    if digest(binary)!=stamp['sha256']: raise RuntimeError('Unvalidated Codex binary')
    files['target/release/codex-app-server.exe']=binary
    return files

def main():
    stage=ROOT/'release-staging'/f'v{VERSION}'
    files=collect_files(ROOT,stage)
    output=ROOT/'release-assets'; output.mkdir(exist_ok=True)
    archive=output/f'codex-dictation-{VERSION}-windows-x64.zip'
    with tempfile.TemporaryDirectory(prefix='clean-release-',dir=ROOT/'release-staging') as directory:
        clean=Path(directory)
        for name,source in files.items():
            target=clean/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target)
        (clean/'userdata').mkdir()
        (clean/'userdata/settings.json').write_text('{"language":"en"}\n',encoding='utf-8')
        (clean/'Start Codex Dictation.vbs').write_text('Set fso = CreateObject("Scripting.FileSystemObject")\nSet shell = CreateObject("WScript.Shell")\nfolder = fso.GetParentFolderName(WScript.ScriptFullName)\nshell.CurrentDirectory = folder\nshell.Run Chr(34) & folder & "\\app-bin\\Ditado Codex.exe" & Chr(34), 1, False\n',encoding='ascii')
        names=sorted(list(files)+['userdata/settings.json','Start Codex Dictation.vbs'])
        manifest={name:digest(clean/name) for name in names}
        (clean/'release-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding='utf-8')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for name in names+['release-manifest.json']: z.write(clean/name,Path(f'codex-dictation-{VERSION}')/name)
    lines=[f'{digest(archive)}  {archive.name}']
    vendor=output/'third-party-sources.zip'
    if vendor.is_file(): lines.append(f'{digest(vendor)}  {vendor.name}')
    (output/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'files':len(names)+1,'sha256':digest(archive)}))

if __name__=='__main__': main()
