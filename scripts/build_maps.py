"""Build the web floor maps from the source floor plans.

    python scripts/build_maps.py

Reads   scripts/source-maps/lantai-N.(png|jpg)   (the original plans)
Writes  static/maps/lantai-N.png    optimised PNG (fallback)
        static/maps/lantai-N.webp   smaller WebP (preferred by browsers)
        static/maps/lantai-N.grid.json  walkable grid used for route finding

The Lantai 2-4 sources are presentation slides, so they are cropped to the
plan itself. Room coordinates in data/rooms.json are measured in the cropped
image, so keep CROP in sync with them if you ever replace a source image.
To add a floor whose image you haven't got yet, just leave it out — the app
shows "Map not available" for floors without an image.
"""
import base64
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.paths import MAPS_DIR, ROOMS_JSON  # noqa: E402

SOURCE_DIR = os.path.join(ROOT, 'scripts', 'source-maps')

# (left, top, right, bottom) in source pixels; None = use the whole image.
CROP = {1: None, 2: (240, 338, 1787, 1349), 3: (245, 318, 1699, 1343), 4: (233, 344, 1548, 1333)}
GRID_STEP = {1: 6, 2: 8, 3: 8, 4: 8}      # map units per grid cell
WALL_GRAY = 215                            # darker than this = any drawn line (building outline)
ROUTE_WALL_GRAY = 150                      # darker than this = wall that blocks a route
# (thin light lines — door swings, furniture, dimensions — must not seal corridors)
MAX_WIDTH = 1600                           # never ship bigger images than this


def source_path(n):
    for ext in ('png', 'jpg', 'jpeg', 'webp'):
        p = os.path.join(SOURCE_DIR, f'lantai-{n}.{ext}')
        if os.path.exists(p):
            return p
    return None


def load_floor(n):
    img = Image.open(source_path(n)).convert('RGB')
    if CROP.get(n):
        img = img.crop(CROP[n])
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    return img


def save_images(n, img):
    png = os.path.join(MAPS_DIR, f'lantai-{n}.png')
    webp = os.path.join(MAPS_DIR, f'lantai-{n}.webp')
    # Plans are line drawings with a few highlight colours: a 128-colour palette
    # is visually identical and a fraction of the size.
    img.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(png, optimize=True)
    img.save(webp, 'WEBP', quality=82, method=4)
    return os.path.getsize(png), os.path.getsize(webp)


def walkable_grid(n, img, floor):
    """1 = blocked, 0 = walkable, sampled every GRID_STEP map units.

    Blocked: drawn walls/lines, everything outside the building outline, and
    the floor's listed voids (atrium openings, escalator wells). Rooms are NOT
    baked in — the browser blocks them itself so the destination can be entered.
    """
    w, h = floor['width'], floor['height']
    img = img.resize((w, h))
    gray = np.asarray(img.convert('L'))
    walls = gray < WALL_GRAY
    # Outside = everything reachable from the image border without crossing a
    # (generously thickened) line. Door gaps in the outer wall get closed first.
    closed = ndi.binary_dilation(walls, iterations=10)
    labels, _ = ndi.label(~closed)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    outside = np.isin(labels, list(border))
    outside = ndi.binary_dilation(outside, iterations=10) & ~ndi.binary_dilation(walls, iterations=2) | outside
    # Where the drawing leaves the outer wall open, rooms.json lists areas
    # that are inside the building anyway.
    for x0, y0, x1, y1 in floor.get('inside', []):
        outside[max(0, y0):y1, max(0, x0):x1] = False
    blocked = ndi.binary_dilation(gray < ROUTE_WALL_GRAY, iterations=1) | outside
    for x0, y0, x1, y1 in floor.get('voids', []):
        blocked[max(0, y0):y1, max(0, x0):x1] = True

    step = GRID_STEP[n]
    cols, rows = -(-w // step), -(-h // step)
    grid = np.zeros((rows, cols), dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            cell = blocked[r * step:(r + 1) * step, c * step:(c + 1) * step]
            # a cell is walkable when most of it is free — thin lines don't close corridors
            grid[r, c] = 1 if cell.mean() > 0.55 else 0
    bits = np.packbits(grid.flatten())
    return {'step': step, 'cols': cols, 'rows': rows,
            'blocked': base64.b64encode(bits.tobytes()).decode('ascii')}


def main():
    os.makedirs(MAPS_DIR, exist_ok=True)
    with open(ROOMS_JSON, encoding='utf-8') as f:
        floors = {fl['floor']: fl for fl in json.load(f)['floors']}
    for n, floor in sorted(floors.items()):
        if not source_path(n):
            print(f'Lantai {n}: no source image in scripts/source-maps/ — skipped (shows "Map not available")')
            continue
        img = load_floor(n)
        png, webp = save_images(n, img)
        print(f'Lantai {n}: {img.width}x{img.height}px  png {png // 1024} KB, webp {webp // 1024} KB')
        if n in CROP and CROP[n]:
            cw, ch = CROP[n][2] - CROP[n][0], CROP[n][3] - CROP[n][1]
            if (cw, ch) != (floor['width'], floor['height']):
                print(f'  WARNING: rooms.json says {floor["width"]}x{floor["height"]} but the crop is {cw}x{ch}')
        if 'walkable' not in floor:          # floors without a simple walkable box get a traced grid
            grid = walkable_grid(n, img, floor)
            with open(os.path.join(MAPS_DIR, f'lantai-{n}.grid.json'), 'w', encoding='utf-8') as f:
                json.dump(grid, f, separators=(',', ':'))
            print(f'  route grid {grid["cols"]}x{grid["rows"]}')


if __name__ == '__main__':
    main()
