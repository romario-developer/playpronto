# PlayPronto

Playback e VS com IA direto no REAPER. Um botão: cola o link do YouTube (ou escolhe um arquivo do PC),
a IA separa os instrumentos e o projeto abre pronto no REAPER.

- **VS**: bateria, baixo, guitarra/violão, teclado/piano, outros + click + guias (original e voz).
- **Playback**: só tira a voz e já exporta MP3 320k.
- **Tom**: -12 a +12 semitons sem mexer na bateria e percussão.
- **BPM**: detectado sozinho (ou informado) e click alinhado às batidas.

## Estrutura

| Caminho | O que é |
|---|---|
| `criar_vs.py` | Motor: download, separação (Demucs), tom (Rubber Band), click, projeto `.RPP` |
| `reaper/PlayPronto.lua` | O botão/janela dentro do REAPER (ReaScript) |
| `reaper/icones/` | Ícone da barra de ferramentas (100/150/200%) e logo — gerados por `gerar_icone.py` |
| `PlayPronto.bat` | Usar sem o REAPER aberto (pergunta modo, link, BPM e tom) |
| `instalador/` | Instalador para clientes (`instalar.ps1`, `desinstalar.ps1`) e `gerar_pacote.ps1` |
| `video/` | Gerador do vídeo de anúncio (`fazer_video.py`), narração e vídeos prontos |
| `requirements.txt` | Bibliotecas do motor (vão no instalador) |
| `requirements-dev.txt` | + ferramentas de desenvolvimento |

## Configurar em outro computador

Precisa de [Python 3.13](https://www.python.org/downloads/) e [Git](https://git-scm.com/).

```bash
git clone https://github.com/romario-developer/playpronto.git
cd playpronto
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

No REAPER: **Actions → Show action list → New action → Load ReaScript** e escolha `reaper\PlayPronto.lua`
desta pasta. Para o ícone, copie `reaper\icones\playpronto.png` (e as pastas `150` e `200`) para
`%APPDATA%\REAPER\Data\toolbar_icons\`.

Os resultados ficam em `VS\` (fora do git).

## Gerar o instalador para clientes

```bash
powershell -ExecutionPolicy Bypass -File instalador\gerar_pacote.ps1
```

Sai em `dist\PlayPronto-Instalador.zip`. O cliente extrai e roda `Instalar PlayPronto.bat`
(baixa Python portátil + IA, ~1,2 GB, e cria o botão no REAPER).

## Vídeo de anúncio

```bash
cd video
..\.venv\Scripts\python fazer_video.py               # vídeo completo
..\.venv\Scripts\python fazer_video.py --previa      # só quadros PNG para conferir
..\.venv\Scripts\python fazer_video.py --sem-narracao
```

## Aviso

Use apenas músicas que você tem direito de usar.
