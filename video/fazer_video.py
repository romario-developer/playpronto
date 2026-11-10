"""Gera o vídeo de anúncio do PlayPronto (1080x1920, Reels/TikTok) sincronizado com a narração.
Uso: ..\\.venv\\Scripts\\python fazer_video.py            -> PlayPronto_anuncio.mp4
     ..\\.venv\\Scripts\\python fazer_video.py --previa   -> só alguns quadros PNG para conferir
"""
import json
import math
import random
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

AQUI = Path(__file__).resolve().parent
LOGO = Image.open(AQUI.parent / "reaper" / "icones" / "preview.png").convert("RGBA")
FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1080, 1920, 30
PALAVRAS = json.loads((AQUI / "palavras.json").read_text(encoding="utf-8"))
DUR_NARR = 43.9
FIM = 46.0

OURO = (245, 170, 35)
BRANCO = (255, 255, 255)
CINZA = (150, 150, 160)
FUNDO = (26, 26, 31)
VERDE = (90, 200, 110)
VERMELHO = (235, 80, 70)
ROSA = (240, 90, 160)

# ------------------------------------------------------------------ util
_fontes = {}


def fonte(tam, peso="b"):
    nome = {"b": "segoeuib.ttf", "r": "segoeui.ttf", "s": "seguisb.ttf", "m": "consolab.ttf"}[peso]
    k = (tam, peso)
    if k not in _fontes:
        try:
            _fontes[k] = ImageFont.truetype(f"C:/Windows/Fonts/{nome}", tam)
        except OSError:
            _fontes[k] = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", tam)
    return _fontes[k]


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def suave(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def entra(t, t0, dur=0.35):
    """0 -> 1 com leve ultrapassagem (efeito 'pop')."""
    x = clamp((t - t0) / dur)
    if x <= 0:
        return 0.0
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def mistura(c1, c2, k):
    return tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))


def txt(d, s, xy, f, cor=BRANCO, ancora="la"):
    d.text(xy, s, font=f, fill=cor, anchor=ancora)


def colar(base, img, cx, cy, escala=1.0, alpha=1.0):
    if escala <= 0.01 or alpha <= 0.01:
        return
    w, h = max(1, int(img.width * escala)), max(1, int(img.height * escala))
    im = img.resize((w, h), Image.LANCZOS) if (w, h) != img.size else img
    if alpha < 1:
        im = im.copy()
        a = im.getchannel("A").point(lambda v: int(v * alpha))
        im.putalpha(a)
    base.alpha_composite(im, (int(cx - w / 2), int(cy - h / 2)))


def camada():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def cursor(d, x, y, apertado=False):
    s = 1.6 if not apertado else 1.4
    pts = [(0, 0), (0, 34), (9, 26), (16, 41), (22, 38), (15, 24), (27, 24)]
    pts = [(x + px * s, y + py * s) for px, py in pts]
    d.polygon(pts, fill=BRANCO, outline=(0, 0, 0))


def onda(rng, n, base=0.5, var=0.5):
    v = np.abs(np.convolve(rng.standard_normal(n), np.ones(5) / 5, mode="same"))
    v = v / (v.max() + 1e-9)
    return base * 0.3 + v * var


# fundo com leve degradê + brilho dourado
def fazer_fundo():
    y = np.linspace(0, 1, H)[:, None]
    g = (np.array([30, 30, 37]) * (1 - y) + np.array([14, 14, 18]) * y)
    img = np.repeat(g[:, None, :], W, axis=1).reshape(H, W, 3)
    yy, xx = np.mgrid[0:H, 0:W]
    brilho = np.exp(-(((xx - W * 0.5) / 700) ** 2 + ((yy - H * 0.32) / 600) ** 2)) * 26
    img = img + brilho[..., None] * np.array([1.0, 0.65, 0.15])
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGBA")


FUNDO_IMG = fazer_fundo()

# ------------------------------------------------------------------ legenda (karaokê)
def frases():
    out, atual = [], []
    for a, b, w in PALAVRAS:
        atual.append((a, b, w))
        if w[-1] in ".,?!" and len(atual) >= 2 or w[-1] in ".?!":
            out.append(atual)
            atual = []
    if atual:
        out.append(atual)
    return out


FRASES = frases()
CORRECOES = {"vs": "VS", "reaper": "Reaper", "playback": "Playback", "Play": "Play"}


def palavra_bonita(w):
    limpo = w.rstrip(".,?!")
    resto = w[len(limpo):]
    limpo = CORRECOES.get(limpo.lower(), limpo) if limpo.lower() in CORRECOES else limpo
    if resto in (",",):
        resto = ""
    return limpo + ("?" if resto == "?" else "")


