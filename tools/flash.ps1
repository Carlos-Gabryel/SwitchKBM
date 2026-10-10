# Grava e abre o monitor serial. Uso: .\tools\flash.ps1 [-Port COM5]
param([string]$Port)
$root = Split-Path -Parent $PSScriptRoot
. "$PSScriptRoot\idf-env.ps1"

if (-not $Port) {
    $ports = @(Get-CimInstance Win32_PnPEntity |
        Where-Object { $_.Name -match '\((COM\d+)\)' } |
        ForEach-Object { [pscustomobject]@{ Port = $Matches[1]; Name = $_.Name } })
    if ($ports.Count -eq 1) {
        $Port = $ports[0].Port
        Write-Host "Porta detectada: $Port ($($ports[0].Name))"
    } else {
        Write-Error ("Nao foi possivel escolher a porta automaticamente. Use -Port COMx. Portas encontradas:`n" +
            (($ports | ForEach-Object { "  $($_.Port)  $($_.Name)" }) -join "`n"))
        exit 1
    }
}
idf.py -C "$root\switch-side" -p $Port flash monitor
