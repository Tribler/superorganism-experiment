#!/usr/bin/env python3
"""SporeStack account funding script."""

import logging
import os
import sys
import time
from pathlib import Path

from lib.provisioner import SporeStackClient, SporeStackError
from lib.wallet import BitcoinWallet, InsufficientFundsError, WalletError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN_FILE = Path.home() / ".mycelium" / "sporestack_token"


def parse_bitcoin_uri(payment_uri: str) -> tuple[str, float] | None:
    """Parse a bitcoin: URI and return (address, amount_btc) or None if invalid."""
    if not payment_uri.startswith("bitcoin:"):
        return None

    parts = payment_uri[8:].split("?")
    address = parts[0]
    amount_btc = None

    if len(parts) > 1:
        for param in parts[1].split("&"):
            if param.startswith("amount="):
                amount_btc = float(param[7:])
                break

    if not address or not amount_btc:
        return None

    return address, amount_btc


def prompt_for_token() -> str:
    print("\n" + "=" * 60)
    print("You need a SporeStack token.")
    print("=" * 60)
    print("\n1. Go to: https://sporestack.com")
    print("2. Click the 'Generate' button in the Payment Token section")
    print("3. Save the token securely (you cannot recover it!)")
    print("4. Paste it below\n")

    token = input("Enter your SporeStack token: ").strip()
    if not token:
        raise ValueError("Token cannot be empty")
    return token


def save_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    logger.info(f"Token saved to {TOKEN_FILE}")


def load_token() -> str | None:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


def get_or_create_token() -> str:
    token = load_token()

    if token:
        print(f"\nFound existing token: {token[:20]}...{token[-10:]}")
        response = input("Use this token? [Y/n]: ").strip().lower()
        if response not in ("n", "no"):
            return token

    token = prompt_for_token()

    save_response = input("\nSave token to file? [Y/n]: ").strip().lower()
    if save_response not in ("n", "no"):
        save_token(token)

    return token


def check_wallet_balance(wallet: BitcoinWallet) -> int:
    print("\nScanning blockchain for wallet updates...")
    wallet.scan()

    balance_sat = wallet.get_balance_satoshis()
    balance_btc = wallet.get_balance_btc()

    print(f"Wallet balance: {balance_sat:,} satoshis ({balance_btc:.8f} BTC)")
    return balance_sat


def check_sporestack_balance(client: SporeStackClient) -> dict:
    print("\nChecking SporeStack account balance...")
    balance = client.get_balance()

    cents = balance.get("cents", 0)
    dollars = cents / 100

    print(f"SporeStack balance: ${dollars:.2f} ({cents} cents)")
    return balance


def create_and_pay_invoice(
    wallet: BitcoinWallet,
    client: SporeStackClient,
    dollars: int
) -> str | None:
    """Create a SporeStack invoice and pay it from the wallet. Returns txid or None."""
    print(f"\nCreating invoice for ${dollars}...")

    try:
        response = client.create_invoice(dollars=dollars, currency="btc")
    except SporeStackError as e:
        logger.error(f"Failed to create invoice: {e}")
        return None

    invoice = response.get("invoice", response)
    payment_uri = invoice.get("payment_uri", "")

    parsed = parse_bitcoin_uri(payment_uri)
    if not parsed:
        logger.error(f"Could not parse invoice: {response}")
        return None

    address, amount_btc = parsed
    amount_sat = int(amount_btc * 100_000_000)

    print(f"\nInvoice created:")
    print(f"  Address: {address}")
    print(f"  Amount:  {amount_sat:,} satoshis ({amount_btc:.8f} BTC)")
    print(f"  Value:   ${dollars}")

    wallet_balance = wallet.get_balance_satoshis()
    if wallet_balance < amount_sat:
        print(f"\nInsufficient funds!")
        print(f"  Wallet balance: {wallet_balance:,} satoshis")
        print(f"  Required:       {amount_sat:,} satoshis")
        print(f"  Shortfall:      {amount_sat - wallet_balance:,} satoshis")
        return None

    print(f"\nReady to send {amount_sat:,} satoshis to {address}")
    confirm = input("Confirm payment? [y/N]: ").strip().lower()

    if confirm not in ("y", "yes"):
        print("Payment cancelled.")
        return None

    print("\nSending payment...")
    try:
        txid = wallet.send(address, amount_sat)
        print(f"\nPayment sent successfully!")
        print(f"Transaction ID: {txid}")
        return txid
    except InsufficientFundsError as e:
        logger.error(f"Insufficient funds: {e}")
        return None
    except WalletError as e:
        logger.error(f"Payment failed: {e}")
        return None


