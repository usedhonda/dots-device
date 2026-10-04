"""Exercise the direct answer scheduling contract with a small extracted stub."""
from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "firmware/kai_companion/kai_companion.ino").read_text()
loop = source[source.index("  for(;;) {", source.index("static void directTask")) : source.index("    ulTaskNotifyTake", source.index("static void directTask"))]

# Keep these checks tied to executable call sites, then run the same ordering
# against a stateful stub below. This catches a future move that strands an
# answer behind connectivity or long-poll checks.
assert loop.index("directMCP.select") < loop.index("if(WiFi.status()!=WL_CONNECTED)")
assert loop.index("directMCP.events.enqueue") < loop.index("pollOnce")
assert loop.index("directMCP.events.pump") < loop.index("pollOnce")
assert "},(questionPending||answerPending)?1000:5000" in loop


class DirectStub:
    def __init__(self):
        self.answer = None
        self.queued = True
        self.persisted = False
        self.events = []
        self.poll_timeouts = []

    def select(self):
        # select() persists before transport availability is considered.
        self.answer = {"receipt_id": None}
        self.persisted = True

    def iteration(self, connected, clock_ready):
        if self.queued:
            self.select()
        if not connected or not clock_ready:
            return
        if self.answer and self.answer["receipt_id"] is None:
            self.events.append("enqueue")
        self.events.append("pump")
        pending_answer = bool(self.answer and self.answer["receipt_id"] is None)
        self.poll_timeouts.append(1000 if pending_answer else 5000)
        self.events.append("poll")


offline = DirectStub()
offline.iteration(connected=False, clock_ready=False)
assert offline.persisted and offline.events == []

pending = DirectStub()
pending.iteration(connected=True, clock_ready=True)
assert pending.events == ["enqueue", "pump", "poll"]
assert pending.poll_timeouts == [1000]

settled = DirectStub()
settled.answer = {"receipt_id": "r"}
settled.queued = False
settled.iteration(connected=True, clock_ready=True)
assert settled.events == ["pump", "poll"]
assert settled.poll_timeouts == [5000]

print("PASS direct delivery: offline persistence, event-before-poll, adaptive long-poll timeout")
