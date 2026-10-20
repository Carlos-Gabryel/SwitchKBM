# Gera dist\SwitchKBM.exe (PyInstaller, onefile, sem console) com o firmware switch-side embutido
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

python -m pip install --quiet pyinstaller pyserial esptool==4.8.1
python -m PyInstaller --noconfirm --onefile --windowed --name SwitchKBM `
    --distpath "$repo\dist" --workpath "$repo\build\pyinstaller" --specpath "$repo\build\pyinstaller" `
    --paths "$repo\tools\kbm" `
    --hidden-import kbm_bridge --hidden-import winput --hidden-import proto --hidden-import mapping `
    --hidden-import flasher --hidden-import esptool --collect-data esptool --collect-submodules esptool `
    --hidden-import serial --hidden-import serial.tools.list_ports `
    --add-data "$fwDst;firmware" `
    "$repo\tools\kbm\kbm_app.py"
if (Test-Path "$repo\dist\SwitchKBM.exe") { Write-Host "OK: $repo\dist\SwitchKBM.exe" } else { throw "exe nao gerado" }
