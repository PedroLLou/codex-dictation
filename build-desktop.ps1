param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .\.venv\Scripts\python.exe app_identity.py
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar o icone.' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath $OutputDirectory --workpath package-build 'Ditado Codex.spec'
if ($LASTEXITCODE -ne 0) { throw 'Falha ao empacotar a interface.' }
& .\.venv\Scripts\python.exe export_bundle_manifest.py $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar manifesto de arquivos.' }
