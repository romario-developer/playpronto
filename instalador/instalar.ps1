# PlayPronto - instalador
# Instala tudo numa pasta própria (Python portátil incluso) e cria o botão no REAPER.
# Não mexe no Python do sistema nem em outras configurações do Windows.
param(
    [string]$Destino  = "$env:LOCALAPPDATA\PlayPronto",
    [string]$ReaperDir = "$env:APPDATA\REAPER",
    [string]$Saida    = "",
    [switch]$SemModelos,      # não baixa os modelos de IA agora (baixa no 1o uso)
    [switch]$SemPausa,        # não espera Enter no final (uso em testes)
    [switch]$Teste            # testes: não exige o REAPER fechado
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$PY_VER = "3.13.9"
$PACOTE = Split-Path -Parent $MyInvocation.MyCommand.Path
$UTF8 = New-Object System.Text.UTF8Encoding $false
$ACTION_ID = "RS7a3f9c1e2b4d6f8091a2b3c4d5e6f708192a3b4c"   # id fixo do botão PlayPronto no REAPER

function Titulo($t) { Write-Host ""; Write-Host "  $t" -ForegroundColor Yellow }
function Ok($t)     { Write-Host "    OK  $t" -ForegroundColor Green }
function Info($t)   { Write-Host "        $t" -ForegroundColor Gray }
function Falha($t) {
    Write-Host ""; Write-Host "  ERRO: $t" -ForegroundColor Red
    Write-Host "  Tire um print desta tela e envie para o suporte." -ForegroundColor Red
    if (-not $SemPausa) { Read-Host "  Aperte Enter para sair" | Out-Null }
    exit 1
}
function LerLinhas($p) { if (Test-Path $p) { return [IO.File]::ReadAllLines($p, $UTF8) } else { return @() } }
function GravarLinhas($p, $linhas) { [IO.File]::WriteAllLines($p, [string[]]$linhas, $UTF8) }

Clear-Host
Write-Host ""
Write-Host "  ==============================================" -ForegroundColor DarkYellow
Write-Host "     PlayPronto  -  Playback e VS com IA no REAPER" -ForegroundColor White
Write-Host "  ==============================================" -ForegroundColor DarkYellow
Info "Pasta do programa: $Destino"
Info "A instalação baixa uns 1,5 GB e pode levar de 5 a 20 minutos."

try {
    # ------------------------------------------------------------ checagens
    Titulo "1/6  Verificando o computador"
    if (-not [Environment]::Is64BitOperatingSystem) { Falha "O PlayPronto precisa do Windows 64 bits." }

    if (-not (Test-Path "$ReaperDir\reaper.ini")) {
        Write-Host "    Não achei o REAPER em $ReaperDir" -ForegroundColor Yellow
        Info "No REAPER: menu Options > Show REAPER resource path... mostra a pasta certa."
        $ReaperDir = (Read-Host "    Cole aqui a pasta de recursos do REAPER").Trim('"', ' ')
        if (-not (Test-Path "$ReaperDir\reaper.ini")) { Falha "Pasta do REAPER inválida: $ReaperDir" }
    }
    Ok "REAPER encontrado"

    $unidade = (Get-Item ([IO.Path]::GetPathRoot($Destino))).PSDrive
    if ($unidade -and $unidade.Free -lt 4GB) { Falha "Pouco espaço no disco $($unidade.Name): precisa de 4 GB livres." }
    Ok "Espaço em disco suficiente"

    while (-not $Teste -and (Get-Process reaper -ErrorAction SilentlyContinue)) {
        Write-Host "    Feche o REAPER para continuar (salve seus projetos antes)." -ForegroundColor Yellow
        Read-Host "    Depois de fechar, aperte Enter" | Out-Null
    }
    Ok "REAPER fechado"

    # ------------------------------------------------------------ arquivos
    Titulo "2/6  Copiando o PlayPronto"
    New-Item -ItemType Directory -Force "$Destino\reaper\icones" | Out-Null
    Copy-Item "$PACOTE\app\criar_vs.py", "$PACOTE\app\licenca.py", "$PACOTE\app\requirements.txt" $Destino -Force
    Copy-Item "$PACOTE\app\reaper\PlayPronto.lua" "$Destino\reaper" -Force
    Copy-Item "$PACOTE\app\reaper\icones\*" "$Destino\reaper\icones" -Recurse -Force
    Copy-Item "$PACOTE\desinstalar.ps1" $Destino -Force
    GravarLinhas "$Destino\Desinstalar PlayPronto.bat" @(
        "@echo off",
        "powershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0desinstalar.ps1`"",
        "pause")

    if (-not $Saida) { $Saida = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "PlayPronto" }
    New-Item -ItemType Directory -Force $Saida | Out-Null
    GravarLinhas "$Destino\config.ini" @("saida=$Saida", "reaper=$ReaperDir")
    Ok "Seus playbacks e VS vão ficar em: $Saida"

    # ------------------------------------------------------------ Python portátil
    Titulo "3/6  Preparando o motor (Python portátil)"
    $py = "$Destino\python\python.exe"
    if (-not (Test-Path $py)) {
        $zip = "$env:TEMP\playpronto-python.zip"
        Info "Baixando Python $PY_VER..."
        Invoke-WebRequest "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-embed-amd64.zip" -OutFile $zip -UseBasicParsing
        Expand-Archive $zip "$Destino\python" -Force
        Remove-Item $zip -Force
        # liberar instalação de pacotes no Python portátil
        $pth = Get-ChildItem "$Destino\python" -Filter "python*._pth" | Select-Object -First 1
        $linhas = (LerLinhas $pth.FullName) | ForEach-Object { if ($_ -match "^#\s*import site") { "import site" } else { $_ } }
        GravarLinhas $pth.FullName $linhas
        Info "Instalando o pip..."
        Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile "$env:TEMP\get-pip.py" -UseBasicParsing
        & $py "$env:TEMP\get-pip.py" --no-warn-script-location -q
        if ($LASTEXITCODE -ne 0) { Falha "Não consegui instalar o pip." }
        Remove-Item "$env:TEMP\get-pip.py" -Force
    }
    Ok "Python pronto"

    # ------------------------------------------------------------ bibliotecas
    Titulo "4/6  Instalando a inteligência artificial (parte mais demorada)"
    & $py -m pip install -r "$Destino\requirements.txt" --no-warn-script-location --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { Falha "Falha ao instalar as bibliotecas. Confira sua internet e rode de novo." }
    & $py -c "import torch, demucs, librosa, yt_dlp, soundfile, cryptography; print('    bibliotecas OK')"
    if ($LASTEXITCODE -ne 0) { Falha "As bibliotecas foram instaladas mas não abriram." }
    Ok "IA instalada"

    if (-not $SemModelos) {
        Titulo "5/6  Baixando os modelos de separação"
        & $py -c "from demucs.pretrained import get_model; get_model('htdemucs_6s'); get_model('htdemucs'); print('    modelos OK')"
        if ($LASTEXITCODE -ne 0) { Write-Host "    Não baixou agora; ele baixa sozinho no primeiro uso." -ForegroundColor Yellow }
        else { Ok "Modelos prontos" }
    } else { Titulo "5/6  Modelos: serão baixados no primeiro uso" }

    # ------------------------------------------------------------ REAPER
    Titulo "6/6  Criando o botão no REAPER"
    foreach ($s in @("", "150", "200")) {
        $origem = if ($s) { "$Destino\reaper\icones\$s\playpronto.png" } else { "$Destino\reaper\icones\playpronto.png" }
        $dst = if ($s) { "$ReaperDir\Data\toolbar_icons\$s" } else { "$ReaperDir\Data\toolbar_icons" }
        New-Item -ItemType Directory -Force $dst | Out-Null
        Copy-Item $origem "$dst\playpronto.png" -Force
    }
    Ok "Ícone instalado"

    # registra a ação (lista de ações do REAPER)
    $kb = "$ReaperDir\reaper-kb.ini"
    $lua = "$Destino\reaper\PlayPronto.lua"
    # remove só o registro antigo deste mesmo id (reinstalação); não toca em mais nada
    $linhas = @(LerLinhas $kb | Where-Object { $_ -notmatch "^SCR .*$([regex]::Escape($ACTION_ID))" })
    $linhas += "SCR 4 0 $ACTION_ID `"Custom: PlayPronto.lua`" `"$lua`""
    GravarLinhas $kb $linhas
    Ok "Ação 'PlayPronto' registrada"

    # botão na barra principal
    $menu = "$ReaperDir\reaper-menu.ini"
    $m = @(LerLinhas $menu)
    $ini = [Array]::IndexOf($m, "[Main toolbar]")
    $botao = $false
    if ($ini -lt 0) {
        # REAPER novo: a barra ainda é a padrão (não está no arquivo). Grava a barra padrão do REAPER 7
        # (mesmos botões, mesma ordem) com o PlayPronto no final.
        $padrao = @(
            "[Main toolbar]",
            "item_0=40023 New project...",
            "item_1=40025 Open project...",
            "item_2=40026 Save project",
            "item_3=40021 Project settings...",
            "item_4=40029 Undo",
            "item_5=40030 Redo",
            "item_6=40364 Enable metronome",
            "item_7=42616 Marquee selection",
            "item_8=-1",
            "item_9=40041 Enable auto-crossfade",
            "item_10=1156 Enable item and track media/razor edit grouping",
            "item_11=1162 Toggle ripple editing",
            "item_12=40070 Move envelope points with media items",
            "item_13=40145 Show arrange view grid",
            "item_14=1157 Enable snapping",
            "item_15=1135 Enable locking",
            "item_16=42618 Razor editing",
            "item_17=_$ACTION_ID PlayPronto",
            "icon_17=playpronto.png",
            "tbf_7=1",
            "tbf_11=1",
            "tbf_16=1")
        if ($m.Count -gt 0 -and $m[-1] -ne "") { $m += "" }
        GravarLinhas $menu ($m + $padrao)
        $botao = $true
        Ok "Botão adicionado na barra principal"
    } else {
        $fim = $m.Count
        for ($i = $ini + 1; $i -lt $m.Count; $i++) { if ($m[$i] -match "^\[") { $fim = $i; break } }
        while ($fim -gt $ini + 1 -and $m[$fim - 1] -eq "") { $fim-- }   # entra antes das linhas em branco
        $secao = $m[($ini + 1)..($fim - 1)]
        if (-not ($secao -match "_$ACTION_ID")) {
            $nums = $secao | Where-Object { $_ -match "^item_(\d+)=" } | ForEach-Object { [int]($_ -replace "^item_(\d+)=.*", '$1') }
            $n = if ($nums) { ($nums | Measure-Object -Maximum).Maximum + 1 } else { 0 }
            $novo = @("item_$n=_$ACTION_ID PlayPronto", "icon_$n=playpronto.png")
            $m = $m[0..($fim - 1)] + $novo + $(if ($fim -lt $m.Count) { $m[$fim..($m.Count - 1)] } else { @() })
            GravarLinhas $menu $m
        }
        $botao = $true
        Ok "Botão adicionado na barra principal"
    }

    Write-Host ""
    Write-Host "  ==============================================" -ForegroundColor Green
    Write-Host "     PlayPronto instalado!" -ForegroundColor White
    Write-Host "  ==============================================" -ForegroundColor Green
    if (-not $botao) {
        Info "Para colocar o botão na barra do REAPER (uma vez só):"
        Info " 1. Options > Customize menus/toolbars..."
        Info " 2. Escolha 'Main toolbar' > Add... > busque 'PlayPronto' > Select"
        Info " 3. Clique em Icon... e escolha o ícone 'playpronto'"
    }
    Info "Ou abra pela lista de ações (tecla ?) buscando 'PlayPronto'."
    Info "Para desinstalar: $Destino\Desinstalar PlayPronto.bat"
} catch {
    Falha $_.Exception.Message
}
if (-not $SemPausa) { Write-Host ""; Read-Host "  Aperte Enter para fechar" | Out-Null }
