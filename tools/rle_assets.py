"""Lossless run encoding of quantized RGB565 + 8-bit coverage for themed sprites."""
from itertools import groupby

def rgba_runs(image):
    pixels = [(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3), a) if a else (0, 0)
              for r, g, b, a in image.convert('RGBA').get_flattened_data()]
    encoded = []
    for (color, alpha), group in groupby(pixels):
        length = sum(1 for _ in group)
        while length:
            count = min(length, 255)
            encoded.extend((count, color & 255, color >> 8, alpha))
            length -= count
    # Verify the asset conversion, including transparent edge coverage.
    decoded = []
    for i in range(0, len(encoded), 4):
        n, lo, hi, alpha = encoded[i:i+4]
        decoded.extend([(lo | (hi << 8), alpha)] * n)
    assert decoded == pixels
    return encoded

def write_runs(f, name, frames):
    offsets, data = [], []
    for frame in frames:
        offsets.append(len(data))
        data.extend(rgba_runs(frame))
    f.write('const uint32_t ' + name + '_offsets[] PROGMEM = {' + ','.join(map(str, offsets)) + '};\n')
    f.write('const uint8_t ' + name + '_rle[] PROGMEM = {\n')
    for i in range(0, len(data), 32):
        f.write(','.join(map(str, data[i:i+32])) + ',\n')
    f.write('};\n')
    return len(data)
