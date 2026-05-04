#!/usr/bin/env python3
"""HTTP collector for mycelium offline-sim events (TODO 8.7).

Accepts POST /event payloads from each container's EventLogger and appends
them as JSONL to sim/data/events.jsonl for the analysis layer (8.11).
"""
import json
import time
import threading
import pathlib

from flask import Flask, request, jsonify

BIND_HOST = "127.0.0.1"
BIND_PORT = 8765
EVENTS_FILE = pathlib.Path(__file__).resolve().parent / "data" / "events.jsonl"
# Matches what the bootstrapper writes to ~/.mycelium/log_secret and injects as
# MYCELIUM_LOG_SECRET on every node. It's just a logging endpoint, not real auth.
API_KEY = "123456789"
_REQUIRED_KEYS = ("timestamp", "node", "event", "data")
_lock = threading.Lock()


def _append(record: dict) -> None:
    with _lock:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_FILE.open("a") as f:
            f.write(json.dumps(record) + "\n")


app = Flask(__name__)


@app.post("/event")
def event():
    if request.headers.get("X-Api-Key") != API_KEY:
        return ("unauthorized", 401)
    payload = request.get_json(silent=True)
    if payload is None or any(k not in payload for k in _REQUIRED_KEYS) \
            or not isinstance(payload["data"], dict):
        return ("bad request", 400)
    record = {"ts": time.time(), "src_ip": request.remote_addr, **payload}
    _append(record)
    return ("", 204)


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, events_file=str(EVENTS_FILE))


if __name__ == "__main__":
    app.run(host=BIND_HOST, port=BIND_PORT, threaded=True)
