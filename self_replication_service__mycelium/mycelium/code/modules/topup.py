"""
Ensures the SporeStack account balance covers TOPUP_TARGET_DAYS of burn.
Called by the decision loop when runway drops below TOPUP_TRIGGER_DAYS.
"""

import asyncio
import logging
import math

from config import Config
from modules import sporestack_client
from modules.node_monitor import NodeState
from modules.wallet import get_wallet

logger = logging.getLogger(__name__)

_SS_MIN_INVOICE_DOLLARS = 5


def _parse_bitcoin_uri(uri: str):
    """Parse bitcoin:ADDRESS?amount=BTC → (address, amount_sat) or None."""
    if not uri.startswith("bitcoin:"):
        return None
    parts = uri[8:].split("?")
    address = parts[0]
    amount_btc = None
    if len(parts) > 1:
        for param in parts[1].split("&"):
            if param.startswith("amount="):
                amount_btc = float(param[7:])
                break
    if not address or amount_btc is None:
        return None
    return address, int(amount_btc * 100_000_000)


async def topup_sporestack(node_state: NodeState) -> None:
    """Buy exactly TOPUP_TARGET_DAYS (30) of SporeStack run time from the BTC wallet."""

    # Read SporeStack token
    try:
        token = Config.SPORESTACK_TOKEN_FILE.read_text().strip()
    except OSError as e:
        logger.error("[TOPUP] Cannot read SporeStack token: %s", e)
        return

    # Calculate monthly VPS cost (stub — returns None until /server/quote supports our provider)
    monthly_cost_cents = sporestack_client.calculate_monthly_vps_cost(
        token, node_state.vps_provider, node_state.vps_region
    )
    if monthly_cost_cents is None:
        logger.warning(
            "[TOPUP] Monthly VPS cost unavailable (SporeStack /server/quote not yet supported "
            "for provider=%r) — cannot calculate topup amount; skipping",
            node_state.vps_provider,
        )
        return

    # Scale to TOPUP_TARGET_DAYS (≈30 days = one month)
    cost_cents = int(monthly_cost_cents * Config.TOPUP_TARGET_DAYS / 30)
    current_cents = node_state.sporestack_balance_cents or 0
    needed_cents = cost_cents - current_cents

    if needed_cents <= 0:
        logger.info(
            "[TOPUP] SS balance $%.2f already covers %d days — no topup needed",
            current_cents / 100, Config.TOPUP_TARGET_DAYS,
        )
        return

    needed_dollars = max(_SS_MIN_INVOICE_DOLLARS, math.ceil(needed_cents / 100))
    logger.info(
        "[TOPUP] Need $%.2f for %d days; current SS balance $%.2f → buying $%d",
        needed_cents / 100, Config.TOPUP_TARGET_DAYS, current_cents / 100, needed_dollars,
    )

    # Create invoice
    response = await asyncio.to_thread(sporestack_client.create_invoice, token, needed_dollars)
    if not response:
        logger.error("[TOPUP] Failed to create SporeStack invoice")
        return

    invoice = response.get("invoice", response)
    payment_uri = invoice.get("payment_uri", "")
    parsed = _parse_bitcoin_uri(payment_uri)
    if not parsed:
        logger.error("[TOPUP] Cannot parse payment URI: %r", response)
        return

    address, amount_sat = parsed
    logger.info("[TOPUP] Invoice: send %d sat to %s (for $%d)", amount_sat, address, needed_dollars)

    # Check BTC balance
    wallet = get_wallet()
    if wallet is None:
        logger.error("[TOPUP] Wallet not initialized")
        return
    wallet_sat = await asyncio.to_thread(wallet.get_balance_satoshis)
    if wallet_sat < amount_sat:
        logger.error(
            "[TOPUP] Insufficient BTC: have %d sat, need %d sat", wallet_sat, amount_sat
        )
        return

    # Send payment
    try:
        txid = await asyncio.to_thread(wallet.send, address, amount_sat)
        logger.info("[TOPUP] Sent %d sat to %s — txid %s", amount_sat, address, txid)
    except Exception as e:
        logger.error("[TOPUP] Payment failed: %s", e)
