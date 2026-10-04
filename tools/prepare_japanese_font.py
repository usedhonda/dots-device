"""Generate the compact 2-bit Japanese UI atlas from an explicit font file.

The input font is read in place and never copied into the repository. Output is
fixed-size, sorted and reproducible, making lookup a small binary search.
"""
import argparse
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'firmware/kai_companion/japanese_font_atlas.h'
SIZE = 16
FONT_SOURCE_URL = 'https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf'
FONT_SOURCE_SHA256 = '68a3fc98800b2a27b371f2fb79991daf3633bd89309d4ffaa6946fd587f375b5'

def jis_level1():
    chars = set(range(0x20, 0x7f)) | set(range(0x3041, 0x30a0)) | set(range(0x30a1, 0x3100))
    chars |= set(map(ord, '　、。，．・：；？！゛゜´｀¨＾￣＿ヽヾゝゞ〃仝々〆〇ー―‐／＼～∥｜…‥‘’“”（）〔〕［］｛｝〈〉《》「」【】＋－±×÷＝≠＜＞≦≧∞∴♂♀°′″℃￥＄¢£％＃＆＊＠§☆★○●◎◇◆□■△▲▽▼※〒→←↑↓'))
    for sj in range(0x889f, 0x9873):
        try:
            c = bytes((sj >> 8, sj & 255)).decode('cp932')
        except UnicodeDecodeError:
            continue
        chars.add(ord(c))
    return sorted(chars)

def raster_glyph(font, cp, size, bits):
    # One baseline for every character, including small kana and punctuation.
    scale = 4
    baseline = round(size * 0.875)
    box = font.getbbox(chr(cp), anchor='ls')
    left, top, right, bottom = [int(v // scale) for v in box[:2]] + [int((v + scale - 1) // scale) for v in box[2:]]
    width, height = max(1, right-left), max(1, bottom-top)
    im = Image.new('L', (width*scale, height*scale), 0)
    ImageDraw.Draw(im).text((-left*scale, -top*scale), chr(cp), font=font, fill=255, anchor='ls')
    im = im.resize((width, height), Image.Resampling.LANCZOS)
    levels = (1 << bits)-1
    values = [min(levels, (a*levels+127)//255) for a in im.getdata()]
    per_byte = 8//bits
    pix = bytearray((len(values)+per_byte-1)//per_byte)
    for i,a in enumerate(values): pix[i//per_byte] |= a << ((per_byte-1-i%per_byte)*bits)
    # Keep the measured advance, widening only when antialias coverage reaches
    # the next cell (some Latin glyphs have a one-pixel right overhang).
    advance = max(round(font.getlength(chr(cp))/scale), left + width)
    return cp, advance, left, baseline+top, width, height, pix


def write_atlas(out, glyphs, prefix, typename, size, font_path):
    digest = hashlib.sha256(font_path.read_bytes()).hexdigest()
    if digest != FONT_SOURCE_SHA256:
        raise ValueError(f'unsupported font SHA-256: {digest}')
    with out.open('w') as f:
        f.write('// Generated from Noto Sans CJK JP Regular (SIL OFL 1.1).\n')
        f.write('// Font copyright: Copyright 2014-2021 Adobe (http://www.adobe.com/).\n')
        f.write('// Noto is a trademark of Google Inc.\n')
        f.write(f'// Source: {FONT_SOURCE_URL}\n')
        f.write(f'// Font SHA-256: {digest}\n')
        f.write('// License: licenses/NotoSansCJK-OFL.txt\n')
        f.write('#pragma once\n#include <Arduino.h>\n')
        f.write(f'static constexpr uint8_t {prefix.upper()}_WIDTH={size}, {prefix.upper()}_HEIGHT={size};\n')
        f.write(f'struct {typename} {{ uint32_t codepoint; uint8_t advance; int8_t xOffset, yOffset; uint8_t width, height; const uint8_t *bitmap; }};\n')
        for i, (*_, pix) in enumerate(glyphs):
            f.write(f'static const uint8_t {prefix}_{i}[{len(pix)}] PROGMEM = {{'+','.join(map(str,pix))+'};\n')
        f.write(f'static const {typename} {prefix}_glyphs[] PROGMEM = {{\n')
        for i,(cp,adv,x,y,w,h,_) in enumerate(glyphs): f.write(f'{{{cp},{adv},{x},{y},{w},{h},{prefix}_{i}}},\n')
        f.write(f'}};\nstatic constexpr size_t {prefix}_glyph_count = sizeof({prefix}_glyphs)/sizeof({prefix}_glyphs[0]);\n')
    print(f'generated {len(glyphs)} glyphs, {sum(len(g[-1]) for g in glyphs)} bitmap bytes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', required=True, type=Path, help='path to NotoSansCJKjp-Regular.otf')
    parser.add_argument('--output', type=Path, default=OUT, help=f'output header (default: {OUT})')
    args = parser.parse_args()
    font = ImageFont.truetype(str(args.font), SIZE*4)
    glyphs = [raster_glyph(font, cp, SIZE, 2) for cp in jis_level1() if font.getmask(chr(cp)).getbbox() or cp in (32, 0x3000)]
    by_cp = {g[0]: g for g in glyphs}
    # Regression: proportional ASCII uses font advances, and small kana keeps
    # its lower position on the same baseline rather than being top-aligned.
    assert by_cp[ord('K')][1] > by_cp[ord('I')][1]
    assert by_cp[ord('W')][1] >= by_cp[ord('W')][2] + by_cp[ord('W')][4]
    assert by_cp[ord('ッ')][3] > by_cp[ord('メ')][3]
    assert by_cp[ord('、')][3] > by_cp[ord('ッ')][3]
    write_atlas(args.output, glyphs, 'japanese_font', 'JapaneseFontGlyph', SIZE, args.font)

if __name__ == '__main__': main()
