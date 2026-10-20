"""Gera ui/assets/icon.ico e icon.png (Switch com teclado e mouse na tela) para o .exe e o app."""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent / "ui" / "assets"
S = 1024        # desenha grande e reduz (antisserrilhado)
BLUE, RED, BODY, SCREEN = "#00B4D8", "#E8445A", "#2A2D34", "#0E0F12"
KEY, KEY_DARK, INK = "#E8E9EC", "#9AA0AA", "#0E0F12"


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top, bot = 196, 828
    mid = (top + bot) // 2
    # Joy-Cons (cantos externos bem arredondados) e corpo
    d.rounded_rectangle((24, top, 248, bot), 124, fill=BLUE, corners=(True, False, False, True))
    d.rounded_rectangle((776, top, 1000, bot), 124, fill=RED, corners=(False, True, True, False))
    d.rectangle((236, top, 788, bot), fill=BODY)
    # analógicos e botões
    for cx, cy in ((140, mid - 150), (884, mid + 150)):
        d.ellipse((cx - 50, cy - 50, cx + 50, cy + 50), fill=INK)
        d.ellipse((cx - 32, cy - 32, cx + 32, cy + 32), fill="#33363D")
    for bx, by in ((140, mid + 120), (884, mid - 120)):
        for dx, dy in ((0, -44), (-44, 0), (44, 0), (0, 44)):
            d.ellipse((bx + dx - 22, by + dy - 22, bx + dx + 22, by + dy + 22), fill=INK)
    # tela
    d.rounded_rectangle((268, top + 36, 756, bot - 36), 28, fill=SCREEN)
    # teclado (4x3 + espaço) e mouse, centralizados na tela
    kw, gap, mw, mh, sep = 52, 12, 100, 180, 34
    kbw = 4 * kw + 3 * gap
    x0 = 512 - (kbw + sep + mw) // 2
    y0 = mid - kbw // 2
    for row in range(3):
        for i in range(4):
            x, y = x0 + i * (kw + gap), y0 + row * (kw + gap)
            d.rounded_rectangle((x, y, x + kw, y + kw), 10, fill=KEY)
    y = y0 + 3 * (kw + gap)
    d.rounded_rectangle((x0 + kw // 2, y, x0 + kbw - kw // 2, y + kw), 10, fill=KEY)
    mx0 = x0 + kbw + sep
    my0 = mid - mh // 2
    mx1, my1 = mx0 + mw, my0 + mh
    d.rounded_rectangle((mx0, my0, mx1, my1), mw // 2, fill=KEY)
    cx = (mx0 + mx1) // 2
    d.line((cx, my0 + 4, cx, my0 + 76), fill=KEY_DARK, width=8)
    d.line((mx0 + 4, my0 + 76, mx1 - 4, my0 + 76), fill=KEY_DARK, width=8)
    d.rounded_rectangle((cx - 10, my0 + 22, cx + 10, my0 + 60), 10, fill=RED)
    return img


def main():
    img = draw()
    img.resize((512, 512), Image.LANCZOS).save(ASSETS / "icon.png")
    img.resize((256, 256), Image.LANCZOS).save(
        ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