def legenda(base, t):
    if t > 41.85:
        return
    atual = None
    for i, fr in enumerate(FRASES):
        ini = fr[0][0] - 0.15
        fim = FRASES[i + 1][0][0] - 0.15 if i + 1 < len(FRASES) else DUR_NARR
        if ini <= t < fim:
            atual = (fr, ini)
            break
    if not atual:
        return
    fr, ini = atual
    f = fonte(82)
    d = ImageDraw.Draw(base)
    # junta "Play" + "Pronto" numa palavra só
    itens = []
    for a, b, w in fr:
        p = palavra_bonita(w)
        if itens and itens[-1][2] == "Play" and p.startswith("Pronto"):
            itens[-1] = (itens[-1][0], b, "PlayPronto")
        else:
            itens.append((a, b, p))
    # quebra em linhas
    linhas, linha, larg = [], [], 0
    esp = d.textlength(" ", font=f)
    for it in itens:
        lw = d.textlength(it[2], font=f)
        if linha and larg + esp + lw > 960:
            linhas.append(linha)
            linha, larg = [], 0
        linha.append((it, lw))
        larg += lw + (esp if larg else 0)
    if linha:
        linhas.append(linha)
    y0 = 1560 - (len(linhas) - 1) * 50
    k = entra(t, ini, 0.25)
    for li, ln in enumerate(linhas):
        total = sum(lw for _, lw in ln) + esp * (len(ln) - 1)
        x = (W - total) / 2
        y = y0 + li * 100 + (1 - k) * 30
        for (a, b, p), lw in ln:
            if t >= a:
                cor = OURO if t < b + 0.12 else BRANCO
            else:
                cor = (120, 120, 130)
            # contorno para ler em cima de qualquer coisa
            d.text((x, y), p, font=f, fill=cor, stroke_width=6, stroke_fill=(10, 10, 12))
            x += lw + esp


# ------------------------------------------------------------------ peças reutilizáveis
def janela_playpronto(t, tipo="vs", tela="inicio", link=False, clique_t=None, progresso=0.0,
                      etapa="", tempo="0:00", titulo="Minha Música"):
    """Desenha a janela do PlayPronto (igual ao script do Reaper) em 440x326 e devolve a imagem."""
    s = 2
    im = Image.new("RGBA", (440 * s, 326 * s), (28, 28, 33, 255))
    d = ImageDraw.Draw(im)

    def R(x, y, w, h, r, cor):
        d.rounded_rectangle([x * s, y * s, (x + w) * s, (y + h) * s], r * s, fill=cor)

    def T(s_, x, y, tam, cor, peso="b", anc="la"):
        d.text((x * s, y * s), s_, font=fonte(tam * s, peso), fill=cor, anchor=anc)

    im.alpha_composite(LOGO.resize((48 * s, 48 * s), Image.LANCZOS), (18 * s, 16 * s))
    T("PlayPronto", 74, 16, 22, BRANCO)
    cw = (440 - 50) / 2
    if tela == "inicio":
        T("Playback e VS com IA direto no Reaper", 74, 46, 13, CINZA, "r")
        for i, (nome, sub, k) in enumerate([("VS", "instrumentos separados", "vs"),
                                            ("Playback", "só tira a voz", "playback")]):
            x = 20 + i * (cw + 10)
            sel = tipo == k
            R(x, 78, cw, 54, 10, OURO if sel else (70, 70, 80))
            R(x + 2, 80, cw - 4, 50, 9, (60, 45, 25) if sel else (42, 42, 48))
            T(nome, x + cw / 2, 96, 16, (255, 200, 90) if sel else (230, 230, 235), anc="mm")
            T(sub, x + cw / 2, 117, 12, (170, 170, 180), "r", anc="mm")
        apert = clique_t is not None and 0 <= t - clique_t < 0.25
        R(20, 146, 400, 46, 8, (200, 130, 20) if apert else OURO)
        T("Criar com o link copiado" if link else "Colar link do YouTube", 220, 169, 16, (35, 20, 5), anc="mm")
        if link:
            T("Link: youtube.com/watch?v=2hgI3RidpgQ", 22, 196, 13, (120, 200, 120), "r")
        R(20, 220, cw, 34, 8, (55, 55, 63)); T("Arquivo do PC", 20 + cw / 2, 237, 13, (230, 230, 235), "r", "mm")
        R(30 + cw, 220, cw, 34, 8, (55, 55, 63)); T("BPM: automático", 30 + cw * 1.5, 237, 13, (230, 230, 235), "r", "mm")
        T("Quando terminar:", 20, 266, 13, CINZA, "r")
        R(20, 286, 196, 26, 8, (55, 55, 63)); T("●  Abrir em nova aba", 118, 299, 12, (230, 230, 235), "r", "mm")
        R(224, 286, 196, 26, 8, (55, 55, 63)); T("○  Pôr no cursor (setlist)", 322, 299, 12, (230, 230, 235), "r", "mm")
    else:
        T(("Playback: " if tipo == "playback" else "VS: ") + titulo, 74, 46, 13, CINZA, "r")
        T(etapa, 20, 92, 14, (220, 220, 225), "r")
        R(20, 118, 400, 16, 8, (50, 50, 58))
        if progresso > 0.02:
            R(20, 118, max(16, 400 * progresso), 16, 8, OURO)
        T(f"{tempo}   {int(progresso * 100)}%", 20, 142, 13, (150, 150, 160), "r")
        T("Pode fechar esta janela: ele continua e avisa quando acabar.", 20, 166, 12, (120, 120, 130), "r")
        R(300, 250, 120, 38, 8, (55, 55, 63)); T("Cancelar", 360, 269, 13, (230, 230, 235), "r", "mm")
    return im