def wait_for_confirmation(client: SporeStackClient, initial_balance: int, timeout: int = 1800) -> bool:
    print(f"\nWaiting for payment confirmation (up to {timeout // 60} minutes)...")
    print("SporeStack typically credits after 1-3 Bitcoin confirmations.")

    start_time = time.time()
    check_interval = 30

    while time.time() - start_time < timeout:
        try:
            balance = client.get_balance()
            current_cents = balance.get("cents", 0)

            if current_cents > initial_balance:
                added = current_cents - initial_balance
                print(f"\nPayment confirmed! Added ${added / 100:.2f} to account.")
                print(f"New balance: ${current_cents / 100:.2f}")
                return True

            elapsed = int(time.time() - start_time)
            print(f"  Waiting... ({elapsed}s elapsed, balance: ${current_cents / 100:.2f})")

        except SporeStackError as e:
            logger.warning(f"Error checking balance: {e}")

        time.sleep(check_interval)

    print("\nTimeout waiting for confirmation.")
    print("The payment may still be processing. Check balance later with:")
    print("  python fund_sporestack.py balance")
    return False


def main():
    print("=" * 60)
    print("SporeStack Account Funding Script")
    print("=" * 60)

    command = sys.argv[1] if len(sys.argv) > 1 else "fund"

    if command == "help":
        print("\nUsage: python fund_sporestack.py [command]")
        print("\nCommands:")
        print("  fund [amount]  - Fund SporeStack account (default: $10)")
        print("  balance        - Check SporeStack balance only")
        print("  token          - Show or generate token")
        print("  help           - Show this help")
        return

    token = get_or_create_token()
    client = SporeStackClient(token)

    if command == "token":
        print(f"\nYour SporeStack token:")
        print(token)
        return

    if command == "balance":
        check_sporestack_balance(client)
        return

    if command == "fund":
        try:
            dollars = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        except ValueError:
            dollars = 10

        if dollars < 1:
            print("Minimum funding amount is $1")
            return

        wallet_name = os.getenv("MYCELIUM_WALLET_NAME", "mycelium")
        print(f"\nLoading wallet: {wallet_name}")

        wallet = BitcoinWallet(wallet_name)

        if not wallet.exists():
            print(f"\nWallet '{wallet_name}' does not exist.")
            print("Create one first with: python wallet.py create mycelium")
            return

        wallet.load()

        check_wallet_balance(wallet)
        initial_ss_balance = check_sporestack_balance(client).get("cents", 0)

        print(f"\n{'=' * 60}")
        print(f"Funding SporeStack with ${dollars}")
        print("=" * 60)

        txid = create_and_pay_invoice(wallet, client, dollars)

        if txid:
            print("\n" + "=" * 60)
            wait_response = input("Wait for SporeStack to confirm payment? [Y/n]: ").strip().lower()

            if wait_response not in ("n", "no"):
                wait_for_confirmation(client, initial_ss_balance)
            else:
                print("\nYou can check your balance later with:")
                print("  python fund_sporestack.py balance")

        # Final balance check
        print("\n" + "=" * 60)
        print("Final balances:")
        check_wallet_balance(wallet)
        check_sporestack_balance(client)

    else:
        print(f"Unknown command: {command}")
        print("Run 'python fund_sporestack.py help' for usage")


if __name__ == "__main__":
    main()
