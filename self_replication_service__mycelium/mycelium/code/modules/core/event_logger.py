"""
Fire-and-forget HTTP event logger.
"""
import json
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Optional


class EventLogger:
    def __init__(self, endpoint: str, secret: str, node_name: str):
        self._endpoint = endpoint.rstrip("/") + "/event" if endpoint else ""
        self._secret = secret
        self._node_name = node_name

    def log_event(self, event_type: str, data: dict) -> None:
        if not self._endpoint:
            return
        threading.Thread(target=self._post, args=(event_type, data), daemon=True).start()

    def _post(self, event_type: str, data: dict) -> None:
        try:
            payload = json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node": self._node_name,
                "event": event_type,
                "data": data,
            }).encode()
            req = urllib.request.Request(
                self._endpoint,
                data=payload,
                headers={"Content-Type": "application/json", "X-Api-Key": self._secret},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # silent fail — never crash the node


_instance: Optional[EventLogger] = None


def init(endpoint: str, secret: str, node_name: str) -> EventLogger:
    global _instance
    _instance = EventLogger(endpoint, secret, node_name)
    return _instance


def get() -> EventLogger:
    global _instance
    if _instance is None:
        _instance = EventLogger("", "", "unknown")
    return _instance