def sombra_de(im, raio=30, opac=150):
    a = im.getchannel("A").point(lambda v: opac if v else 0)
    sh = Image.new("RGBA", (im.width + raio * 4, im.height + raio * 4), (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", im.size, (0, 0, 0, 255)), (raio * 2, raio * 2), a)
    return sh.filter(ImageFilter.GaussianBlur(raio))


def com_moldura(im, raio=24):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, im.width - 1, im.height - 1], raio, fill=255)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im, (0, 0), m)
    ImageDraw.Draw(out).rounded_rectangle([0, 0, im.width - 1, im.height - 1], raio, outline=(80, 80, 92), width=3)
    return out


def colar_janela(base, im, cx, cy, escala=1.0, alpha=1.0):
    im = com_moldura(im)
    if escala != 1.0:
        im = im.resize((int(im.width * escala), int(im.height * escala)), Image.LANCZOS)
    sh = sombra_de(im)
    colar(base, sh, cx, cy + 20, 1.0, alpha * 0.8)
    colar(base, im, cx, cy, 1.0, alpha)


FAIXAS = [
    ("GUIA - Original", (120, 120, 120), True),
    ("GUIA - Voz", ROSA, True),
    ("CLICK", (255, 230, 0), False),
    ("VS - Minha Música", (60, 60, 66), None),
    ("Bateria", (220, 80, 60), False),
    ("Baixo", (230, 160, 40), False),
    ("Guitarra/Violão", (80, 170, 80), False),
    ("Teclado/Piano", (70, 130, 220), False),
    ("Outros", (150, 100, 200), False),
]
_rng = np.random.default_rng(7)
ONDAS = [onda(_rng, 300) for _ in FAIXAS]
ONDAS[2] = np.array([1.0 if i % 12 < 2 else 0.05 for i in range(300)])  # click


def desenhar_onda(d, x, y, w, h, env, cor, ate=1.0):
    n = len(env)
    passo = w / n
    for i in range(int(n * ate)):
        a = env[i] * h * 0.45
        cx = x + i * passo
        d.line([(cx, y + h / 2 - a), (cx, y + h / 2 + a)], fill=cor, width=max(1, int(passo)))


# ------------------------------------------------------------------ cenas
def cena_problema(base, t):
    d = ImageDraw.Draw(base)
    # relógio 02:00
    k = entra(t, 0.05, 0.4)
    if k > 0:
        cor = VERMELHO
        dois = ":" if int(t * 2) % 2 == 0 else " "
        f = fonte(int(190 * k), "m")
        txt(d, f"02{dois}00", (W / 2, 330), f, cor, "mm")
        txt(d, "véspera do show", (W / 2, 450), fonte(46, "s"), CINZA, "mm")
    # setlist
    if t > 3.7:
        a = suave((t - 3.7) / 0.4)
        x0, y0 = 120, 560
        d.rounded_rectangle([x0, y0, W - x0, y0 + 820], 30, fill=mistura(FUNDO, (40, 40, 48), a))
        txt(d, "SETLIST  -  amanhã", (W / 2, y0 + 55), fonte(46), mistura(FUNDO, OURO, a), "mm")
        for i in range(14):
            ti = 5.15 + i * 0.08
            if t < ti:
                continue
            ka = entra(t, ti, 0.25)
            col, lin = i // 7, i % 7
            x = x0 + 50 + col * 430
            y = y0 + 130 + lin * 95
            txt(d, f"{i + 1:02d}", (x, y), fonte(40, "m"), CINZA)
            txt(d, f"Música {i + 1:02d}", (x + 70 + (1 - ka) * 40, y), fonte(40, "s"), BRANCO)
            # marcação VS ok / falta
            tm = 6.66 + i * 0.045 if i < 9 else 7.18 + (i - 9) * 0.09
            if t >= tm:
                km = entra(t, tm, 0.25)
                cx, cy = x + 360, y + 24
                r = 24 * km
                if i < 9:
                    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=VERDE)
                    d.line([(cx - r * 0.45, cy), (cx - r * 0.1, cy + r * 0.4), (cx + r * 0.5, cy - r * 0.35)],
                           fill=BRANCO, width=6)
                else:
                    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=VERMELHO)
                    d.line([(cx - r * 0.4, cy - r * 0.4), (cx + r * 0.4, cy + r * 0.4)], fill=BRANCO, width=6)
                    d.line([(cx - r * 0.4, cy + r * 0.4), (cx + r * 0.4, cy - r * 0.4)], fill=BRANCO, width=6)


