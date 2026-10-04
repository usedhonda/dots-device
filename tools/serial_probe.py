"""Query the real device and capture its framebuffer without toggling reset lines."""
import argparse
import json
import time
from pathlib import Path
import serial
from PIL import Image

p = argparse.ArgumentParser()
p.add_argument('--port', default='/dev/cu.usbmodem1101')
p.add_argument('--seconds', type=float, default=6)
p.add_argument('--warmup', type=float, default=12)
p.add_argument('--command', action='append', default=[])
p.add_argument('--screenshot', type=Path)
a = p.parse_args()
s = serial.Serial()
s.port, s.baudrate, s.timeout = a.port, 115200, 0.2
s.dtr = s.rts = False
s.open()
time.sleep(a.warmup)
s.reset_input_buffer()
for command in a.command:
    s.write((command + '\n').encode()); s.flush(); time.sleep(.2)
if a.screenshot:
    s.write(b'screenshot\n'); s.flush()
end = time.monotonic() + a.seconds
pixels, size = [], None
while time.monotonic() < end:
    line = s.readline().decode('ascii', 'replace').strip()
    if line.startswith('FRAME_BEGIN '):
        size = tuple(map(int, line.split()[1:])); pixels = []; continue
    if line == 'FRAME_END' and size:
        if len(pixels) != size[0]*size[1]: raise RuntimeError('Incomplete framebuffer')
        rgb = bytes(channel for v in pixels for channel in (((v>>11)&31)*255//31, ((v>>5)&63)*255//63, (v&31)*255//31))
        a.screenshot.parent.mkdir(parents=True, exist_ok=True)
        Image.frombytes('RGB', size, rgb).save(a.screenshot)
        print(json.dumps({'screenshot': str(a.screenshot), 'width':size[0], 'height':size[1]}))
        size = None
        continue
    if size:
        try: pixels.extend(int(v,16) for v in line.split())
        except ValueError: pass
    elif line.startswith('{'):
        try:
            value = json.loads(line)
            # Only firmware's defined diagnostics; no arbitrary serial log dump.
            if value.get('type') in {'health','telemetry','command','touch','boot','network','motion'}: print(json.dumps(value))
        except ValueError: pass
s.close()
