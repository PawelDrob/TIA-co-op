"""Draws the two icons of tray.py, each size by itself so that a small one stays sharp. Run it only to change them; the .ico files
are committed. Each dashboard has its colour and letter, so the two can be told apart without the colour too. The colours are Catppuccin
Mocha's, as the dashboards' dark mode: its base for the letter, and for the tile an accent the pages do not use, as their peach and red
say something there. The name stays off the icon: at 16 px a word cannot be read. The tooltip and the menu carry it.

    python tools\\dashboard\\icons\\make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
FINE = 8        # drawn this many times larger, then reduced: smooth edges
BASE, MAUVE, GREEN = '#1e1e2e', '#cba6f7', '#a6e3a1'


def letter_d(draw_on, size, ink, background):
    left, top, right, bottom, stem = size * .27, size * .20, size * .78, size * .80, size * .17
    mid = (top + bottom) / 2
    draw_on.rectangle((left, top, mid, bottom), fill=ink)
    draw_on.pieslice((2 * mid - right, top, right, bottom), -90, 90, fill=ink)
    draw_on.rectangle((left + stem, top + stem, mid, bottom - stem), fill=background)
    draw_on.pieslice((2 * mid - right + stem, top + stem, right - stem, bottom - stem), -90, 90, fill=background)


def letter_t(draw_on, size, ink, background):
    left, top, right, bottom, stem = size * .20, size * .20, size * .80, size * .80, size * .19
    mid = size / 2
    draw_on.rectangle((left, top, right, top + stem), fill=ink)
    draw_on.rectangle((mid - stem / 2, top, mid + stem / 2, bottom), fill=ink)


def draw(size, colour, letter):
    s = size * FINE
    image = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s * .2, fill=colour)
    letter(d, s, BASE, colour)
    return image.resize((size, size), Image.LANCZOS)


def make(name, colour, letter):
    images = [draw(size, colour, letter) for size in SIZES]
    images[-1].save(HERE / name, format='ICO', sizes=[(n, n) for n in SIZES], append_images=images[:-1])


if __name__ == '__main__':
    make('development.ico', MAUVE, letter_d)
    make('tia.ico', GREEN, letter_t)
