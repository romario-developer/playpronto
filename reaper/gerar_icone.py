"""Gera o ícone do PlayPronto para a barra de ferramentas do REAPER.
Formato do REAPER: tira com 3 estados lado a lado (normal | mouse em cima | clicado).
Tamanhos: 30px (100%), 45px (150%), 60px (200%) + logo.png para a janela do script."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

AQUI = Path(__file__).resolve().parent / "icones"
S = 512  # desenha grande e reduz (fica liso)


def desenhar(brilho=1.0, afundado=False):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    m = 28 if not afundado else 40
    # fundo: degradê laranja -> dourado
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        r = int((255 - 25 * t) * brilho)
        g = int((150 + 60 * (1 - t)) * brilho)
        b = int((30 + 20 * t) * brilho)
        gd.line([(0, y), (S, y)], fill=(min(r, 255), min(g, 255), min(b, 255), 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, S - m, S - m], radius=110, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    # triângulo de play (lado esquerdo)
    cx, cy = 215, S // 2
    tri = [(cx - 80, cy - 125), (cx - 80, cy + 125), (cx + 120, cy)]
    sombra = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).polygon([(x + 8, y + 10) for x, y in tri], fill=(90, 40, 0, 120))
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(10)))
    d.polygon(tri, fill=(255, 255, 255, 255))
    # 3 barras = faixas separadas (lado direito)
    for i, h in enumerate([150, 230, 110]):
        x = 350 + i * 42
        d.rounded_rectangle([x, cy - h / 2, x + 26, cy + h / 2], radius=13, fill=(40, 25, 15, 235))
    return img


def tira(tam):
    estados = [desenhar(1.0), desenhar(1.12), desenhar(0.85, afundado=True)]
    out = Image.new("RGBA", (tam * 3, tam), (0, 0, 0, 0))
    for i, e in enumerate(estados):
        out.paste(e.resize((tam, tam), Image.LANCZOS), (i * tam, 0))
    return out


if __name__ == "__main__":
    for pasta, tam in [("", 30), ("150", 45), ("200", 60)]:
        dst = AQUI / pasta
        dst.mkdir(parents=True, exist_ok=True)
        tira(tam).save(dst / "playpronto.png")
    desenhar().resize((64, 64), Image.LANCZOS).save(AQUI / "logo.png")
    desenhar().resize((256, 256), Image.LANCZOS).save(AQUI / "preview.png")
    print("ícones gerados em", AQUI)
