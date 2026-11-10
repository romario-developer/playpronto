# Monta dist\PlayPronto-Instalador (pasta + .zip) para enviar aos clientes.
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dist = "$raiz\dist\PlayPronto-Instalador"
$BOM = New-Object System.Text.UTF8Encoding $true

if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force "$dist\app\reaper\icones" | Out-Null

Copy-Item "$raiz\criar_vs.py", "$raiz\requirements.txt" "$dist\app"
Copy-Item "$raiz\reaper\PlayPronto.lua" "$dist\app\reaper"
foreach ($s in @("", "150", "200")) {
    $o = if ($s) { "$raiz\reaper\icones\$s" } else { "$raiz\reaper\icones" }
    $d = if ($s) { "$dist\app\reaper\icones\$s" } else { "$dist\app\reaper\icones" }
    New-Item -ItemType Directory -Force $d | Out-Null
    Copy-Item "$o\playpronto.png" $d
}
Copy-Item "$raiz\reaper\icones\logo.png" "$dist\app\reaper\icones"

# .ps1 com BOM: o PowerShell 5 do Windows só lê acentos certo assim
foreach ($f in "instalar.ps1", "desinstalar.ps1") {
    [IO.File]::WriteAllText("$dist\$f", [IO.File]::ReadAllText("$raiz\instalador\$f"), $BOM)
}

[IO.File]::WriteAllText("$dist\Instalar PlayPronto.bat", @"
@echo off
title Instalador PlayPronto
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
"@)

[IO.File]::WriteAllText("$dist\LEIA-ME.txt", @"
PlayPronto - Playback e VS com IA direto no REAPER
===================================================

INSTALAR
1. Extraia este .zip numa pasta (botão direito > Extrair tudo).
2. Dê dois cliques em "Instalar PlayPronto.bat".
3. Se o Windows mostrar "O Windows protegeu o computador", clique em
   "Mais informações" > "Executar assim mesmo".
4. Espere terminar (5 a 20 minutos, baixa ~1,5 GB). Precisa de internet.

REQUISITOS
- Windows 10 ou 11, 64 bits
- REAPER instalado (abra ele pelo menos uma vez antes de instalar)
- 4 GB livres no disco, 8 GB de memória RAM recomendados

USAR
- No REAPER, clique no botão laranja PlayPronto (ou busque "PlayPronto"
  na lista de ações).
- Escolha VS (instrumentos separados) ou Playback (só tira a voz).
- Copie o link da música ou escolha um arquivo do PC e clique.
- Os arquivos ficam em Documentos\PlayPronto.

DESINSTALAR
- Rode "Desinstalar PlayPronto.bat" na pasta %LOCALAPPDATA%\PlayPronto.

AVISO
Use apenas músicas que você tem direito de usar. O uso das faixas
geradas é responsabilidade do usuário.
"@.Replace("`n", "`r`n"), $BOM)

$zip = "$raiz\dist\PlayPronto-Instalador.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive "$dist\*" $zip
"Pacote gerado: $zip ($([math]::Round((Get-Item $zip).Length / 1KB)) KB)"
