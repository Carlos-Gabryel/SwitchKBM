# Gera dist\SwitchKBM.exe (PyInstaller, onefile, sem console)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo
python -m pip install --quiet pyinstaller pyserial
python -m PyInstaller --noconfirm --onefile --windowed --name SwitchKBM `
    --distpath "$repo\dist" --workpath "$repo\build\pyinstaller" --specpath "$repo\build\pyinstaller" `
    --paths "$repo\tools\kbm" `
    --hidden-import kbm_bridge --hidden-import winput --hidden-import proto --hidden-import mapping `
    --hidden-import serial --hidden-import serial.tools.list_ports `
    "$repo\tools\kbm\kbm_app.py"
if (Test-Path "$repo\dist\SwitchKBM.exe") { Write-Host "OK: $repo\dist\SwitchKBM.exe" } else { throw "exe nao gerado" }
