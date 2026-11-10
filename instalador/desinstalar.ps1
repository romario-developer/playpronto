# PlayPronto - desinstalador. Seus playbacks/VS (pasta de saída) NÃO são apagados.
param([switch]$Sim)  # -Sim: não pergunta (testes)
$ErrorActionPreference = "Continue"
$Destino = Split-Path -Parent $MyInvocation.MyCommand.Path
$UTF8 = New-Object System.Text.UTF8Encoding $false
$ACTION_ID = "RS7a3f9c1e2b4d6f8091a2b3c4d5e6f708192a3b4c"

$ReaperDir = "$env:APPDATA\REAPER"
if (Test-Path "$Destino\config.ini") {
    foreach ($l in [IO.File]::ReadAllLines("$Destino\config.ini", $UTF8)) { if ($l -match "^reaper=(.+)$") { $ReaperDir = $Matches[1] } }
}

Write-Host ""
Write-Host "  Desinstalar PlayPronto" -ForegroundColor Yellow
if (-not $Sim -and (Read-Host "  Tem certeza? (s/n)") -ne "s") { exit }
while (-not $Sim -and (Get-Process reaper -ErrorAction SilentlyContinue)) { Read-Host "  Feche o REAPER e aperte Enter" | Out-Null }

$kb = "$ReaperDir\reaper-kb.ini"
if (Test-Path $kb) {
    $l = [IO.File]::ReadAllLines($kb, $UTF8) | Where-Object { $_ -notmatch [regex]::Escape($ACTION_ID) }
    [IO.File]::WriteAllLines($kb, [string[]]$l, $UTF8)
}
$menu = "$ReaperDir\reaper-menu.ini"
if (Test-Path $menu) {
    $m = [IO.File]::ReadAllLines($menu, $UTF8)
    $nums = $m | Where-Object { $_ -match "^item_(\d+)=_$ACTION_ID" } | ForEach-Object { $_ -replace "^item_(\d+)=.*", '$1' }
    $m = $m | Where-Object { $l = $_; -not ($nums | Where-Object { $l -match "^(item|icon)_$_=" }) }
    [IO.File]::WriteAllLines($menu, [string[]]$m, $UTF8)
}
foreach ($s in @("", "\150", "\200")) { Remove-Item "$ReaperDir\Data\toolbar_icons$s\playpronto.png" -ErrorAction SilentlyContinue }

# apaga a pasta do programa depois que este script terminar
Start-Process cmd.exe -ArgumentList "/c ping -n 4 127.0.0.1 >nul & rmdir /s /q `"$Destino`"" -WindowStyle Hidden
Write-Host "  PlayPronto removido. Seus playbacks continuam na pasta Documentos\PlayPronto." -ForegroundColor Green
