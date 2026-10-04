"""Generate four antialiased action symbols as transparent firmware images."""
from pathlib import Path
from PIL import Image, ImageDraw
from rle_assets import write_runs

ROOT = Path(__file__).resolve().parents[1]
S=4
frames=[]
for n,color in enumerate(['#88BFF0','#B9A6ED','#86CDB4','#F0BF85']):
    im=Image.new('RGBA',(44*S,44*S)); d=ImageDraw.Draw(im)
    def line(points): d.line([(x*S,y*S) for x,y in points],fill=color,width=2*S,joint='curve')
    def rect(box,r=3):d.rounded_rectangle(tuple(v*S for v in box),radius=r*S,outline=color,width=2*S)
    if n==0:
        rect((7,10,37,37));line([(7,18),(37,18)])
        for x in [14,30]:line([(x,6),(x,13)])
        for x in [14,22,30]:
            for y in [24,31]:d.ellipse(((x-1)*S,(y-1)*S,(x+1)*S,(y+1)*S),fill=color)
    elif n==1:
        rect((5,8,39,32),7);line([(11,32),(11,38),(19,32)])
        for x in [14,22,30]:d.ellipse(((x-1)*S,19*S,(x+1)*S,21*S),fill=color)
    elif n==2:
        rect((9,8,35,38),5);rect((16,5,28,12),2);line([(15,24),(20,29),(30,19)])
    else:
        for x,y in [(9,27),(20,18),(31,8)]:rect((x,y,x+5,37),2)
    frames.append(im.resize((44,44),Image.Resampling.LANCZOS))
with (ROOT/'firmware/kai_companion/button_assets.h').open('w') as f:
    f.write('#pragma once\n#include <Arduino.h>\n#define ACTION_ICON_SIZE 44\n')
    size=write_runs(f,'action_icons',frames)
print('4 antialiased action icons',size,'bytes')
