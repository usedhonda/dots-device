"""Bounded serial connection trace. Opening USB can reset an ESP32-C6.

No reset commands, automatic reopen, raw logs, or arbitrary JSON fields.
Store captures under an ignored local directory (for example .local/).
"""
import argparse
import json
import math
import os
import select
import sys
import time
from pathlib import Path



NUMERIC_FIELDS = {
    'health': {'wifi', 'wifi_status', 'wifi_disconnect_reason',
               'wifi_disconnect_count', 'wifi_last_disconnect_ms', 'rssi',
               'wifi_first_connected_ms', 'wifi_first_got_ip_ms',
               'first_valid_clock_ms', 'first_tunnel_poll_ms',
               'wifi_reconnect_attempts', 'wifi_reconnect_failed_calls', 'min_heap',
               'heap', 'uptime_ms', 'reset_reason', 'last_http',
               'bridge_task_created', 'imu', 'touch', 'touch_samples', 'gestures'},
    'direct': {'http', 'polls', 'commands', 'responses', 'failures',
               'heap', 'min_heap'},
    'link': {'wifi_sleep', 'successes', 'failures', 'age_ms', 'http', 'heap'},
    'power': {'tx_power_qdbm', 'backlight_pwm', 'battery_mv'},
    'diagnostics': {'uptime_ms', 'reset_reason', 'wifi_status',
                    'bridge_task_created'},
}


def safe_diagnostic(value):
    """Allow only reviewed scalar fields; unknown schemas are discarded."""
    if not isinstance(value, dict):
        return None
    kind = value.get('type')
    if not isinstance(kind, str) or kind not in NUMERIC_FIELDS:
        return None
    result = {'type': kind}
    for key in NUMERIC_FIELDS[kind]:
        item = value.get(key)
        if isinstance(item, (bool, int, float)) and math.isfinite(item):
            result[key] = item
    if kind == 'health' and value.get('bridge') in {
            'online', 'offline', 'connecting', 'error', 'ready'}:
        result['bridge'] = value['bridge']
    if kind == 'diagnostics' and value.get('event') in {
            'boot', 'measurement_nvs_write_failed'}:
        result['event'] = value['event']
    return result if len(result) > 1 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--seconds', type=float, default=180)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 3600:
        parser.error('--seconds must be between 0 and 3600')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print('Opening USB can reset ESP32-C6. '
          'This trace opens once and never resets or reopens.', file=sys.stderr)
    started = time.monotonic()
    fd = None
    try:
        with args.output.open('x', encoding='utf-8') as output:
            def record(value):
                output.write(json.dumps({'elapsed_s': round(time.monotonic() - started, 3),
                                         **value}, allow_nan=False) + '\n')
                output.flush()

            record({'type': 'trace', 'event': 'opening',
                    'duration_s': args.seconds, 'usb_open_may_reset': True})
            # Match recover_measurements: do not touch DTR/RTS or termios.
            fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            record({'type': 'trace', 'event': 'opened'})
            next_query = time.monotonic()
            first_query = True
            pending = bytearray()
            dropping = False
            while time.monotonic() - started < args.seconds:
                now = time.monotonic()
                if now >= next_query:
                    commands = ['health', 'link', 'power'] if first_query else ['health', 'link']
                    for command in commands:
                        os.write(fd, (command + '\n').encode('ascii'))
                        record({'type': 'trace', 'event': 'query', 'command': command})
                    first_query = False
                    next_query = now + 5
                if not select.select([fd], [], [], 0.2)[0]:
                    continue
                for byte in os.read(fd, 1024):
                    if byte == 10:
                        if not dropping:
                            try:
                                value = safe_diagnostic(json.loads(pending))
                            except (ValueError, UnicodeError, OverflowError):
                                value = None
                            if value:
                                record(value)
                        pending.clear()
                        dropping = False
                    elif not dropping:
                        pending.append(byte)
                        if len(pending) > 8192:
                            pending.clear()
                            dropping = True
            record({'type': 'trace', 'event': 'completed'})
    except KeyboardInterrupt:
        print('Trace interrupted; partial capture preserved.', file=sys.stderr)
        return 130
    except OSError:
        # Exception strings can contain paths or device data; keep them private.
        print('Trace failed; partial capture preserved. No reopen attempted.', file=sys.stderr)
        return 1
    finally:
        if fd is not None:
            os.close(fd)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
