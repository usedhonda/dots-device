import json
import http.client
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import bridge


class _LockCheckingConnection:
    """Fail if a connection operation bypasses Store.lock in this test."""

    def __init__(self, connection, lock):
        self._connection = connection
        self._lock = lock

    def execute(self, *args, **kwargs):
        if not self._lock._is_owned():
            raise AssertionError("database access bypassed Store.lock")
        return self._connection.execute(*args, **kwargs)

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, *args):
        return self._connection.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = bridge.Store(Path(self.tmp.name) / "bridge.sqlite3")
        self.server = bridge.ThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler)
        self.server.token, self.server.store = "test-token", self.store
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()

    def req(self, path, method="GET", payload=None, token="test-token"):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Authorization": "Bearer " + token}
        if data: headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.load(response)

    def test_measurements_persist_deduplicate_and_validate_atomically(self):
        sample = dict(boot_id="test-boot", seq=1, uptime_ms=100, battery_mv=3800,
                      min_battery_mv=3750, wifi_status=6, rssi=0, http_code=-1,
                      reset_reason=9, stage="before_wifi")
        for _ in range(2):
            self.assertEqual(self.req("/device/measurements", "POST", {"samples": [sample]})[1]["accepted"], 1)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.req("/device/measurements", "POST", {"samples": [dict(sample, seq=2), dict(sample, seq=3, battery_mv=True)]})
        self.assertEqual(ctx.exception.code, 400)
        reopened = bridge.Store(Path(self.tmp.name) / "bridge.sqlite3")
        self.assertEqual(len(reopened.measurements()), 1)
        reopened.db.close()
        rows = self.req("/admin/device/measurements")[1]["samples"]
        self.assertEqual(rows[0]["battery_mv"], 3800)
        self.assertIn("received_at", rows[0])
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.req("/admin/device/measurements", token="")
        self.assertEqual(ctx.exception.code, 401)

    def test_compact_device_state_retains_replies_without_event_backlog(self):
        self.store.set_meta("summary", "接続しました")
        self.store.event("test", "long event" * 50)
        full = self.req("/state")[1]
        compact = self.req("/state?compact=1")[1]
        self.assertEqual(set(compact), {"summary", "summary_age_seconds", "summary_source", "demo_enabled", "interaction", "reply_request_id", "reply_status", "reply_summary"})
        self.assertEqual(compact["summary"], full["summary"])
        self.assertLess(len(json.dumps(compact)), len(json.dumps(full)))

    def test_schedule_and_messages_remain_pending_until_real_reply(self):
        for command in ("schedule", "messages"):
            reply = self.req("/command", "POST", {"id": command, "request_id": "pending-" + command})[1]
            self.assertEqual(reply["status"], "pending_agent")
            row = self.store.request("pending-" + command)
            self.assertEqual(row["status"], "pending_agent")

    def test_device_reuses_one_connection_for_complete_state_responses(self):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        client.request("GET", "/state?compact=1", headers={"Authorization": "Bearer test-token"})
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        json.loads(response.read())
        connection = client.sock
        self.assertIsNotNone(connection)
        client.request("GET", "/state?compact=1", headers={"Authorization": "Bearer test-token"})
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        json.loads(response.read())
        self.assertIs(client.sock, connection)
        client.close()

    def test_token_missing_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.req("/state", token="")
        self.assertEqual(ctx.exception.code, 401)

    def test_admin_device_is_authenticated_loopback_and_ignores_local_state_probe(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.req("/admin/device", token="")
        self.assertEqual(ctx.exception.code, 401)

        status, device = self.req("/admin/device")
        self.assertEqual(status, 200)
        self.assertEqual(device, {"last_seen": None, "age_seconds": None, "count": 0, "metrics": {}})

        self.req("/state")
        device = self.req("/admin/device")[1]
        self.assertEqual(device["count"], 0)
        self.assertIsNone(device["last_seen"])
        self.assertIsNone(device["age_seconds"])

    def test_dedup_returns_same_persisted_response(self):
        first = self.req("/command", "POST", {"id": "focus", "request_id": "same-id"})[1]
        second = self.req("/command", "POST", {"id": "focus", "request_id": "same-id"})[1]
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.recent_requests()), 1)

    def test_local_command_does_not_claim_kai_delivery(self):
        result = self.req("/command", "POST", {"id": "details", "request_id": "detail-id"})[1]
        self.assertNotIn("delivered", result.get("summary", "").lower())
        self.assertIn("KAIへの送信はまだ", result["summary"])

    def test_admin_summary_update_is_marked_simulation(self):
        result = self.req("/admin/state", "POST", {"summary": "Synthetic dashboard check"})[1]
        self.assertTrue(result["simulation"])
        self.assertEqual(self.store.meta("summary"), "Synthetic dashboard check")

    def test_progress_queues_and_reply_is_persisted_for_dedup(self):
        first = self.req("/command", "POST", {"id": "progress", "request_id": "progress-id"})[1]
        self.assertEqual(first["status"], "pending_agent")
        self.assertEqual(first["summary"], "Macに記録。KAIへの連携待ち")
        self.req("/admin/reply", "POST", {"request_id": "progress-id", "status": "completed", "summary": "KAI replied"})
        second = self.req("/command", "POST", {"id": "progress", "request_id": "progress-id"})[1]
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["summary"], "KAI replied")
        self.assertEqual(self.store.meta("summary"), "KAI replied")
        state = self.req("/state")[1]
        self.assertEqual((state["reply_request_id"], state["reply_status"], state["reply_summary"]), ("progress-id", "completed", "KAI replied"))

    def test_interaction_choice_is_persisted_idempotent_and_stale_rejected(self):
        created = self.req("/admin/interaction", "POST", {"text": "どちらにしますか", "choices": [{"id": "yes", "label": "はい"}, {"id": "no", "label": "いいえ"}], "source": "simulation"})[1]["interaction"]
        self.assertEqual(self.req("/state")[1]["interaction"]["status"], "pending")
        self.assertEqual(self.req("/choice", "POST", {"interaction_id": created["id"], "choice_id": "yes", "request_id": "r1"})[1]["status"], "recorded")
        self.assertEqual(self.req("/choice", "POST", {"interaction_id": created["id"], "choice_id": "yes", "request_id": "r1"})[1]["status"], "recorded")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.req("/choice", "POST", {"interaction_id": created["id"], "choice_id": "no", "request_id": "r2"})
        self.assertEqual(ctx.exception.code, 409)
        self.assertEqual(self.req("/admin/choices")[1]["choices"][0]["choice_id"], "yes")

    def test_interaction_validation_and_current_interaction_only(self):
        bad = {"text": "x\n", "choices": [{"id": "x", "label": "x"}], "source": "simulation"}
        with self.assertRaises(urllib.error.HTTPError) as ctx: self.req("/admin/interaction", "POST", bad)
        self.assertEqual(ctx.exception.code, 400)
        first = self.req("/admin/interaction", "POST", {"text": "one", "choices": [{"id": "a", "label": "A"}], "source": "real"})[1]["interaction"]
        second = self.req("/admin/interaction", "POST", {"text": "two", "choices": [{"id": "b", "label": "B"}], "source": "simulation"})[1]["interaction"]
        with self.assertRaises(urllib.error.HTTPError) as ctx: self.req("/choice", "POST", {"interaction_id": first["id"], "choice_id": "a", "request_id": "old"})
        self.assertEqual(ctx.exception.code, 409)
        with self.assertRaises(urllib.error.HTTPError) as ctx: self.req("/choice", "POST", {"interaction_id": second["id"], "choice_id": "unknown", "request_id": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_real_choice_receipt_is_authenticated_idempotent_and_stale_safe(self):
        first = self.req("/admin/interaction", "POST", {"text": "one", "choices": [{"id": "a", "label": "A"}], "source": "real"})[1]["interaction"]
        self.req("/choice", "POST", {"interaction_id": first["id"], "choice_id": "a", "request_id": "choice-a"})
        selected_at = self.req("/admin/choices")[1]["choices"][0]["selected_at"]

        newer = self.req("/admin/interaction", "POST", {"text": "two", "choices": [{"id": "b", "label": "B"}], "source": "real"})[1]["interaction"]
        self.req("/choice", "POST", {"interaction_id": newer["id"], "choice_id": "b", "request_id": "choice-b"})
        self.req("/admin/state", "POST", {"summary": "Newer question summary", "source": "real"})

        receipt = {"interaction_id": first["id"], "choice_id": "a", "receipt_id": "kai-1", "summary": "KAI received A"}
        result = self.req("/admin/choice-receipt", "POST", receipt)[1]
        self.assertEqual((result["status"], result["current"], result["idempotent"]), ("recorded", False, False))
        self.assertEqual(self.req("/admin/choice-receipt", "POST", receipt)[1]["idempotent"], True)
        listed = next(item for item in self.req("/admin/choices")[1]["choices"] if item["interaction_id"] == first["id"])
        self.assertEqual((listed["receipt_id"], listed["receipt_summary"]), ("kai-1", "KAI received A"))
        self.assertIsNone(self.req("/state")[1]["interaction"]["receipt_id"])
        self.assertEqual(listed["selected_at"], selected_at)
        self.assertEqual(self.req("/state")[1]["summary"], "Newer question summary")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.req("/admin/choice-receipt", "POST", {**receipt, "receipt_id": "kai-conflict"})
        self.assertEqual(ctx.exception.code, 409)

        self.req("/admin/choice-receipt", "POST", {"interaction_id": newer["id"], "choice_id": "b", "receipt_id": "kai-2", "summary": "KAI received B"})
        self.assertEqual(self.req("/state")[1]["interaction"]["receipt_id"], "kai-2")
        simulation = self.req("/admin/interaction", "POST", {"text": "sim", "choices": [{"id": "s", "label": "S"}], "source": "simulation"})[1]["interaction"]
        self.req("/choice", "POST", {"interaction_id": simulation["id"], "choice_id": "s", "request_id": "choice-s"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.req("/admin/choice-receipt", "POST", {"interaction_id": simulation["id"], "choice_id": "s", "receipt_id": "kai-sim", "summary": "must reject"})
        self.assertEqual(ctx.exception.code, 409)

    def test_explicit_demo_choice_updates_simulation_summary_and_off_dismisses(self):
        demo = self.req("/admin/demo", "POST", {"kind": "short"})[1]
        self.assertTrue(self.req("/state")[1]["demo_enabled"])
        self.req("/choice", "POST", {"interaction_id": demo["interaction"]["id"], "choice_id": "send", "request_id": "demo-choice"})
        current = self.req("/state")[1]
        self.assertIn("サンプル：送信するを選びました", current["summary"])
        self.assertEqual(current["summary_source"], "simulation")
        self.req("/admin/demo", "POST", {"kind": "short"})
        self.req("/admin/demo", "POST", {"kind": "off"})
        off = self.req("/state")[1]
        self.assertFalse(off["demo_enabled"])
        self.assertIsNone(off["interaction"])
        self.assertEqual(off["summary"], bridge.NEUTRAL_SUMMARY)

    def test_summary_without_timestamp_is_neutral_but_storage_remains(self):
        self.store.set_meta("summary", "Old summary")
        value = self.req("/state")[1]
        self.assertEqual(value["summary"], bridge.NEUTRAL_SUMMARY)
        self.assertEqual(self.store.meta("summary"), "Old summary")

    def test_all_shared_reads_serialize_through_store_lock(self):
        self.store.db = _LockCheckingConnection(self.store.db, self.store.lock)
        holder_ready = threading.Event()
        release_holder = threading.Event()

        def hold_store_lock():
            with self.store.lock:
                holder_ready.set()
                release_holder.wait()

        holder = threading.Thread(target=hold_store_lock)
        holder.start()
        self.assertTrue(holder_ready.wait(1))

        reader_started = threading.Event()
        reader_result = []

        def read_meta():
            reader_started.set()
            reader_result.append(self.store.meta("missing", "default"))

        reader = threading.Thread(target=read_meta)
        reader.start()
        self.assertTrue(reader_started.wait(1))
        release_holder.set()
        holder.join(1)
        reader.join(1)
        self.assertEqual(reader_result, ["default"])

        self.store.request("missing")
        self.store.recent_requests()
        self.store.recent_events()
        self.store.interaction()
        self.assertEqual(self.req("/admin/choices")[1], {"choices": []})


if __name__ == "__main__":
    unittest.main()
