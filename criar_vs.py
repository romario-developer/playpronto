"""
Criador de VS: link do YouTube -> faixas separadas por IA (Demucs) + click + projeto do Reaper.

Uso:
    .venv\\Scripts\\python criar_vs.py "https://www.youtube.com/watch?v=..."
    .venv\\Scripts\\python criar_vs.py "link" --bpm 128      (força o BPM se a detecção errar)
    .venv\\Scripts\\python criar_vs.py "C:\\musica.mp3"        (também aceita arquivo local)

Saída: pasta VS\\<nome da música>\\ com os WAVs e o arquivo .RPP para abrir no Reaper.
"""
import argparse
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import soundfile as sf

RAIZ = Path(__file__).resolve().parent


def pasta_saida():
    """Instalado: lê config.ini (saida=...). Desenvolvimento: pasta VS ao lado do script."""
    cfg = RAIZ / "config.ini"
    if cfg.exists():
        for linha in cfg.read_text(encoding="utf-8").splitlines():
            if linha.strip().lower().startswith("saida="):
                return Path(linha.split("=", 1)[1].strip())
    return RAIZ / "VS"


SAIDA = pasta_saida()
SR = 44100
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# nome da faixa no Demucs -> (nome no Reaper, cor RGB)
FAIXAS = {
    "drums": ("Bateria", (220, 80, 60)),
    "bass": ("Baixo", (230, 160, 40)),
    "guitar": ("Guitarra/Violao", (80, 170, 80)),
    "piano": ("Teclado/Piano", (70, 130, 220)),
    "other": ("Outros (sanfona, cordas...)", (150, 100, 200)),
}


def log(msg):
    print(f"\n>> {msg}", flush=True)


def nome_seguro(txt):
    txt = re.sub(r'[<>:"/\\|?*]', "", txt).strip()
    return txt[:80] or "musica"


# ---------------------------------------------------------------- 1. baixar
def baixar(link, destino_tmp):
    import yt_dlp

    destino_tmp.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(destino_tmp / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "ffmpeg_location": FFMPEG,
        "quiet": False,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(link, download=True)
        arquivo = Path(ydl.prepare_filename(info))
    return arquivo, info.get("title") or arquivo.stem


def para_wav(origem, wav):
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(origem), "-ac", "2", "-ar", str(SR), str(wav)],
        check=True,
    )


# ---------------------------------------------------------------- 2. separar
def separar(wav_original, pasta, modo="vs", tom=0):
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    # VS: 6 faixas (com guitarra e piano). Playback: modelo de 4 faixas, só precisamos da voz.
    nome_modelo = "htdemucs_6s" if modo == "vs" else "htdemucs"
    log(f"Carregando modelo de IA ({nome_modelo})... na 1a vez ele baixa ~80MB")
    model = get_model(nome_modelo)
    model.eval()

    audio, sr = sf.read(str(wav_original), dtype="float32", always_2d=True)
    wav = torch.from_numpy(audio.T)  # (canais, amostras)
    ref = wav.mean(0)
    media, desvio = ref.mean(), ref.std() + 1e-8
    wav_n = (wav - media) / desvio

    log("Separando instrumentos (no processador demora alguns minutos)..." if modo == "vs"
        else "Separando a voz (no processador demora alguns minutos)...")
    with torch.no_grad():
        fontes = apply_model(model, wav_n[None], device="cpu", shifts=1, split=True, overlap=0.25, progress=True)[0]
    fontes = fontes * desvio + media

    arquivos = {}
    if modo == "vs":
        for nome, fonte in zip(model.sources, fontes):
            caminho = pasta / f"{nome}.wav"
            sf.write(str(caminho), fonte.numpy().T, sr, subtype="PCM_24")
            arquivos[nome] = caminho
        return arquivos

    # playback = música original menos a voz (mantém 100% do instrumental, sem perder nada)
    fontes_np = dict(zip(model.sources, (f.numpy().T for f in fontes)))
    voz = fontes_np["vocals"]
    playback = audio[: len(voz)] - voz
    pico = np.abs(playback).max()
    if pico > 0.999:  # evita distorcer
        playback = playback * (0.999 / pico)
    salvar = [("vocals", voz), ("playback", playback), ("drums", fontes_np["drums"])]
    if tom:  # para mudar o tom precisamos das partes separadas (o playback é remontado depois)
        salvar += [("bass", fontes_np["bass"]), ("other", fontes_np["other"])]
    for nome, dado in salvar:
        caminho = pasta / f"{nome}.wav"
        sf.write(str(caminho), dado, sr, subtype="PCM_24")
        arquivos[nome] = caminho
    return arquivos


