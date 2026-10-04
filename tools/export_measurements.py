#!/usr/bin/env python3
"""Export locally collected device measurements to CSV (no credentials needed)."""
import argparse
import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=ROOT / '.local/device-measurements.csv')
args = parser.parse_args()
db = sqlite3.connect(f"file:{ROOT / '.local/bridge.sqlite3'}?mode=ro", uri=True)
rows = db.execute('SELECT received_at,sample FROM measurements ORDER BY received_at,rowid')
fields = ['received_at', 'boot_id', 'seq', 'uptime_ms', 'stage', 'battery_mv', 'min_battery_mv', 'wifi_status', 'rssi', 'http_code', 'reset_reason']
with args.output.open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    count = 0
    for received_at, sample in rows:
        writer.writerow(dict(json.loads(sample), received_at=received_at))
        count += 1
print(f'Exported {count} measurements: {args.output}')