def cena_internet(base, t):
    d = ImageDraw.Draw(base)
    k = entra(t, 7.9, 0.35)
    y = 250 + (1 - k) * 60
    d.rounded_rectangle([90, y, W - 90, y + 120], 60, fill=(245, 245, 248))
    busca = "VS sertanejo grátis"
    n = int(clamp((t - 8.16) / 0.9) * len(busca))
    txt(d, busca[:n] + ("|" if int(t * 3) % 2 == 0 else ""), (170, y + 60), fonte(50, "s"), (40, 40, 45), "lm")
    d.ellipse([W - 190, y + 30, W - 130, y + 90], outline=(120, 120, 130), width=7)
    d.line([(W - 140, y + 82), (W - 118, y + 104)], fill=(120, 120, 130), width=8)
    cartoes = [
        (9.6, "VS - Aquele Hit Novo", "nenhum resultado", "NÃO TEM"),
        (10.64, "VS Multitrack Premium", "R$ 59,90 por música", "CARO"),
        (11.62, "VS em Ré maior", "você canta em Dó...", "TOM ERRADO"),
    ]
    for i, (t0, tit, sub, selo) in enumerate(cartoes):
        if t < t0:
            continue
        kc = entra(t, t0, 0.35)
        cy = 560 + i * 300
        cartao = Image.new("RGBA", (880, 240), (0, 0, 0, 0))
        dc = ImageDraw.Draw(cartao)
        dc.rounded_rectangle([0, 0, 879, 239], 28, fill=(44, 44, 52))
        dc.rounded_rectangle([40, 50, 180, 190], 18, fill=(70, 70, 80))
        dc.polygon([(90, 85), (90, 155), (145, 120)], fill=(130, 130, 140))
        txt(dc, tit, (215, 80), fonte(48), BRANCO)
        txt(dc, sub, (215, 150), fonte(38, "r"), CINZA)
        colar(base, cartao, W / 2, cy, 0.85 + 0.15 * kc, clamp(kc))
        # carimbo
        ks = entra(t, t0 + 0.25, 0.3)
        if ks > 0:
            sel = Image.new("RGBA", (520, 130), (0, 0, 0, 0))
            ds = ImageDraw.Draw(sel)
            ds.rounded_rectangle([5, 5, 515, 125], 16, outline=VERMELHO, width=10)
            txt(ds, selo, (260, 66), fonte(66), VERMELHO, "mm")
            sel = sel.rotate(-8, resample=Image.BICUBIC, expand=True)
            colar(base, sel, W / 2 + 250, cy + 115, (1.5 - 0.6 * ks) * 0.85, clamp(ks))


def cena_produto(base, t):
    d = ImageDraw.Draw(base)
    # logo surge
    k = entra(t, 14.55, 0.45)
    mover = suave((t - 15.6) / 0.5)
    if k > 0:
        cy = 620 - mover * 160
        esc = (1.6 - mover * 0.7) * k
        brilho = Image.new("RGBA", (700, 700), (0, 0, 0, 0))
        ImageDraw.Draw(brilho).ellipse([100, 100, 600, 600], fill=(245, 170, 35, 90))
        colar(base, brilho.filter(ImageFilter.GaussianBlur(80)), W / 2, cy, k)
        colar(base, LOGO, W / 2, cy, esc)
        kt = entra(t, 14.78, 0.35)
        if kt > 0 and mover < 1:
            txt(d, "PlayPronto", (W / 2, cy + 280 * (1 - mover)), fonte(int(120 * kt)), BRANCO, "mm")
    # barra do Reaper com o botão
    kb = entra(t, 15.6, 0.4)
    if kb > 0:
        y = 900
        kj = suave((t - 16.32) / 0.4)
        if kj > 0:  # janela do Reaper em volta
            d.rounded_rectangle([60, y - 170, W - 60, y + 330], 24, fill=mistura(FUNDO, (52, 52, 58), kj),
                                outline=mistura(FUNDO, (90, 90, 100), kj), width=3)
            d.rectangle([62, y - 168, W - 62, y - 100], fill=mistura(FUNDO, (36, 36, 42), kj))
            txt(d, "REAPER  -  [Projeto sem título]", (100, y - 135), fonte(36, "s"), mistura(FUNDO, BRANCO, kj), "lm")
            for i in range(6):
                d.rectangle([100, y + 140 + i * 30, W - 100, y + 160 + i * 30], fill=mistura(FUNDO, (44, 44, 50), kj))
        icones = 7
        larg = 116
        x0 = W / 2 - icones * larg / 2
        for i in range(icones):
            x = x0 + i * larg + larg / 2
            if i == icones - 1:
                pulso = 1 + 0.08 * math.sin(t * 8)
                gl = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
                ImageDraw.Draw(gl).ellipse([60, 60, 240, 240], fill=(245, 170, 35, 140))
                colar(base, gl.filter(ImageFilter.GaussianBlur(30)), x, y, kb)
                colar(base, LOGO, x, y, 0.37 * kb * pulso)
            else:
                r = 40 * kb
                d.rounded_rectangle([x - r, y - r, x + r, y + r], 14, fill=(75, 75, 85))
                d.rectangle([x - r * 0.4, y - r * 0.4, x + r * 0.4, y + r * 0.4], outline=(140, 140, 150), width=4)
        if kb > 0.5:
            txt(d, "1 botão", (x0 + icones * larg - 58, y + 100), fonte(40), OURO, "mm")


