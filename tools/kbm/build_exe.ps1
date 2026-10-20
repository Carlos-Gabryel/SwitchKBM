# Gera dist\SwitchKBM.exe (flet pack/PyInstaller, onefile, sem console) com o firmware switch-side embutido
param([switch]$SkipFirmware)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo

if (-not $SkipFirmware) {
    # processo filho: o export.ps1 do ESP-IDF altera o PATH/python
    powershell -NoProfile -ExecutionPolicy Bypass -Command ". '$repo\tools\idf-env.ps1'; idf.py -C '$repo\switch-side' build; exit `$LASTEXITCODE"
    if ($LASTEXITCODE -ne 0) { throw "build do firmware falhou" }
}

# firmware preparado em build\firmware (caminhos relativos do flasher_args.json)
$fwSrc = "$repo\switch-side\build"
$fwDst = "$repo\build\firmware"
if (Test-Path $fwDst) { Remove-Item -Recurse -Force $fwDst }
New-Item -ItemType Directory -Force $fwDst | Out-Null
$manifest = Get-Content "$fwSrc\flasher_args.json" -Raw | ConvertFrom-Json
$rels = @("flasher_args.json") + @($manifest.flash_files.PSObject.Properties | ForEach-Object { $_.Value })
foreach ($rel in $rels) {
    $src = Join-Path $fwSrc $rel
    if (-not (Test-Path $src)) { throw "firmware ausente: $src" }
    $dst = Join-Path $fwDst $rel
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    Copy-Item $src $dst
}

python -m pip install --quiet -r "$repo\tools\kbm\requirements.txt"

# o flet pack apaga a pasta build\ do diretorio atual (onde esta o firmware): roda numa pasta de trabalho propria
$work = "$repo\.pack"
New-Item -ItemType Directory -Force $work | Out-Null
$kbm = "$repo\tools\kbm"
$flet = "import sys; from flet_cli.cli import main; sys.argv[0] = 'flet'; main()"
$buildArgs = @("--paths=$kbm",
    "--hidden-import=kbm_bridge", "--hidden-import=winput", "--hidden-import=proto", "--hidden-import=mapping",
    "--hidden-import=flasher", "--hidden-import=runners", "--hidden-import=controller", "--hidden-import=capture",
    "--hidden-import=bindings", "--hidden-import=profiles", "--hidden-import=serial",
    "--hidden-import=serial.tools.list_ports", "--hidden-import=esptool",
    "--collect-data=esptool", "--collect-submodules=esptool", "--collect-submodules=ui")
$packArgs = @("-c", $flet, "pack", "$kbm\kbm_app.py", "--name", "SwitchKBM", "--icon", "$kbm\ui\assets\icon.ico", "-y",
    "--distpath", "$work\dist", "--product-name", "Switch KBM", "--file-description", "Switch KBM",
    "--product-version", "1.0.0", "--file-version", "1.0.0.0", "--company-name", "Carlos Gabryel",
    "--copyright", "(c) 2026 Carlos Gabryel - GPL-3.0",
    "--add-data", "$fwDst;firmware", "$kbm\ui\assets;ui\assets")
foreach ($a in $buildArgs) { $packArgs += "--pyinstaller-build-args=$a" }
$env:PYTHONPATH = $kbm
Push-Location $work
try {
    python @packArgs
    if ($LASTEXITCODE -ne 0) { throw "flet pack falhou" }
} finally { Pop-Location }
# o flet pack APAGA a pasta --distpath inteira: gera em .pack\dist e copia so o exe para dist
if (-not (Test-Path "$work\dist\SwitchKBM.exe")) { throw "exe nao gerado" }
New-Item -ItemType Directory -Force "$repo\dist" | Out-Null
Copy-Item -Force "$work\dist\SwitchKBM.exe" "$repo\dist\SwitchKBM.exe"
Write-Host "OK: $repo\dist\SwitchKBM.exe"
