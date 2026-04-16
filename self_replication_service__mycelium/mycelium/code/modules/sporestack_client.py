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


def create_invoice(token: str, dollars: int) -> Optional[dict]:
    """
    POST /token/{token}/add → BTC funding invoice.
    Returns response dict with invoice.payment_uri, or None on error.
    SporeStack minimum $5; caller enforces.
    """
    try:
        url = f"https://api.sporestack.com/token/{token}/add"
        payload = json.dumps({"dollars": dollars, "currency": "btc"}).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode())
    except Exception:
        return None


def calculate_monthly_vps_cost(token: str, provider: str, region: str) -> Optional[int]:
    """
    Return the monthly VPS cost in cents, or None if not available.

    TODO: Use GET /server/quote?flavor=<flavor>&days=30&provider=<provider> once
    the endpoint supports the provider in use. Until then this returns None.

    burn_rate_cents_per_day is always 0 for monthly-billed servers, so /token/info
    cannot be used — this is the only alternative.
    """
    return None


def get_servers(token: str) -> Optional[list]:
    """
    Get active (non-forgotten, non-deleted) servers from SporeStack API for this token.
    """
    try:
        url = f"https://api.sporestack.com/token/{token}/servers?include_forgotten=false&include_deleted=false"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode())
            return data.get("servers")
    except Exception:
        return None
