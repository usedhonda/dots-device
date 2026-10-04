from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class BridgeError(RuntimeError):
    pass


class BridgeClient:
    """Small authenticated adapter; it never exposes the bearer token."""

    def __init__(self, root: str | Path | None = None, base_url: str = "http://127.0.0.1:8766"):
        self.root = Path(root or Path(__file__).resolve().parents[1])
        self.base_url = base_url.rstrip("/")
        self.token_path = self.root / ".local" / "bridge-token"

    def _token(self) -> str:
        try:
            token = self.token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise BridgeError("bridge token unavailable") from exc
        if not token:
            raise BridgeError("bridge token unavailable")
        return token

    def _request(self, method: str, path: str, value: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode()
        req = urllib.request.Request(self.base_url + path, data=body, method=method,
                                     headers={"Authorization": "Bearer " + self._token(),
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read(64 * 1024))
        except (OSError, urllib.error.HTTPError, ValueError) as exc:
            raise BridgeError("bridge request failed") from exc
        if not isinstance(result, dict):
            raise BridgeError("bridge returned invalid response")
        if "error" in result:
            raise BridgeError("bridge rejected request")
        return result

    def publish_question(self, text: str, choices: list[dict[str, str]], question_id: str) -> dict[str, Any]:
        if not isinstance(question_id, str) or not question_id:
            raise BridgeError("question_id is required for idempotency")
        try:
            return self._request("POST", "/admin/interaction", {"id": question_id, "request_id": question_id,
                "text": text, "choices": choices, "source": "real"})
        except BridgeError:
            # The bridge rejects duplicate IDs; read back the existing question so
            # retries remain idempotent and never reopen a selected interaction.
            state = self._request("GET", "/admin/state")
            interaction = state.get("interaction")
            if (isinstance(interaction, dict) and interaction.get("id") == question_id
                    and interaction.get("text") == text and interaction.get("choices") == choices
                    and interaction.get("source") == "real"):
                return {"status": interaction.get("status", "pending"), "interaction": interaction, "idempotent": True}
            raise

    def read_answers(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/admin/choices")
        answers = result.get("choices")
        return [item for item in answers if isinstance(item, dict) and item.get("source") == "real"] if isinstance(answers, list) else []

    def record_receipt(self, interaction_id: str, choice_id: str, receipt_id: str, summary: str) -> dict[str, Any]:
        return self._request("POST", "/admin/choice-receipt", {"interaction_id": interaction_id,
            "choice_id": choice_id, "receipt_id": receipt_id, "summary": summary})

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/admin/device")
