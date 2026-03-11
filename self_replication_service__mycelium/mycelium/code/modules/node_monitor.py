"""
Aggregates BTC balance and SporeStack runway details into a NodeState.
Decision loop and SeedboxInfoPayload broadcast consume info.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from modules import sporestack_client
from modules.wallet import get_wallet

logger = logging.getLogger(__name__)


@dataclass
class NodeState:
    btc_balance_sat: int = 0
    sporestack_balance_cents: int = 0
    burn_rate_cents_per_day: int = 0
    cost_per_day_usd: float = 0.0
    days_remaining: int = 0
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
            days_remaining = 0

            vps_provider = ""
            vps_region = ""

            token = self._load_token()
            if token:
                data = sporestack_client.get_info(token)
                if data:
                    sporestack_balance_cents = int(data.get("balance_cents", 0))
                    burn_rate_cents_per_day = int(data.get("burn_rate_cents", 0))
                    cost_per_day_usd = round(burn_rate_cents_per_day / 100, 4)
                    days_remaining = int(data.get("days_remaining", 0))

                servers = sporestack_client.get_servers(token)
                if servers:
                    server = next((s for s in servers if s.get("running")), servers[0])
                    vps_provider = server.get("provider", "")
                    vps_region = server.get("region", "")

            self._state = NodeState(
                btc_balance_sat=btc_balance_sat,
                sporestack_balance_cents=sporestack_balance_cents,
                burn_rate_cents_per_day=burn_rate_cents_per_day,
                cost_per_day_usd=cost_per_day_usd,
                days_remaining=days_remaining,
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
