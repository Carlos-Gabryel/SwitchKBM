# Ativa o ambiente ESP-IDF. Uso (dot-source): . .\tools\idf-env.ps1
$env:IDF_PATH = "C:\Espressif\esp-idf"
if ($env:MSYSTEM) { Remove-Item Env:MSYSTEM -ErrorAction SilentlyContinue }
. "$env:IDF_PATH\export.ps1"
