"""
Criador de VS: link do YouTube -> faixas separadas por IA (Demucs) + click + projeto do Reaper.

Uso:
    .venv\\Scripts\\python criar_vs.py "https://www.youtube.com/watch?v=..."
    .venv\\Scripts\\python criar_vs.py "link" --bpm 128      (força o BPM se a detecção errar)
    .venv\\Scripts\\python criar_vs.py "C:\\musica.mp3"        (também aceita arquivo local)

Saída: pasta VS\\<nome da música>\\ com os WAVs e o arquivo .RPP para abrir no Reaper.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
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
    "other_perc": ("Outros (percussão)", (190, 90, 120)),
}
# partes que mudam de tom; bateria, "outros (percussão)" e click ficam iguais
TOM_CHAVES = ("bass", "guitar", "piano", "other", "vocals")


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
    fontes_np = dict(zip(model.sources, (f.numpy().T for f in fontes)))
    if modo == "playback":
        # playback = música original menos a voz (mantém 100% do instrumental, sem perder nada)
        voz = fontes_np["vocals"]
        playback = audio[: len(voz)] - voz
        pico = np.abs(playback).max()
        if pico > 0.999:  # evita distorcer
            playback = playback * (0.999 / pico)
        fontes_np["playback"] = playback
    # as partes ficam guardadas: com elas dá para mudar o tom depois sem separar de novo
    for nome, dado in fontes_np.items():
        caminho = pasta / f"{nome}.wav"
        sf.write(str(caminho), dado, sr, subtype="PCM_24")
        arquivos[nome] = caminho
    dividir_outros(pasta, arquivos)
    return arquivos


def dividir_outros(pasta, arquivos):
    """'other' (sanfona, cordas, percussão solta...) vira parte harmônica (muda de tom)
    e parte percussiva (fica igual). As duas somadas dão exatamente o 'other' original."""
    import librosa

    log("Separando a percussão da faixa Outros...")
    a, sr = _ler(arquivos["other"])
    n = len(a)
    harm = np.zeros_like(a)
    perc = np.zeros_like(a)
    for c in range(a.shape[1]):
        S = librosa.stft(a[:, c], n_fft=4096, hop_length=1024)
        Sh, Sp = librosa.decompose.hpss(S, margin=2.0)
        perc[:, c] = librosa.istft(Sp, hop_length=1024, length=n)
        harm[:, c] = a[:, c] - perc[:, c]  # o resto (inclusive o que não é claro) fica no harmônico
    sf.write(str(arquivos["other"]), harm, sr, subtype="PCM_24")
    arquivos["other_perc"] = pasta / "other_perc.wav"
    sf.write(str(arquivos["other_perc"]), perc, sr, subtype="PCM_24")


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


def _normalizar(x):
    p = np.abs(x).max()
    return x * (0.999 / p) if p > 0.999 else x


def salvar_info(pasta, titulo, modo, arquivos):
    """Guarda na pasta da música quais são as partes no tom original (para mudar o tom depois)."""
    info = {"titulo": titulo, "modo": modo,
            "arquivos": {k: v.relative_to(pasta).as_posix() for k, v in arquivos.items()}}
    (pasta / "playpronto.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")


def nome_mp3(pasta, titulo, tom):
    return pasta / (nome_seguro(titulo) + (f" (Tom {tom:+d})" if tom else "") + " - Playback.mp3")


def aplicar_tom_pasta(pasta, tom):
    """Arquivos da música no tom pedido. As partes originais nunca são alteradas: o tom novo vai para
    a subpasta 'Tom +N' (se já existir, reaproveita na hora). Bateria e percussão não mudam.
    Devolve (arquivos, mp3)."""
    info = json.loads((pasta / "playpronto.json").read_text(encoding="utf-8"))
    modo, titulo = info["modo"], info["titulo"]
    orig = {k: pasta / v for k, v in info["arquivos"].items()}
    out = dict(orig)
    if tom:
        dest = pasta / f"Tom {tom:+d}"
        mover = [k for k in TOM_CHAVES if k in orig]
        if not (dest / ".pronto").exists():
            log(f"Mudando o tom ({tom:+d} semitons) sem mexer na bateria e percussão...")
            dest.mkdir(exist_ok=True)
            n = sf.info(str(orig["drums"])).frames
            with ThreadPoolExecutor(max_workers=4) as ex:  # uma faixa por núcleo
                list(ex.map(lambda k: _rubberband(orig[k], dest / f"_{k}.wav", tom, voz=(k == "vocals")), mover))
            for k in mover:
                a, sr = _ler(dest / f"_{k}.wav", n)
                sf.write(str(dest / f"{k}.wav"), a, sr, subtype="PCM_24")
                (dest / f"_{k}.wav").unlink()
            log("Montando a guia e o playback no tom novo...")
            fixas = [orig[k] for k in ("drums", "other_perc") if k in orig]
            novas = [dest / f"{k}.wav" for k in mover if k != "vocals"]
            instrumental = sum(_ler(f, n)[0] for f in fixas + novas)
            voz, sr = _ler(dest / "vocals.wav", n)
            sf.write(str(dest / "original.wav"), _normalizar(instrumental + voz), sr, subtype="PCM_24")
            if modo == "playback":
                sf.write(str(dest / "playback.wav"), _normalizar(instrumental), sr, subtype="PCM_24")
            (dest / ".pronto").write_text("ok")
        for k in mover:
            out[k] = dest / f"{k}.wav"
        out["original"] = dest / "original.wav"
        if modo == "playback":
            out["playback"] = dest / "playback.wav"
    mp3 = None
    if modo == "playback":
        mp3 = nome_mp3(pasta, titulo, tom)
        if not mp3.exists():
            exportar_mp3(out["playback"], mp3)
    return out, mp3


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


def faixa_rpp(nome, arquivo, duracao, cor, mudo=False, volume=1.0, pasta_inicio=0, pasta_fim=0, base=None):
    rel = os.path.relpath(arquivo, base) if base else arquivo.name
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
        FILE "{rel}"
      >
    >
  >
"""


