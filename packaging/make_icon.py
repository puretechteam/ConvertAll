"""Draw the ConvertAll icon (two circling arrows on a rounded square) -> convertall/assets/."""

from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
ASSETS = Path(__file__).resolve().parent.parent / "convertall" / "assets"


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # vertical gradient tile
    top, bottom = (99, 102, 241), (139, 92, 246)
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)
    # two arcs with arrowheads
    w = 92
    box = [250, 250, S - 250, S - 250]
    d.arc(box, 200, 340, fill="white", width=w)
    d.arc(box, 20, 160, fill="white", width=w)
    cx = cy = S / 2
    r = (box[2] - box[0]) / 2
    import math
    for ang in (340, 160):
        a = math.radians(ang)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        tx, ty = -math.sin(a), math.cos(a)  # tangent (clockwise direction)
        nx, ny = math.cos(a), math.sin(a)
        L = 120
        d.polygon([(x + tx * L, y + ty * L), (x + nx * L, y + ny * L), (x - nx * L, y - ny * L)], fill="white")
    return img


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = draw()
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png")
    icon.save(ASSETS / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote", ASSETS)
