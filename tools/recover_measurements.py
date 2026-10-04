#!/usr/bin/env python3
"""Recover retained measurements over USB without toggling reset/DTR."""
import argparse
import json
import os
from pathlib import Path
import select
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bridge'))
from bridge import Store

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('port', help='USB serial device path')
args = parser.parse_args()
fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
try:
    os.write(fd, b'measurements\n')
    deadline, buf = time.monotonic() + 10, b''
    while time.monotonic() < deadline:
        if not select.select([fd], [], [], .1)[0]: continue
        buf += os.read(fd, 65536)
        while b'\n' in buf:
            raw, buf = buf.split(b'\n', 1)
            try: message = json.loads(raw)
            except (ValueError, UnicodeDecodeError): continue
            if not isinstance(message, dict) or 'samples' not in message: continue
            samples = message['samples']
            store = Store()
            count = store.save_measurements(samples) if samples else 0
            store.db.close()
            print(f'Recovered {count} measurements into local SQLite history')
            sys.exit(0)
    raise SystemExit('No measurement response within 10 seconds')
finally:
    os.close(fd)