def layout(modo, titulo, arquivos):
    """Lista de faixas do projeto. Usada tanto no .RPP quanto pelo botão do Reaper.
    ("TRACK", nome, arquivo, cor, mudo, pasta, volume, chave) | ("FOLDER", nome, cor, chave, mudo)
    'chave' diz ao botão do Reaper o que é cada faixa (para mudar o tom ao vivo)."""
    L = [
        ("TRACK", "GUIA - Original", arquivos["original"], (120, 120, 120), 1, 0, 1.0, "original"),
        ("TRACK", "GUIA - Voz", arquivos["vocals"], (240, 90, 160), 1, 0, 1.0, "vocals"),
    ]
    if modo == "playback":
        L.append(("TRACK", "CLICK", arquivos["click"], (255, 255, 0), 1, 0, 0.7, "click"))  # mudo: playback não precisa
        L.append(("TRACK", f"PLAYBACK - {titulo}", arquivos["playback"], (245, 170, 35), 0, 0, 1.0, "playback"))
        # partes do playback: ficam mudas; o botão usa para você ouvir o tom novo antes de confirmar
        L.append(("FOLDER", "PARTES (para mudar o tom)", (60, 60, 60), "partes", 1))
        nomes = [k for k in ("drums", "other_perc", "bass", "other") if k in arquivos]
    else:
        L.append(("TRACK", "CLICK", arquivos["click"], (255, 255, 0), 0, 0, 0.7, "click"))
        L.append(("FOLDER", f"VS - {titulo}", (40, 40, 40), "vs", 0))
        nomes = [k for k in FAIXAS if k in arquivos]
    for i, k in enumerate(nomes):
        nome, cor = FAIXAS[k]
        L.append(("TRACK", nome, arquivos[k], cor, 0, -1 if i == len(nomes) - 1 else 0, 1.0, k))
    return L


