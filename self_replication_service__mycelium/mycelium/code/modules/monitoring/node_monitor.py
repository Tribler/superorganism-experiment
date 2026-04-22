"""
Aggregates BTC balance and SporeStack runway details into a NodeState.
Decision loop and SeedboxInfoPayload broadcast consume info.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import sporestack_client
from ..core.wallet import get_wallet

logger = logging.getLogger(__name__)


@dataclass
class NodeState:
    btc_balance_sat: int = 0
    sporestack_balance_cents: int = 0
    burn_rate_cents_per_day: int = 0
    cost_per_day_usd: float = 0.0
    days_remaining: Optional[int] = None
    server_expiry_ts: int = 0        # Unix ts of running server lease end
    last_updated: float = 0.0
    vps_provider: str = ""
    vps_region: str = ""


class NodeMonitor:
    REFRESH_INTERVAL = 300  # 5 minutes

    def __init__(self, token_file: Path):
        self._token_file = token_file
        self._state = NodeState()

    def _load_token(self) -> Optional[str]:
        try:
            if self._token_file.exists():
                token = self._token_file.read_text().strip()
                return token or None
        except Exception:
            pass
        return None

    def refresh(self) -> None:
        """Refresh node state from blockchain and SporeStack API. Swallows all exceptions."""
        try:
            # BTC balance
            w = get_wallet()
            if w:
                try:
                    w.scan()
                except Exception as e:
                    logger.warning("Wallet scan failed: %s", e)
                btc_balance_sat = w.get_balance_satoshis()
            else:
                btc_balance_sat = 0

            # SporeStack balance
            sporestack_balance_cents = 0
            burn_rate_cents_per_day = 0
            cost_per_day_usd = 0.0
            days_remaining = None

            vps_provider = ""
            vps_region = ""

            server_expiry_ts = 0
            server = None

            token = self._load_token()
            if token:
                data = sporestack_client.get_info(token)
                if data:
                    sporestack_balance_cents = int(data.get("balance_cents", 0))
                    burn_rate_cents_per_day = int(data.get("burn_rate_cents", 0))
                    cost_per_day_usd = round(burn_rate_cents_per_day / 100, 4)
                    # Do NOT use data.get("days_remaining") — SporeStack computes that as
                    # balance/burn_rate which is always 0 for per-cycle-billed servers.
                    # burn_rate_cents_per_day is always 0 for monthy-billed servers.
                    # ONLY way to infer/get that information is to wait for /server/quote to support
                    # the VPS provider used here and then to divide the quote's cost by 30.

                servers = sporestack_client.get_servers(token)
                if servers:
                    server = servers[-1]
                if server:
                    vps_provider = server.get("provider", "")
                    vps_region = server.get("region", "")
                    server_expiry_ts = int(server.get("expiration", 0))

                    # TODO: once SporeStack's /server/quote endpoint supports the VPS provider
                    # used here, use it to get the cost per 30-day cycle and compute additional
                    # runway from (sporestack_balance_cents + btc_as_cents) / cost_per_cycle * 30.
                    if server_expiry_ts:
                        days_remaining = max(0, int((server_expiry_ts - time.time()) / 86400))

            self._state = NodeState(
                btc_balance_sat=btc_balance_sat,
                sporestack_balance_cents=sporestack_balance_cents,
                burn_rate_cents_per_day=burn_rate_cents_per_day,
                cost_per_day_usd=cost_per_day_usd,
                days_remaining=days_remaining,
                server_expiry_ts=server_expiry_ts,
                last_updated=time.time(),
                vps_provider=vps_provider,
                vps_region=vps_region,
            )
            logger.info(
                "Monitor refresh: btc=%d sat, runway=%d days, burn=%d cents/day",
                btc_balance_sat, days_remaining, burn_rate_cents_per_day,
            )
        except Exception as e:
            logger.error("NodeMonitor.refresh failed: %s", e)

    def get_state(self) -> NodeState:
        return self._state


# Module-level singleton
_monitor: Optional[NodeMonitor] = None


def init(token_file: Path) -> None:
    global _monitor
    _monitor = NodeMonitor(token_file)


def get_monitor() -> Optional[NodeMonitor]:
    return _monitor