# ---------------------------------------------------------------- 2b. mudar o tom
def _rubberband(origem, destino, semitons, voz=False):
    filtro = f"rubberband=pitch={2 ** (semitons / 12):.6f}:pitchq=quality"
    if voz:
        filtro += ":formant=preserved"  # voz não fica "de esquilo"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(origem), "-af", filtro,
                    "-c:a", "pcm_s24le", str(destino)], check=True)


def _ler(p, n=None):
    a, sr = sf.read(str(p), dtype="float32", always_2d=True)
    if n is not None:
        a = a[:n] if len(a) >= n else np.pad(a, ((0, n - len(a)), (0, 0)))
    return a, sr


def aplicar_tom(pasta, arquivos, modo, tom):
    """Muda o tom das partes melódicas. Bateria e percussão ficam intactas.
    A faixa 'other' (sanfona, cordas, percussão solta...) é dividida em parte harmônica
    (muda o tom) e parte percussiva (fica igual)."""
    import librosa

    log(f"Mudando o tom ({tom:+d} semitons) sem mexer na bateria e percussão...")
    n = sf.info(str(arquivos["drums"])).frames
    melodicas = [k for k in ("bass", "guitar", "piano", "vocals") if k in arquivos]
    for k in melodicas:
        tmp = pasta / f"_{k}_tom.wav"
        _rubberband(arquivos[k], tmp, tom, voz=(k == "vocals"))
        a, sr = _ler(tmp, n)
        sf.write(str(arquivos[k]), a, sr, subtype="PCM_24")
        tmp.unlink()

    # 'other': separa harmônico x percussivo
    a, sr = _ler(arquivos["other"], n)
    harm = np.zeros_like(a)
    perc = np.zeros_like(a)
    for c in range(a.shape[1]):
        S = librosa.stft(a[:, c], n_fft=4096, hop_length=1024)
        Sh, Sp = librosa.decompose.hpss(S, margin=2.0)
        resto = S - Sh - Sp  # o que não é claramente nenhum dos dois vai junto com o harmônico
        harm[:, c] = librosa.istft(Sh + resto, hop_length=1024, length=n)
        perc[:, c] = librosa.istft(Sp, hop_length=1024, length=n)
    tmp_h, tmp_h2 = pasta / "_other_harm.wav", pasta / "_other_harm_tom.wav"
    sf.write(str(tmp_h), harm, sr, subtype="FLOAT")
    _rubberband(tmp_h, tmp_h2, tom)
    harm_tom, _ = _ler(tmp_h2, n)
    sf.write(str(arquivos["other"]), harm_tom + perc, sr, subtype="PCM_24")
    tmp_h.unlink(); tmp_h2.unlink()

    # remonta a guia original (no tom novo) e, no modo playback, o próprio playback
    partes = [k for k in ("drums", "bass", "guitar", "piano", "other") if k in arquivos]
    instrumental = sum(_ler(arquivos[k], n)[0] for k in partes)
    voz, _ = _ler(arquivos["vocals"], n)

    def normalizar(x):
        p = np.abs(x).max()
        return x * (0.999 / p) if p > 0.999 else x

    guia = pasta / "original_no_tom.wav"
    sf.write(str(guia), normalizar(instrumental + voz), sr, subtype="PCM_24")
    arquivos["original"] = guia
    if modo == "playback":
        sf.write(str(arquivos["playback"]), normalizar(instrumental), sr, subtype="PCM_24")
        for k in ("bass", "other"):
            arquivos.pop(k).unlink(missing_ok=True)


def exportar_mp3(wav, destino):
    log("Exportando MP3 do playback...")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "320k", str(destino)], check=True)


# ---------------------------------------------------------------- 3. click
def gerar_click(wav_bateria, wav_original, destino, bpm_forcado=None, compasso=4):
    import librosa

    log("Detectando BPM e tempos...")
    # a bateria isolada dá uma detecção muito melhor que a mix inteira
    y, sr = librosa.load(str(wav_bateria), sr=22050, mono=True)
    if np.abs(y).max() < 1e-3:  # música sem bateria
        y, sr = librosa.load(str(wav_original), sr=22050, mono=True)

    if bpm_forcado:
        tempo, batidas = librosa.beat.beat_track(y=y, sr=sr, bpm=bpm_forcado, tightness=400, units="time")
    else:
        tempo, batidas = librosa.beat.beat_track(y=y, sr=sr, units="time")
    bpm = float(np.atleast_1d(tempo)[0])
    if bpm_forcado:
        bpm = float(bpm_forcado)

    duracao = sf.info(str(wav_original)).duration
    total = int(duracao * SR) + SR
    click = np.zeros(total, dtype=np.float32)

    def bip(freq, ms=35):
        t = np.arange(int(SR * ms / 1000)) / SR
        return (np.sin(2 * np.pi * freq * t) * np.exp(-t * 90)).astype(np.float32)

    forte, fraco = bip(1600) * 0.9, bip(1000) * 0.6
    for i, t in enumerate(batidas):
        s = forte if i % compasso == 0 else fraco
        ini = int(t * SR)
        fim = min(ini + len(s), total)
        click[ini:fim] += s[: fim - ini]

    sf.write(str(destino), np.stack([click, click], axis=1), SR, subtype="PCM_16")
    primeira = float(batidas[0]) if len(batidas) else 0.0
    return round(bpm, 2), primeira


