# Gera dist\SwitchKBM.exe (flet pack/PyInstaller, onefile, sem console) com o firmware switch-side embutido.
# Envolve o build.py (que e multiplataforma). -SkipFirmware pula a recompilacao do firmware.
param([switch]$SkipFirmware)
$ErrorActionPreference = "Stop"
$extra = @()
if ($SkipFirmware) { $extra += "--skip-firmware" }
python "$PSScriptRoot\build.py" @extra
if ($LASTEXITCODE -ne 0) { throw "build falhou" }
