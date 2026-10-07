import json
from pathlib import Path
import tempfile
import unittest
from export_bundle_manifest import digest
from package_release import collect_files,safe_member

class PackageTests(unittest.TestCase):
    def test_extra_files_and_developer_settings_are_not_selected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'source';stage=Path(d)/'stage'
            (root/'target/release').mkdir(parents=True); (stage/'app-bin').mkdir(parents=True)
            binary=root/'target/release/codex-app-server.exe';binary.write_bytes(b'validated-test-binary')
            exe=stage/'app-bin/App.exe';exe.write_bytes(b'declared-test-executable')
            (root/'README.md').write_text('reviewed')
            (root/'release-files.json').write_text(json.dumps(['README.md','validated-build.json']))
            (root/'validated-build.json').write_text(json.dumps({'sha256':digest(binary)}))
            (stage/'bundle-files.json').write_text(json.dumps({'app-bin/App.exe':digest(exe)}))
            for name in ('app-bin/debug.log','tests/transcript.txt','assets/.env.local','userdata/settings.json'):
                p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('private sentinel')
            selected=collect_files(root,stage)
            self.assertEqual(set(selected),{'app-bin/App.exe','README.md','validated-build.json','target/release/codex-app-server.exe'})
            exe.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'Build output changed'):collect_files(root,stage)
    def test_path_traversal_and_private_names_are_rejected(self):
        for name in ('../auth.json','app-bin/.env.local','C:/private.txt','userdata/credentials.json','a\\b'):
            with self.assertRaises(RuntimeError):safe_member(name)

if __name__=='__main__':unittest.main()
