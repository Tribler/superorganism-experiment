"""
SporeStack API client
"""

import json
import time
import urllib.request
from typing import Optional

from config import Config
from utils import setup_logger

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


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


def calculate_monthly_vps_cost(flavor: str, provider: str) -> int:
    """
    Monthly (30-day) VPS cost in cents.

    Tries GET /server/quote?flavor=<>&days=30&provider=<>; falls back to
    Config.VPS_MONTHLY_COST_CENTS on any error (including the 422
    "only DigitalOcean or Vultr, for now" response for sporestack_eu).
    Never returns None — always a positive int — so callers can treat it
    as a known-good sizing input.
    """
    try:
        url = (
            f"https://api.sporestack.com/server/quote"
            f"?flavor={flavor}&days=30&provider={provider}"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                cents = int(data.get("cents", 0))
                if cents > 0:
                    return cents
    except Exception as e:
        logger.debug("calculate_monthly_vps_cost quote failed: %s", e)
    logger.info(
        "calculate_monthly_vps_cost: falling back to Config.VPS_MONTHLY_COST_CENTS=%d",
        Config.VPS_MONTHLY_COST_CENTS,
    )
    return Config.VPS_MONTHLY_COST_CENTS


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


def generate_token() -> Optional[str]:
    """
    GET /token → mint a fresh SporeStack token (text/plain response body).
    Returns the token string stripped of whitespace, or None on HTTP/network error.
    """
    try:
        url = "https://api.sporestack.com/token"
        req = urllib.request.Request(url, headers={"Accept": "text/plain"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            return resp.read().decode().strip()
    except Exception as e:
        logger.error("generate_token failed: %s", e)
        return None


def get_balance(token: str) -> Optional[dict]:
    """
    GET /token/{token}/balance → raw JSON dict ({cents, usd, burn_rate, ...}).
    Returns the dict, or None on HTTP/network error.
    """
    try:
        url = f"https://api.sporestack.com/token/{token}/balance"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error("get_balance failed: %s", e)
        return None


def launch_server(
    token: str,
    ssh_key: str,
    *,
    flavor: Optional[str] = None,
    operating_system: Optional[str] = None,
    provider: Optional[str] = None,
    region: Optional[str] = None,
    days: Optional[int] = None,
    billing_cycle: Optional[str] = None,
    hostname: Optional[str] = None,
    autorenew: bool = True,
    user_data: Optional[str] = None,
) -> Optional[str]:
    """
    POST /token/{token}/servers → launch a VPS on this token.
    Returns the new machine_id, or None on HTTP/network error.
    Unspecified kwargs fall back to Config.VPS_* defaults.
    """
    flavor = flavor or Config.VPS_FLAVOR
    operating_system = operating_system or Config.VPS_OS
    provider = provider or Config.VPS_PROVIDER
    region = region or Config.VPS_REGION
    billing_cycle = billing_cycle or Config.VPS_BILLING_CYCLE
    if days is None:
        days = Config.VPS_DAYS

    payload = {
        "flavor": flavor,
        "ssh_key": ssh_key,
        "operating_system": operating_system,
        "provider": provider,
        "billing_cycle": billing_cycle,
        "region": region,
        "days": days,
    }
    if hostname:
        payload["hostname"] = hostname
    if autorenew:
        payload["autorenew"] = autorenew
    if user_data:
        payload["user_data"] = user_data

    try:
        url = f"https://api.sporestack.com/token/{token}/servers"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                return None
            response = json.loads(resp.read().decode())
            machine_id = response.get("machine_id")
            if machine_id:
                logger.info(
                    "launch_server: machine_id=%s flavor=%s provider=%s region=%s days=%s",
                    machine_id, flavor, provider, region, days,
                )
            return machine_id
    except Exception as e:
        logger.error("launch_server failed: %s", e)
        return None


def _get_server(token: str, machine_id: str) -> Optional[dict]:
    """GET /token/{token}/servers/{machine_id} → server dict, or None on error."""
    try:
        url = f"https://api.sporestack.com/token/{token}/servers/{machine_id}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error("_get_server failed: %s", e)
        return None


def wait_for_server_ready(
    token: str,
    machine_id: str,
    timeout: int = 300,
    poll_interval: int = 10,
) -> Optional[dict]:
    """
    Poll the server until it has a reachable IPv4/IPv6, or timeout elapses.
    Returns the server dict when ready, or None on timeout.
    Uses time.sleep — call from asyncio.to_thread if invoked from async code.
    """
    start = time.time()
    while time.time() - start < timeout:
        server = _get_server(token, machine_id)
        if server:
            ipv4 = server.get("ipv4")
            ipv6 = server.get("ipv6")
            has_ipv4 = ipv4 and ipv4 != "0.0.0.0"
            has_ipv6 = ipv6 and ipv6 not in ("", "::")
            if has_ipv4 or has_ipv6:
                logger.info("Server %s ready: %s", machine_id, ipv4 or ipv6)
                return server
        logger.debug("Server %s not ready, sleeping %ds", machine_id, poll_interval)
        time.sleep(poll_interval)
    logger.error("Server %s not ready after %ds", machine_id, timeout)
    return None