# ---------------------------------------------------------------- 4. projeto Reaper
def guid():
    return "{" + str(uuid.uuid4()).upper() + "}"


def cor_reaper(rgb):
    r, g, b = rgb
    return (b << 16 | g << 8 | r) | 0x1000000


def faixa_rpp(nome, arquivo, duracao, cor, mudo=False, volume=1.0, pasta_inicio=0, pasta_fim=0):
    return f"""  <TRACK {guid()}
    NAME "{nome}"
    PEAKCOL {cor_reaper(cor)}
    VOLPAN {volume} 0 -1 -1 1
    MUTESOLO {1 if mudo else 0} 0 0
    ISBUS {pasta_inicio} {pasta_fim}
    NCHAN 2
    <ITEM
      POSITION 0
      LENGTH {duracao:.6f}
      NAME "{arquivo.name}"
      <SOURCE WAVE
        FILE "{arquivo.name}"
      >
    >
  >
"""


def layout(modo, titulo, arquivos):
    """Lista de faixas do projeto. Usada tanto no .RPP quanto pelo botão do Reaper.
    ("TRACK", nome, arquivo, cor, mudo, pasta, volume) | ("FOLDER", nome, cor)"""
    L = [
        ("TRACK", "GUIA - Original", arquivos["original"], (120, 120, 120), 1, 0, 1.0),
        ("TRACK", "GUIA - Voz", arquivos["vocals"], (240, 90, 160), 1, 0, 1.0),
    ]
    if modo == "playback":
        L.append(("TRACK", "CLICK", arquivos["click"], (255, 255, 0), 1, 0, 0.7))  # mudo: playback não precisa
        L.append(("TRACK", f"PLAYBACK - {titulo}", arquivos["playback"], (245, 170, 35), 0, 0, 1.0))
        return L
    L.append(("TRACK", "CLICK", arquivos["click"], (255, 255, 0), 0, 0, 0.7))
    L.append(("FOLDER", f"VS - {titulo}", (40, 40, 40)))
    nomes = [k for k in FAIXAS if k in arquivos]
    for i, k in enumerate(nomes):
        nome, cor = FAIXAS[k]
        L.append(("TRACK", nome, arquivos[k], cor, 0, -1 if i == len(nomes) - 1 else 0, 1.0))
    return L


