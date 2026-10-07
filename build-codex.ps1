param([string]$SourceDirectory = 'C:\cd-build')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$revision = 'a956835d020762cb2b570053af06f643a11c0ecc'
if (Test-Path -LiteralPath $SourceDirectory) { throw 'Use a new, empty source directory. Existing checkouts are not modified.' }
git -c core.longpaths=true clone --filter=blob:none --no-checkout https://github.com/openai/codex.git $SourceDirectory
if ($LASTEXITCODE -ne 0) { throw 'Clone failed.' }
git -C $SourceDirectory -c core.longpaths=true checkout $revision
if ($LASTEXITCODE -ne 0) { throw 'Checkout failed.' }
git -C $SourceDirectory apply (Join-Path $projectRoot 'patches\codex-dictation.patch')
if ($LASTEXITCODE -ne 0) { throw 'Dictation patch did not apply.' }
$env:CARGO_PROFILE_RELEASE_DEBUG='0'
$env:CARGO_PROFILE_RELEASE_LTO='false'
$env:CARGO_PROFILE_RELEASE_CODEGEN_UNITS='16'
$env:CARGO_BUILD_JOBS='4'
Push-Location (Join-Path $SourceDirectory 'codex-rs')
try {
    cargo build --locked --release -p codex-app-server --bin codex-app-server
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    # Required guard test before trusting a newly built binary.
    cargo test --locked --release -p codex-core --test all dictation_fork -- --nocapture
    if ($LASTEXITCODE -ne 0) { throw 'Dictation isolation test failed.' }
    $binary=Join-Path $SourceDirectory 'codex-rs\target\release\codex-app-server.exe'
    $destination=Join-Path $projectRoot 'target\release'
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Copy-Item -LiteralPath $binary -Destination (Join-Path $destination 'codex-app-server.exe')
    $stamp=@{binary='target/release/codex-app-server.exe';sha256=(Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLower();validation='cargo test --release -p codex-core --test all dictation_fork'}
    [IO.File]::WriteAllText((Join-Path $projectRoot 'validated-build.json'),($stamp | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
} finally { Pop-Location }
