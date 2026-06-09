"""Central config loader — reads config.json from the project root."""

import json
from pathlib import Path

_CONFIG_FILE = Path(__file__).parent.parent / "config.json"


def _load() -> dict:
    with open(_CONFIG_FILE) as f:
        raw = json.load(f)
    result = {}
    for k, v in raw.items():
        if isinstance(v, str) and v.startswith("~"):
            result[k] = Path(v).expanduser()
        else:
            result[k] = v
    return result


CFG = _load()
