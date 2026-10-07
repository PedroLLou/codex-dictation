"""Collect installed dependency license texts, never credentials or user files."""
import importlib.metadata as metadata
from pathlib import Path
import shutil
from runtime_paths import ROOT

def main():
    directory=ROOT/'third-party/python-licenses'; directory.mkdir(parents=True,exist_ok=True)
    inventory=[]
    build_only={'pyinstaller','pyinstaller-hooks-contrib','pefile','altgraph','pywin32-ctypes','setuptools'}
    for dist in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        name=dist.metadata['Name']
        if name.lower() in build_only: continue
        license=dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'See bundled license text'
        if len(license)>150: license='See bundled license text'
        inventory.append(f'- {name} {dist.version}: {license}')
        for file in dist.files or []:
            path=Path(str(file))
            if '.dist-info' not in str(file): continue
            if 'licenses' not in path.parts and not any(word in path.name.lower() for word in ('license','copying','notice')): continue
            source=Path(dist.locate_file(file))
            if not source.is_file(): continue
            target=directory/name/Path(*path.parts[1:]); target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
    (ROOT/'third-party/PYTHON-DEPENDENCIES.md').write_text('# Bundled Python dependencies\n\n'+'\n'.join(inventory)+'\n',encoding='utf-8')

if __name__=='__main__': main()
