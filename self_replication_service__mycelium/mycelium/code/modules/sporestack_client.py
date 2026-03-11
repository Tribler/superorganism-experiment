"""
SporeStack API client
"""

import json
import urllib.request
from typing import Optional


def get_info(token: str) -> Optional[dict]:
    """
    Get token info from SporeStack API.
    """
    try:
        url = f"https://api.sporestack.com/token/{token}/info"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode())
    except Exception:
        return None


def get_servers(token: str) -> Optional[list]:
    """
    Get all servers from SporeStack API for this token
    """
    try:
        url = f"https://api.sporestack.com/token/{token}/servers"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode())
            return data.get("servers")
    except Exception:
        return None