def cena_janela(base, t):
    k = entra(t, 18.1, 0.4)
    link = t >= 18.68
    tipo = "vs"
    if t >= 20.84:
        tipo = "playback"
    if t >= 21.4:
        tipo = "vs"
    im = janela_playpronto(t, tipo=tipo, link=link, clique_t=21.96)
    cx, cy = W / 2, 760
    esc = 1.1
    colar_janela(base, im, cx, cy + (1 - k) * 120, esc, clamp(k))
    d = ImageDraw.Draw(base)
    # "Ctrl+C" do link
    kc = entra(t, 18.24, 0.3)
    if 0 < kc and t < 19.4:
        chip = Image.new("RGBA", (560, 110), (0, 0, 0, 0))
        dc = ImageDraw.Draw(chip)
        dc.rounded_rectangle([0, 0, 559, 109], 55, fill=(230, 40, 40))
        txt(dc, "Ctrl + C no link", (280, 55), fonte(50), BRANCO, "mm")
        colar(base, chip, W / 2, 230, kc, clamp(kc))
    # cursor passeando
    alvos = [(18.3, (900, 300)), (19.5, (cx - 230, 495)), (20.6, (cx + 230, 495)),
             (21.2, (cx - 230, 495)), (21.7, (cx, 640)), (23.5, (cx, 640))]
    pos = alvos[0][1]
    for (ta, pa), (tb, pb) in zip(alvos, alvos[1:]):
        if ta <= t < tb:
            kk = suave((t - ta) / min(0.45, tb - ta))
            pos = (pa[0] + (pb[0] - pa[0]) * kk, pa[1] + (pb[1] - pa[1]) * kk)
            break
        if t >= tb:
            pos = pb
    if k > 0.5:
        ap = 21.96 <= t < 22.2
        if ap:  # onda do clique
            r = 30 + (t - 21.96) * 400
            d.ellipse([pos[0] - r, pos[1] - r, pos[0] + r, pos[1] + r], outline=OURO, width=6)
        cursor(d, pos[0], pos[1], ap)


def cena_processando(base, t):
    prog = suave((t - 22.6) / (28.7 - 22.6))
    if t < 28.84:
        seg = int((t - 22.6) * 2.5)
        tempo = f"0:{max(0, seg):02d}"
    else:
        tempo = "3:02"
        prog = 1.0
    etapa = "Separando instrumentos..." if prog < 0.98 else "Pronto!"
    im = janela_playpronto(t, tela="proc", progresso=prog, etapa=etapa, tempo=tempo)
    colar_janela(base, im, W / 2, 420, 0.95)
    d = ImageDraw.Draw(base)
    chegadas = [(24.48, 4), (25.38, 5), (25.96, 6), (26.62, 7), (28.58, 2)]
    for i, (t0, fi) in enumerate(chegadas):
        if t < t0:
            continue
        k = entra(t, t0, 0.35)
        nome, cor, _ = FAIXAS[fi]
        y = 820 + i * 128
        x = 90 + (1 - k) * -300
        d.rounded_rectangle([x, y, x + 900, y + 108], 20, fill=(40, 40, 47))
        d.rounded_rectangle([x, y, x + 18, y + 108], 9, fill=cor)
        txt(d, nome, (x + 45, y + 54), fonte(44), BRANCO, "lm")
        desenhar_onda(d, x + 430, y + 14, 440, 80, ONDAS[fi], cor, ate=clamp((t - t0) / 0.8))
    if t >= 28.84:  # "3 minutos depois"
        kk = entra(t, 28.84, 0.3)
        sel = Image.new("RGBA", (620, 150), (0, 0, 0, 0))
        ds = ImageDraw.Draw(sel)
        ds.rounded_rectangle([0, 0, 619, 149], 30, fill=OURO)
        txt(ds, "3 min depois", (310, 75), fonte(76), (35, 20, 5), "mm")
        colar(base, sel.rotate(4, expand=True, resample=Image.BICUBIC), W / 2, 700, kk)


