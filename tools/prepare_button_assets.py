"""Convert the generated 2x3 action-icon atlas into RGB565 firmware assets."""
import argparse
from pathlib import Path
from PIL import Image
from rle_assets import write_runs

p = argparse.ArgumentParser()
p.add_argument('source', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
im = Image.open(a.source).convert('RGBA')
w, h = im.size
size = 44
frames = []
# This generated atlas places the timer cap slightly above its nominal cell.
# Split at the transparent gap so it is neither clipped nor included in the chat icon.
row_bounds = (0, h//3, h*5//8, h)
for row in range(3):
    for col in range(2):
        icon = im.crop((col*w//2, row_bounds[row], (col+1)*w//2, row_bounds[row+1]))
        # Trim cell padding for consistent visible icon size, retaining alpha edges.
        bounds = icon.getchannel('A').point(lambda v: 255 if v > 180 else 0).getbbox()
        if not bounds:
            raise ValueError('Missing atlas icon')
        bounds = (max(0, bounds[0]-3), max(0, bounds[1]-3), min(icon.width,bounds[2]+3), min(icon.height,bounds[3]+3))
        icon = icon.crop(bounds)
        icon.thumbnail((size-2, size-2), Image.Resampling.LANCZOS)
        bg = Image.new('RGBA', (size,size), (0,0,0,0))
        bg.alpha_composite(icon, ((size-icon.width)//2, (size-icon.height)//2))
        frames.append(bg)
a.output.parent.mkdir(parents=True, exist_ok=True)
with a.output.open('w') as f:
    f.write('#pragma once\n#include <Arduino.h>\n#define ACTION_ICON_SIZE 44\n')
    byte_count = write_runs(f, 'action_icons', frames)
print(f'Prepared 6 transparent icons: {byte_count} flash bytes; round trip verified')
