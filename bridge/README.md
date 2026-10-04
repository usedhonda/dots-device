# Legacy Mac bridge

This is the legacy/local recovery path, not required by direct HTTPS mode. From the repository root, create `.local/bridge-token` with a random bearer token and optionally create ignored `bridge-config.json` with `{"codex_url":"codex://threads/<id>"}`. Start with:

```sh
python3 bridge/bridge.py --host 0.0.0.0 --port 8766
```

The device API uses `Authorization: Bearer TOKEN`: `GET /state`, `POST /command` with `{"id":"progress","request_id":"..."}`, `POST /choice`, and optional `POST /telemetry`. The same request ID returns the persisted response. The visible action list is `schedule` (予定), `messages` (メッセージ), `approvals` (承認待ち), and `progress` (作業状況); older command IDs remain accepted for firmware compatibility but are not advertised in state. Admin endpoints require the token even from loopback.

After an operator has confirmed a selected real interaction was received by KAI, the authenticated loopback-only `POST /admin/choice-receipt` endpoint accepts `{"interaction_id":"...","choice_id":"...","receipt_id":"...","summary":"..."}`. It only accepts a selected `source=real` interaction with the matching choice, stores the receipt id and summary idempotently, and rejects conflicting receipts. `GET /admin/choices` includes `receipt_id`, `receipt_summary`, and `receipt_at`; a receipt for an older interaction is retained without replacing the current top summary. Simulation choices cannot be marked as KAI receipts.

```sh
python3 bridge/bridge_cli.py status
python3 bridge/bridge_cli.py requests
python3 bridge/bridge_cli.py pending
python3 bridge/bridge_cli.py choices
python3 bridge/bridge_cli.py demo short   # explicit local simulation question
python3 bridge/bridge_cli.py demo four    # four-choice schedule sample
python3 bridge/bridge_cli.py demo scroll  # long test question for device scrolling
python3 bridge/bridge_cli.py demo off     # dismiss pending simulation
python3 bridge/bridge_cli.py publish summary
python3 bridge/bridge_cli.py reply REQUEST_ID completed 'Handled locally'
python3 bridge/bridge_cli.py set-state 'Live KAI relay summary' --source real
```

To publish a device question, put `{"text":"どちらにしますか","choices":[{"id":"yes","label":"はい"}],"source":"simulation"}` in a JSON file and run `python3 bridge/bridge_cli.py publish --interaction-json question.json`. Device text is one line and at most 240 Unicode characters; provide 1-4 unique choices with IDs at most 48 characters and labels at most 8 characters. `source` is explicitly `real` or `simulation`; simulation is shown as test data. The `demo` command provides explicit short, four-choice, and long-scroll simulation questions; it never sends anything externally and never cycles automatically. The device posts `{"interaction_id":"...","choice_id":"...","request_id":"..."}` to `/choice`. A repeated identical tuple is idempotent; a different choice, unknown choice, or stale interaction is rejected. `GET /admin/choices` is the local relay queue. A simulation choice updates the local summary with a no-op statement; a real choice records intent without fabricating a KAI acknowledgement.

State includes `summary_age_seconds`, `summary_source`, and `demo_enabled`. Summaries without a recorded update time, or older than 30 minutes, remain stored but are displayed as `接続できました。確認したい項目を選んでください。`; measurements and generic bridge updates do not refresh summary age.

The `progress` queue is represented as `pending_agent` with `Macに記録。KAIへの連携待ち` until an authenticated admin reply. Dashboard-entered summaries default to clearly marked simulation; `set-state --source real` is for a separately verified relay update.

For USB-free link diagnosis, authenticated loopback-only `GET /admin/device` returns in-memory `count`, `last_seen` (Unix seconds or null), and `age_seconds`. It counts successfully written `/state` responses to non-loopback clients; local probes do not count. Counters reset with the bridge process. This proves server-side response progress, not on-screen rendering or delivery of a KAI task.
Firmware may append bounded diagnostic query values `uptime_ms`, `reset_reason`, and `wifi_rssi` to `/state`; the last successful response's values appear in `/admin/device.metrics`. Missing or invalid values are omitted. This contains no SSID, password, or message content.
