# Prepara o Bluepad32 (submodulo) para o ds5-side: baixa submodulos e copia o BTstack
# para third_party/bluepad32/src/components/btstack (ignorado pelo git do submodulo).
# NAO altera o ESP-IDF (IDF_PATH aponta para o src do Bluepad32 so durante o script).
$root = Split-Path -Parent $PSScriptRoot
git -C $root submodule update --init --recursive
$env:IDF_PATH = "$root\third_party\bluepad32\src"
Push-Location "$root\third_party\bluepad32\external\btstack\port\esp32"
python integrate_btstack.py | Select-Object -Last 1
Pop-Location
