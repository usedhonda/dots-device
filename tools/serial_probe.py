"""Query the real device and capture its framebuffer without toggling reset lines."""
import argparse
import json
import os
import select
import sys
import time
from pathlib import Path
from PIL import Image

p = argparse.ArgumentParser()
p.add_argument('--port', default='/dev/cu.usbmodem1101')
p.add_argument('--seconds', type=float, default=6)
p.add_argument('--warmup', type=float, default=12)
p.add_argument('--command', action='append', default=[])
p.add_argument('--screenshot', type=Path)
a = p.parse_args()
print('Opening USB can reset the device; this probe never toggles reset lines or reopens the port.', file=sys.stderr)
fd = os.open(a.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
try:
    time.sleep(a.warmup)
    # Match the old input-buffer reset without touching termios or modem lines.
    while select.select([fd], [], [], 0)[0]:
        if not os.read(fd, 65536):
            break
    for command in a.command:
        os.write(fd, (command + '\n').encode('ascii'))
        time.sleep(.2)
    if a.screenshot:
        os.write(fd, b'screenshot\n')
    end = time.monotonic() + a.seconds
    pixels, size = [], None
    pending = bytearray()
    while time.monotonic() < end:
        if not select.select([fd], [], [], .2)[0]:
            continue
        pending.extend(os.read(fd, 65536))
        while b'\n' in pending:
            raw, _, pending = pending.partition(b'\n')
            line = raw.decode('ascii', 'replace').strip()
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
finally:
    os.close(fd)
