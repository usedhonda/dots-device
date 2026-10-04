"""Generate the compact native 20px atlas for fixed button labels."""
import argparse
from pathlib import Path
from PIL import ImageFont
from prepare_japanese_font import raster_glyph, write_atlas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'firmware/kai_companion/japanese_large_font_atlas.h'
SIZE = 20
LABEL_CHARS = '予定メッセージ承認待ち作業状況ノーマルダーク設定テーマ進めるやめる後で確認する送信打合出張締切私用次の今日明週一覧'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', required=True, type=Path, help='path to NotoSansCJKjp-Regular.otf')
    parser.add_argument('--output', type=Path, default=OUT, help=f'output header (default: {OUT})')
    args = parser.parse_args()
    font = ImageFont.truetype(str(args.font), SIZE*4)
    chars = set(map(ord, LABEL_CHARS + '、。？！')) | set(range(32,127)) | set(range(0x3041,0x3100))
    glyphs = [raster_glyph(font, cp, SIZE, 4) for cp in sorted(chars) if font.getmask(chr(cp)).getbbox() or cp == 32]
    by_cp = {g[0]: g for g in glyphs}
    # Guard the two regressions this atlas is intended to prevent: measured
    # proportional Latin advances, and a shared baseline for small kana.
    assert by_cp[ord('K')][1] > by_cp[ord('I')][1]
    assert by_cp[ord('W')][1] >= by_cp[ord('W')][2] + by_cp[ord('W')][4]
    assert by_cp[ord('ッ')][3] > by_cp[ord('メ')][3]
    assert by_cp[ord('、')][3] > by_cp[ord('ッ')][3]
    write_atlas(args.output, glyphs, 'japanese_large_font', 'JapaneseLargeFontGlyph', SIZE, args.font)

if __name__ == '__main__': main()