def montar_rpp(pasta, titulo, faixas, bpm, duracao):
    blocos = []
    for f in faixas:
        if f[0] == "FOLDER":
            blocos.append(f"""  <TRACK {guid()}
    NAME "{f[1]}"
    PEAKCOL {cor_reaper(f[2])}
    ISBUS 1 1
  >
""")
        else:
            _, nome, arq, cor, mudo, pasta_fim, vol = f
            blocos.append(faixa_rpp(nome, arq, duracao, cor, mudo=mudo, volume=vol, pasta_fim=pasta_fim))

    rpp = f"""<REAPER_PROJECT 0.1 "7.0" 0
  TEMPO {bpm} 4 4
  SAMPLERATE {SR} 0 0
{''.join(blocos)}>
"""
    caminho = pasta / f"{nome_seguro(titulo)}.RPP"
    caminho.write_text(rpp, encoding="utf-8")
    return caminho


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Cria VS a partir de link do YouTube ou arquivo de áudio")
    ap.add_argument("entrada", help="link do YouTube ou caminho de um MP3/WAV")
    ap.add_argument("--bpm", type=float, help="força o BPM do click")
    ap.add_argument("--compasso", type=int, default=4, help="batidas por compasso (padrão 4)")
    ap.add_argument("--resultado", help="(uso interno do Reaper) arquivo onde gravar o resultado")
    ap.add_argument("--nao-abrir", action="store_true", help="não abre o Reaper no final")
    ap.add_argument("--modo", choices=["vs", "playback"], default="vs",
                    help="vs = instrumentos separados | playback = só tira a voz")
    ap.add_argument("--tom", type=int, default=0, choices=range(-12, 13), metavar="[-12..12]",
                    help="muda o tom em semitons (bateria e percussão não mudam)")
    args = ap.parse_args()
    print(f"PID:{os.getpid()}", flush=True)

    tmp = SAIDA / "_downloads"
    if re.match(r"https?://", args.entrada):
        log("Baixando áudio do YouTube...")
        origem, titulo = baixar(args.entrada, tmp)
    else:
        origem = Path(args.entrada)
        if not origem.exists():
            sys.exit(f"Arquivo não encontrado: {origem}")
        titulo = origem.stem

    if args.tom:
        titulo = f"{titulo} (Tom {args.tom:+d})"
    sufixo = " (Playback)" if args.modo == "playback" else ""
    pasta = SAIDA / (nome_seguro(titulo) + sufixo)
    pasta.mkdir(parents=True, exist_ok=True)
    wav_original = pasta / "original.wav"
    log(f"Convertendo para WAV: {titulo}")
    para_wav(origem, wav_original)
    duracao = sf.info(str(wav_original)).duration

    arquivos = separar(wav_original, pasta, args.modo, args.tom)
    arquivos["original"] = wav_original
    if args.tom:
        aplicar_tom(pasta, arquivos, args.modo, args.tom)

    arquivos["click"] = pasta / "click.wav"
    bpm, primeira = gerar_click(arquivos["drums"], wav_original, arquivos["click"], args.bpm, args.compasso)

    mp3 = None
    if args.modo == "playback":
        arquivos.pop("drums").unlink(missing_ok=True)  # só servia para achar o BPM
        mp3 = pasta / f"{nome_seguro(titulo)} - Playback.mp3"
        exportar_mp3(arquivos["playback"], mp3)

    faixas = layout(args.modo, titulo, arquivos)
    rpp = montar_rpp(pasta, titulo + sufixo, faixas, bpm, duracao)

    if args.resultado:
        escrever_resultado(args.resultado, titulo, bpm, primeira, duracao, faixas, rpp, args.modo, mp3)

    log("PRONTO!")
    print(f"   Modo   : {'Playback (sem voz)' if args.modo == 'playback' else 'VS (instrumentos separados)'}")
    if mp3:
        print(f"   MP3    : {mp3}")
    print(f"   Musica : {titulo}")
    print(f"   BPM    : {bpm}  (1a batida em {primeira:.2f}s)")
    print(f"   Pasta  : {pasta}")
    print(f"   Reaper : {rpp}")

    # rodando fora do Reaper (pelo .bat): já abre o projeto pronto
    if not args.resultado and not args.nao_abrir:
        abrir_no_reaper(rpp)


def abrir_no_reaper(rpp):
    candidatos = [
        Path(r"C:\Program Files\REAPER (x64)\reaper.exe"),
        Path(r"C:\Program Files\REAPER\reaper.exe"),
    ]
    exe = next((c for c in candidatos if c.exists()), None)
    log("Abrindo no Reaper...")
    try:
        if exe:
            subprocess.Popen([str(exe), str(rpp)], close_fds=True)
        else:
            os.startfile(str(rpp))
    except OSError as e:
        print(f"   Não consegui abrir sozinho ({e}). Abra o arquivo .RPP acima.")


def escrever_resultado(caminho, titulo, bpm, primeira, duracao, faixas, rpp, modo, mp3):
    """Arquivo simples (separado por TAB) que o script Lua do Reaper lê para montar as faixas.
    TRACK  nome  arquivo  r  g  b  mudo  profundidade_pasta  volume  |  FOLDER  nome  r  g  b"""
    linhas = [f"TITULO\t{titulo}", f"MODO\t{modo}", f"BPM\t{bpm}", f"PRIMEIRA\t{primeira:.4f}",
              f"DURACAO\t{duracao:.6f}", f"RPP\t{rpp}"]
    if mp3:
        linhas.append(f"MP3\t{mp3}")
    for f in faixas:
        if f[0] == "FOLDER":
            linhas.append(f"FOLDER\t{f[1]}\t{f[2][0]}\t{f[2][1]}\t{f[2][2]}")
        else:
            _, nome, arq, cor, mudo, pasta, vol = f
            linhas.append(f"TRACK\t{nome}\t{arq}\t{cor[0]}\t{cor[1]}\t{cor[2]}\t{mudo}\t{pasta}\t{vol}")
    linhas.append("FIM")
    Path(caminho).write_text("\n".join(linhas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import traceback

    try:
        main()
    except BaseException as e:  # avisa o Reaper que deu erro
        if "--resultado" in sys.argv:
            i = sys.argv.index("--resultado")
            if i + 1 < len(sys.argv):
                msg = str(e) or e.__class__.__name__
                Path(sys.argv[i + 1]).write_text(f"ERRO\t{msg}\n", encoding="utf-8")
        traceback.print_exc()
        sys.exit(1)
