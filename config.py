from typing import Final

from authentication.bitcoin.rpc_client import BitcoinRpcConfig

DATA_PATH: Final[str] = "democracy/data/"
KEYS_PATH: Final[str] = "democracy/keys/"
COMMUNICATION_INTERVAL: Final[float] = 60.0 # Seconds
UI_REFRESH_DELAY: Final[int] = 100 # Milliseconds

REGTEST_RPC_CONFIG = BitcoinRpcConfig(
    rpc_url="http://127.0.0.1:18443",
    rpc_user="demo",
    rpc_password="superorganism",
    wallet_name="demo",
    timeout_seconds=10.0,
)

NETWORK_ID: Final[bytes] = b"regtest"
