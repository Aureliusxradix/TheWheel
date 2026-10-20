"""Render the synthetic flyer fixture (tests/fixtures/flyer_image/input.png)."""
import random
import sys
from PIL import Image, ImageDraw, ImageFont

out = sys.argv[1]
W, H = 900, 1200
img = Image.new("RGB", (W, H), (24, 38, 52))
d = ImageDraw.Draw(img)
rnd = random.Random(7)
for _ in range(260):  # hatched fringe, so the text sits on a busy ground
    x, y = rnd.randrange(W), rnd.randrange(H)
    d.line((x, y, x + rnd.randrange(-40, 40), y + rnd.randrange(10, 60)), fill=(60, 90, 110), width=2)
serif = "/usr/share/fonts/google-noto/NotoSerif-Bold.ttf"
sans = "/usr/share/fonts/google-noto/NotoSans-Regular.ttf"
def text(y, s, size, font, fill):
    f = ImageFont.truetype(font, size)
    w = d.textlength(s, font=f)
    d.text(((W - w) / 2, y), s, font=f, fill=fill)
text(120, "POETRY", 130, serif, (240, 200, 120))
text(270, "& PROSE", 110, serif, (240, 200, 120))
text(430, "an open mic for the coast", 44, sans, (220, 230, 235))
text(610, "SUNDAY 1 NOVEMBER", 64, serif, (250, 250, 250))
text(700, "2pm – 5pm", 56, sans, (250, 250, 250))
text(830, "The Driftwood Café, Waiwera", 46, sans, (220, 230, 235))
text(900, "free entry  ·  sign up on the night", 38, sans, (180, 200, 210))
img.save(out)