def cena_reaper(base, t):
    k = suave((t - 30.2) / 0.45)
    y0 = 230 + (1 - k) * 900
    d = ImageDraw.Draw(base)
    x0, x1 = 40, W - 40
    d.rounded_rectangle([x0, y0, x1, y0 + 1160], 24, fill=(46, 46, 52), outline=(90, 90, 100), width=3)
    d.rectangle([x0 + 2, y0 + 2, x1 - 2, y0 + 70], fill=(34, 34, 40))
    txt(d, "REAPER  -  Minha Música.RPP", (x0 + 30, y0 + 36), fonte(34, "s"), BRANCO, "lm")
    # régua + linhas
    painel = 330
    for i in range(10):
        xx = x0 + painel + i * 72
        d.line([(xx, y0 + 80), (xx, y0 + 1150)], fill=(56, 56, 64), width=2)
        txt(d, str(i + 1), (xx + 6, y0 + 84), fonte(22, "r"), CINZA)
    org = clamp((t - 32.0) / 0.8)
    for i, (nome, cor, mudo) in enumerate(FAIXAS):
        y = y0 + 120 + i * 112
        ti = 30.6 + i * 0.06
        if t < ti:
            continue
        kf = entra(t, ti, 0.3)
        c_ef = mistura((90, 90, 96), cor, clamp(org * 9 - i * 0.9))
        pasta = mudo is None
        dentro = i > 3
        xp = x0 + 16 + (30 if dentro else 0)
        d.rounded_rectangle([xp, y, x0 + painel - 10, y + 98], 12, fill=(58, 58, 66) if not pasta else (38, 38, 44))
        d.rectangle([xp, y, xp + 12, y + 98], fill=c_ef)
        txt(d, nome, (xp + 30, y + 34), fonte(28 if len(nome) < 14 else 24, "s"), BRANCO, "lm")
        if mudo is not None:
            d.rounded_rectangle([xp + 30, y + 60, xp + 72, y + 90], 6, fill=VERMELHO if mudo else (80, 80, 90))
            txt(d, "M", (xp + 51, y + 75), fonte(22), BRANCO, "mm")
        if not pasta:
            lx = x0 + painel + 6
            lw = (x1 - 20 - lx) * kf
            d.rounded_rectangle([lx, y + 4, lx + lw, y + 94], 8, fill=mistura((50, 50, 56), c_ef, 0.35))
            desenhar_onda(d, lx + 6, y + 8, lw - 12, 82, ONDAS[i], mistura((200, 200, 205), c_ef, 0.8))
        # destaque na guia de voz
        if i == 1 and t >= 33.34:
            kd = entra(t, 33.34, 0.3)
            d.rounded_rectangle([x0 + 8, y - 6, x1 - 8, y + 104], 16, outline=ROSA, width=int(7 * kd))
    # cursor de reprodução
    if t > 31.0:
        px = x0 + painel + 6 + ((t - 31.0) * 120) % 650
        d.line([(px, y0 + 80), (px, y0 + 1150)], fill=(255, 255, 255), width=3)


def cena_playback(base, t):
    d = ImageDraw.Draw(base)
    im = janela_playpronto(t, tipo="playback")
    im = im.crop((0, 0, im.width, 140 * 2))
    colar_janela(base, im, W / 2, 330, 1.05, clamp(entra(t, 34.55, 0.35)))
    # música = instrumental + voz
    y = 720
    x0, w = 90, 900
    env_i = ONDAS[4] * 0.7 + 0.2
    env_v = ONDAS[1]
    d.rounded_rectangle([x0 - 20, y - 40, x0 + w + 20, y + 330], 24, fill=(40, 40, 47))
    desenhar_onda(d, x0, y, w, 260, env_i, OURO)
    kv = 1 - suave((t - 35.52) / 0.6)
    if kv > 0:
        cam = Image.new("RGBA", (w, 260), (0, 0, 0, 0))
        dc = ImageDraw.Draw(cam)
        desenhar_onda(dc, 0, 0, w, 260, env_v * 0.8, ROSA + (255,))
        colar(base, cam, x0 + w / 2, y + 130 - (1 - kv) * 200, 1.0, kv)
        txt(d, "voz", (x0 + 10, y - 20), fonte(44), mistura(FUNDO, ROSA, kv))
    if t >= 35.7:
        txt(d, "voz removida", (x0 + 10, y - 20), fonte(44), mistura(FUNDO, ROSA, suave((t - 35.7) / 0.3)))
    if t >= 36.36:
        kp = entra(t, 36.36, 0.35)
        chip = Image.new("RGBA", (520, 120), (0, 0, 0, 0))
        dc = ImageDraw.Draw(chip)
        dc.rounded_rectangle([0, 0, 519, 119], 60, fill=OURO)
        txt(dc, "PLAYBACK", (260, 60), fonte(66), (35, 20, 5), "mm")
        colar(base, chip, W / 2, y + 140, kp)
    # MP3 -> pendrive
    if t >= 37.52:
        km = suave((t - 37.7) / 0.8)
        doc = Image.new("RGBA", (200, 250), (0, 0, 0, 0))
        dd = ImageDraw.Draw(doc)
        dd.polygon([(0, 0), (140, 0), (200, 60), (200, 250), (0, 250)], fill=(245, 245, 248))
        dd.polygon([(140, 0), (200, 60), (140, 60)], fill=(200, 200, 205))
        dd.rounded_rectangle([20, 140, 180, 210], 12, fill=OURO)
        txt(dd, "MP3", (100, 175), fonte(48), (35, 20, 5), "mm")
        sx, sy = 300, 1270
        ex, ey = 700, 1290
        cx = sx + (ex - sx) * km
        cy = sy + (ey - sy) * km - math.sin(km * math.pi) * 120
        # pendrive
        d.rounded_rectangle([640, 1200, 900, 1380], 28, fill=(70, 120, 220))
        d.rectangle([900, 1250, 970, 1330], fill=(190, 190, 200))
        txt(d, "pendrive", (770, 1420), fonte(38, "s"), CINZA, "mm")
        colar(base, doc, cx, cy, entra(t, 37.52, 0.3) * (1 - 0.5 * km), 1 - clamp((km - 0.85) / 0.15))