def montar_rpp(pasta, titulo, faixas, bpm, duracao):
    blocos = []
    for f in faixas:
        if f[0] == "FOLDER":
            blocos.append(f"""  <TRACK {guid()}
    NAME "{f[1]}"
    PEAKCOL {cor_reaper(f[2])}
    MUTESOLO {f[4]} 0 0
    ISBUS 1 1
    BUSCOMP {2 if f[4] else 0} 0 0 0 0
  >
""")
        else:
            _, nome, arq, cor, mudo, pasta_fim, vol, _chave = f
            blocos.append(faixa_rpp(nome, arq, duracao, cor, mudo=mudo, volume=vol, pasta_fim=pasta_fim,
                                    base=pasta))

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
    ap.add_argument("entrada", nargs="?", help="link do YouTube ou caminho de um MP3/WAV")
    ap.add_argument("--bpm", type=float, help="força o BPM do click")
    ap.add_argument("--compasso", type=int, default=4, help="batidas por compasso (padrão 4)")
    ap.add_argument("--resultado", help="(uso interno do Reaper) arquivo onde gravar o resultado")
    ap.add_argument("--nao-abrir", action="store_true", help="não abre o Reaper no final")
    ap.add_argument("--modo", choices=["vs", "playback"], default="vs",
                    help="vs = instrumentos separados | playback = só tira a voz")
    ap.add_argument("--tom", type=int, default=0, choices=range(-12, 13), metavar="[-12..12]",
                    help="muda o tom em semitons (bateria e percussão não mudam)")
    ap.add_argument("--retom", metavar="PASTA",
                    help="(uso interno do Reaper) refaz só o tom de uma música já separada")
    args = ap.parse_args()
    print(f"PID:{os.getpid()}", flush=True)

    if args.retom:  # mudar o tom depois: usa as partes já separadas, a IA não roda de novo
        arquivos, mp3 = aplicar_tom_pasta(Path(args.retom), args.tom)
        if args.resultado:
            linhas = [f"TOM\t{args.tom}"] + ([f"MP3\t{mp3}"] if mp3 else [])
            linhas += [f"ARQ\t{k}\t{v}" for k, v in arquivos.items()]
            Path(args.resultado).write_text("\n".join(linhas + ["FIM"]) + "\n", encoding="utf-8")
        log("PRONTO!")
        return
    if not args.entrada:
        ap.error("informe o link ou o arquivo da música")

    import licenca
    log("Verificando licença...")
    try:
        lic = licenca.checar_para_uso()
    except licenca.ErroLicenca as e:
        sys.exit("LICENCA|" + e.msg)  # o botão do Reaper reconhece e abre a tela de ativação
    if lic["tipo"] == "teste":
        print(f"   Teste grátis: {lic['restantes']} de {lic['total']} músicas restantes", flush=True)

    tmp = SAIDA / "_downloads"
    if re.match(r"https?://", args.entrada):
        log("Baixando áudio do YouTube...")
        origem, titulo = baixar(args.entrada, tmp)
    else:
        origem = Path(args.entrada)
        if not origem.exists():
            sys.exit(f"Arquivo não encontrado: {origem}")
        titulo = origem.stem

    sufixo = " (Playback)" if args.modo == "playback" else ""
    pasta = SAIDA / (nome_seguro(titulo) + sufixo)
    pasta.mkdir(parents=True, exist_ok=True)
    wav_original = pasta / "original.wav"
    log(f"Convertendo para WAV: {titulo}")
    para_wav(origem, wav_original)
    duracao = sf.info(str(wav_original)).duration

    arquivos = separar(wav_original, pasta, args.modo)
    arquivos["original"] = wav_original

    arquivos["click"] = pasta / "click.wav"
    bpm, primeira = gerar_click(arquivos["drums"], wav_original, arquivos["click"], args.bpm, args.compasso)

    # partes no tom original ficam registradas; o tom escolhido (se houver) vai para a subpasta 'Tom +N'
    salvar_info(pasta, titulo, args.modo, arquivos)
    arquivos, mp3 = aplicar_tom_pasta(pasta, args.tom)

    faixas = layout(args.modo, titulo, arquivos)
    rpp = montar_rpp(pasta, titulo + sufixo, faixas, bpm, duracao)

    if lic["tipo"] == "teste":  # só conta a música do teste depois que deu tudo certo
        try:
            restantes = licenca.consumir_teste()
            print(f"   Teste grátis: restam {restantes} música(s)", flush=True)
        except licenca.ErroLicenca:
            pass

    if args.resultado:
        escrever_resultado(args.resultado, titulo, bpm, primeira, duracao, faixas, rpp, args.modo, mp3,
                           pasta, args.tom)

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


def escrever_resultado(caminho, titulo, bpm, primeira, duracao, faixas, rpp, modo, mp3, pasta=None, tom=0):
    """Arquivo simples (separado por TAB) que o script Lua do Reaper lê para montar as faixas.
    TRACK  nome  arquivo  r  g  b  mudo  profundidade_pasta  volume  chave
    FOLDER  nome  r  g  b  chave  mudo"""
    linhas = [f"TITULO\t{titulo}", f"MODO\t{modo}", f"BPM\t{bpm}", f"PRIMEIRA\t{primeira:.4f}",
              f"DURACAO\t{duracao:.6f}", f"RPP\t{rpp}", f"PASTA\t{pasta}", f"TOM\t{tom}"]
    if mp3:
        linhas.append(f"MP3\t{mp3}")
    for f in faixas:
        if f[0] == "FOLDER":
            linhas.append(f"FOLDER\t{f[1]}\t{f[2][0]}\t{f[2][1]}\t{f[2][2]}\t{f[3]}\t{f[4]}")
        else:
            _, nome, arq, cor, mudo, prof, vol, chave = f
            linhas.append(f"TRACK\t{nome}\t{arq}\t{cor[0]}\t{cor[1]}\t{cor[2]}\t{mudo}\t{prof}\t{vol}\t{chave}")
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