def cena_dormir(base, t):
    k = suave((t - 38.85) / 0.5)
    noite = Image.new("RGBA", (W, H), (10, 14, 40, int(200 * k)))
    base.alpha_composite(noite)
    d = ImageDraw.Draw(base)
    rng = random.Random(3)
    for _ in range(60):
        x, y = rng.randrange(W), rng.randrange(1300)
        b = 0.5 + 0.5 * math.sin(t * 3 + x)
        r = rng.choice([2, 3, 4])
        d.ellipse([x - r, y - r, x + r, y + r], fill=mistura((10, 14, 40), BRANCO, k * b))
    km = entra(t, 39.0, 0.5)
    if km > 0:
        cx, cy, r = W / 2 + 120, 520, 210 * km
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(250, 230, 160))
        d.ellipse([cx - r + 90 * km, cy - r - 40 * km, cx + r + 90 * km, cy + r - 40 * km], fill=(18, 22, 52))
    for i in range(3):
        t0 = 40.62 + i * 0.35
        if t < t0:
            continue
        kz = (t - t0)
        txt(d, "z", (W / 2 - 180 + i * 70 + kz * 40, 860 - i * 60 - kz * 90), fonte(70 + i * 28),
            mistura((18, 22, 52), BRANCO, clamp(1 - kz / 2.5)), "mm")
    if t >= 39.42:
        kc = entra(t, 39.42, 0.35)
        chip = Image.new("RGBA", (700, 130), (0, 0, 0, 0))
        dc = ImageDraw.Draw(chip)
        dc.rounded_rectangle([0, 0, 699, 129], 65, fill=VERDE)
        txt(dc, "Setlist 14/14 pronta", (350, 65), fonte(56), BRANCO, "mm")
        colar(base, chip, W / 2, 1180, kc)


def cena_final(base, t):
    d = ImageDraw.Draw(base)
    k = entra(t, 41.85, 0.5)
    brilho = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    ImageDraw.Draw(brilho).ellipse([150, 150, 750, 750], fill=(245, 170, 35, 110))
    colar(base, brilho.filter(ImageFilter.GaussianBlur(100)), W / 2, 640, k)
    colar(base, LOGO, W / 2, 640, 1.5 * k)
    kt = entra(t, 42.0, 0.4)
    if kt > 0:
        txt(d, "PlayPronto", (W / 2, 950), fonte(int(140 * kt)), BRANCO, "mm")
        txt(d, "Playback e VS com IA", (W / 2, 1060), fonte(52, "s"), mistura(FUNDO, CINZA, kt), "mm")
        txt(d, "direto no Reaper", (W / 2, 1125), fonte(52, "s"), mistura(FUNDO, CINZA, kt), "mm")
    kl = entra(t, 42.75, 0.4)
    if kl > 0:
        pulso = 1 + 0.04 * math.sin((t - 42.75) * 6)
        chip = Image.new("RGBA", (640, 150), (0, 0, 0, 0))
        dc = ImageDraw.Draw(chip)
        dc.rounded_rectangle([0, 0, 639, 149], 75, fill=OURO)
        txt(dc, "Link na bio", (320, 75), fonte(76), (35, 20, 5), "mm")
        colar(base, chip, W / 2, 1360, kl * pulso)


CENAS = [
    (0.0, 7.9, cena_problema),
    (7.9, 13.35, cena_internet),
    (13.35, 18.1, cena_produto),
    (18.1, 22.6, cena_janela),
    (22.6, 30.2, cena_processando),
    (30.2, 34.55, cena_reaper),
    (34.55, 38.85, cena_playback),
    (38.85, 41.85, cena_dormir),
    (41.85, FIM, cena_final),
]


def quadro(t):
    base = FUNDO_IMG.copy()
    for ini, fim, fn in CENAS:
        if ini <= t < fim:
            # transição: leve fade de entrada
            fn(base, t)
            kin = clamp((t - ini) / 0.18) if ini > 0 else 1
            if kin < 1:
                base = Image.blend(FUNDO_IMG, base, kin)
            break
    if t >= 38.85 and t < 41.85:
        pass
    legenda(base, t)
    # marca d'água discreta
    if 13.35 < t < 41.85:
        d = ImageDraw.Draw(base)
        base.alpha_composite(LOGO.resize((56, 56), Image.LANCZOS), (40, 40))
        txt(d, "PlayPronto", (108, 68), fonte(34), (200, 200, 205), "lm")
    # fade final
    if t > FIM - 0.6:
        base = Image.blend(base, Image.new("RGBA", (W, H), (0, 0, 0, 255)), clamp((t - (FIM - 0.6)) / 0.6))
    return base.convert("RGB")


# ------------------------------------------------------------------ áudio: narração + batida + efeitos
def gerar_audio(destino, com_narracao=True):
    sr = 44100
    # mp3 -> wav com ffmpeg (soundfile nem sempre lê mp3)
    tmp = AQUI / "_narracao.wav"
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(AQUI / "narracao.mp3"), "-ac", "1", "-ar", str(sr),
                    str(tmp)], check=True)
    narr, _ = sf.read(str(tmp), dtype="float32")
    tmp.unlink()
    n = int(FIM * sr)
    mix = np.zeros(n, dtype=np.float32)
    if com_narracao:
        mix[: len(narr)] += narr[:n] * 1.0

    def add(sinal, t0, vol=1.0):
        i = int(t0 * sr)
        j = min(n, i + len(sinal))
        if i < n:
            mix[i:j] += sinal[: j - i] * vol

    tt = lambda d: np.arange(int(d * sr)) / sr

    def kick():
        x = tt(0.25)
        return np.sin(2 * np.pi * (50 + 90 * np.exp(-x * 30)) * x) * np.exp(-x * 14)

    def hat():
        x = tt(0.05)
        return np.random.default_rng(1).standard_normal(len(x)) * np.exp(-x * 80) * 0.5

    def pop(f=880):
        x = tt(0.12)
        return np.sin(2 * np.pi * f * x * (1 + x * 4)) * np.exp(-x * 35)

    def whoosh(d=0.45):
        x = tt(d)
        ruido = np.random.default_rng(2).standard_normal(len(x))
        ruido = np.convolve(ruido, np.ones(30) / 30, mode="same")
        return ruido * np.sin(np.pi * x / d) * 2.5

    # batida leve (90 bpm) a partir do PlayPronto
    bpm = 90
    passo = 60 / bpm
    t = 13.4
    while t < FIM - 0.8:
        add(kick(), t, 0.22)
        add(hat(), t + passo / 2, 0.10)
        t += passo
    # efeitos nos momentos-chave
    for t0 in (9.6 + 0.25, 10.64 + 0.25, 11.62 + 0.25):
        add(pop(300), t0, 0.35)  # carimbos
    for t0 in [5.15 + i * 0.08 for i in range(14)]:
        add(pop(1200), t0, 0.06)
    for t0 in (14.55, 15.6, 18.24, 19.94, 20.84, 24.48, 25.38, 25.96, 26.62, 28.58, 36.36, 39.42, 42.75):
        add(pop(900), t0, 0.18)
    add(pop(2000), 21.96, 0.3)  # clique
    for t0 in (7.9, 13.35, 22.6, 30.2, 34.55, 41.85):
        add(whoosh(), t0 - 0.2, 0.12)
    # ducking simples da batida não precisa: volume já é baixo
    mix = np.tanh(mix * 1.1) * 0.95
    fade = int(0.6 * sr)
    mix[-fade:] *= np.linspace(1, 0, fade)
    sf.write(str(destino), mix, sr)


def main():
    if "--sem-narracao" in sys.argv:
        # reaproveita o vídeo já renderizado e troca só o áudio (efeitos + batida, sem voz)
        video = AQUI / "PlayPronto_anuncio.mp4"
        audio = AQUI / "PlayPronto_efeitos.wav"
        gerar_audio(audio, com_narracao=False)
        saida = AQUI / "PlayPronto_anuncio_sem_narracao.mp4"
        subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-map", "0:v",
                        "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                        "-movflags", "+faststart", str(saida)], check=True)
        print("vídeo:", saida)
        print("áudio dos efeitos:", audio)
        return
    if "--previa" in sys.argv:
        for t in (2.0, 7.6, 11.9, 14.9, 17.5, 19.0, 21.0, 27.0, 29.2, 33.6, 36.8, 38.3, 40.9, 43.5):
            quadro(t).save(AQUI / f"previa_{t:05.1f}.png")
        print("prévias salvas")
        return
    audio = AQUI / "_audio.wav"
    gerar_audio(audio)
    saida = AQUI / "PlayPronto_anuncio.mp4"
    proc = subprocess.Popen(
        [FF, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-i", str(audio), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(saida)],
        stdin=subprocess.PIPE)
    total = int(FIM * FPS)
    for i in range(total):
        proc.stdin.write(quadro(i / FPS).tobytes())
        if i % 150 == 0:
            print(f"  quadro {i}/{total}", flush=True)
    proc.stdin.close()
    proc.wait()
    audio.unlink()
    print("vídeo:", saida)


if __name__ == "__main__":
    main()
