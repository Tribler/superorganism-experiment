#!/usr/bin/env bash
set -euo pipefail

# ===== Config =====
BITCOIND_BIN="${BITCOIND_BIN:-bitcoind}"
BITCOINCLI_BIN="${BITCOINCLI_BIN:-bitcoin-cli}"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$PROJECT_ROOT/.bitcoin/regtest-demo}"
CONF_FILE="$DATA_DIR/bitcoin.conf"

WALLET_NAME="${WALLET_NAME:-demo}"
TREASURY_WALLET_NAME="${TREASURY_WALLET_NAME:-treasury}"

APP_ENV_FILE="${APP_ENV_FILE:-$PROJECT_ROOT/.bitcoin/.env.regtest}"
TREASURY_ADDRESS_FILE="$DATA_DIR/treasury_address"

RPC_USER="${RPC_USER:-demo}"
RPC_PASSWORD="${RPC_PASSWORD:-superorganism}"
RPC_PORT="${RPC_PORT:-18443}"
P2P_PORT="${P2P_PORT:-18444}"
HOST="${HOST:-127.0.0.1}"

# ===== Helpers =====

btc() {
  "$BITCOINCLI_BIN" \
    -regtest \
    -datadir="$DATA_DIR" \
    -rpcconnect="$HOST" \
    -rpcport="$RPC_PORT" \
    -rpcuser="$RPC_USER" \
    -rpcpassword="$RPC_PASSWORD" \
    "$@"
}

wallet_btc() {
  btc -rpcwallet="$WALLET_NAME" "$@"
}

treasury_btc() {
  btc -rpcwallet="$TREASURY_WALLET_NAME" "$@"
}

ensure_conf() {
  mkdir -p "$DATA_DIR"
  mkdir -p "$(dirname "$APP_ENV_FILE")"

  if [ ! -f "$CONF_FILE" ]; then
    cat > "$CONF_FILE" <<EOF
regtest=1
server=1
txindex=1
fallbackfee=0.0002

[regtest]
rpcbind=$HOST
rpcallowip=127.0.0.1
rpcport=$RPC_PORT
port=$P2P_PORT
rpcuser=$RPC_USER
rpcpassword=$RPC_PASSWORD
daemon=1
EOF

    chmod 600 "$CONF_FILE"
    echo "Created $CONF_FILE"
  fi
}

wait_for_rpc() {
  echo "Waiting for RPC on $HOST:$RPC_PORT..."
  for _ in {1..60}; do
    if btc getblockchaininfo >/dev/null 2>&1; then
      echo "RPC is ready."
      return 0
    fi
    sleep 1
  done

  echo "RPC did not become ready in time." >&2
  exit 1
}

ensure_wallet_loaded() {
  local wallet_name="$1"

  if btc listwallets | grep -q "\"$wallet_name\""; then
    return 0
  fi

  if btc loadwallet "$wallet_name" >/dev/null 2>&1; then
    echo "Loaded existing wallet: $wallet_name"
  else
    btc createwallet "$wallet_name" >/dev/null
    echo "Created wallet: $wallet_name"
  fi
}

ensure_funded_wallet() {
  local balance
  balance="$(wallet_btc getbalance)"

  # If no funds yet, mine 101 blocks so coinbase outputs mature.
  if [ "$balance" = "0.00000000" ] || [ "$balance" = "0" ]; then
    local addr
    addr="$(wallet_btc getnewaddress "mining-rewards" "bech32")"
    btc generatetoaddress 101 "$addr" >/dev/null
    echo "Mined 101 blocks to $addr"
  fi
}

ensure_treasury_address() {
  if [ -f "$TREASURY_ADDRESS_FILE" ]; then
    cat "$TREASURY_ADDRESS_FILE"
    return 0
  fi

  local addr
  addr="$(treasury_btc getnewaddress "treasury" "bech32")"
  echo "$addr" > "$TREASURY_ADDRESS_FILE"
  chmod 600 "$TREASURY_ADDRESS_FILE"
  echo "$addr"
}

write_app_env() {
  local treasury_address="$1"

  cat > "$APP_ENV_FILE" <<EOF
BITCOIN_RPC_URL=http://$HOST:$RPC_PORT
BITCOIN_RPC_USER=$RPC_USER
BITCOIN_RPC_PASSWORD=$RPC_PASSWORD
BITCOIN_RPC_WALLET=$WALLET_NAME
TREASURY_ADDRESS=$treasury_address
EOF

  chmod 600 "$APP_ENV_FILE"
  echo "Wrote app config to $APP_ENV_FILE"
}

print_info() {
  local treasury_address="$1"
  local block_count balance wallet_addr

  block_count="$(btc getblockcount)"
  balance="$(wallet_btc getbalance)"
  wallet_addr="$(wallet_btc getnewaddress "receive" "bech32")"

  cat <<EOF

Regtest node is ready.

Data dir:         $DATA_DIR
Wallet:           $WALLET_NAME
Treasury wallet:  $TREASURY_WALLET_NAME
Treasury address: $treasury_address
RPC URL:          http://$HOST:$RPC_PORT
RPC user:         $RPC_USER
RPC password:     $RPC_PASSWORD
Block height:     $block_count
Wallet balance:   $balance BTC
Fresh address:    $wallet_addr

App config file:  $APP_ENV_FILE

Useful commands:
  btc getblockchaininfo
  btc listwallets
  wallet_btc getbalance
  wallet_btc getnewaddress
  treasury_btc getnewaddress
  wallet_btc sendtoaddress <address> 1
  btc generatetoaddress 1 \$(wallet_btc getnewaddress)

EOF
}

# ===== Commands =====

start_node() {
  ensure_conf

  if btc getblockchaininfo >/dev/null 2>&1; then
    echo "Regtest node already running."
  else
    "$BITCOIND_BIN" -datadir="$DATA_DIR" >/dev/null
    echo "Started bitcoind."
  fi

  wait_for_rpc
  ensure_wallet_loaded "$WALLET_NAME"
  ensure_wallet_loaded "$TREASURY_WALLET_NAME"
  ensure_funded_wallet

  local treasury_address
  treasury_address="$(ensure_treasury_address)"

  write_app_env "$treasury_address"
  print_info "$treasury_address"
}

stop_node() {
  if btc getblockchaininfo >/dev/null 2>&1; then
    btc stop
    echo "Stopping regtest node..."
  else
    echo "Regtest node is not running."
  fi
}

reset_node() {
  if btc getblockchaininfo >/dev/null 2>&1; then
    btc stop || true
    sleep 2
  fi

  rm -rf "$DATA_DIR/regtest" "$DATA_DIR/wallets" "$TREASURY_ADDRESS_FILE"
  rm -f "$APP_ENV_FILE"
  echo "Removed regtest chain, wallets, treasury address, and app env from $DATA_DIR"
  start_node
}

status_node() {
  btc getblockchaininfo
  echo
  btc listwallets
  echo
  echo "Demo wallet balance:"
  wallet_btc getbalance
  echo
  if [ -f "$TREASURY_ADDRESS_FILE" ]; then
    echo "Treasury address:"
    cat "$TREASURY_ADDRESS_FILE"
  fi
}

send_demo_tx() {
  local dest="${1:-}"
  local amount="${2:-1.0}"
  local op_return_hex="${3:-}"

  if [ -z "$dest" ]; then
    echo "Usage: $0 send <address> [amount] [op_return_hex]" >&2
    exit 1
  fi

  local raw_tx
  local funded_json
  local funded_hex
  local signed_json
  local signed_hex
  local complete
  local txid

  if [ -n "$op_return_hex" ]; then
    raw_tx="$(
      wallet_btc createrawtransaction \
        "[]" \
        "[{\"$dest\": $amount}, {\"data\": \"$op_return_hex\"}]"
    )"
  else
    raw_tx="$(
      wallet_btc createrawtransaction \
        "[]" \
        "[{\"$dest\": $amount}]"
    )"
  fi

  funded_json="$(wallet_btc fundrawtransaction "$raw_tx")"
  funded_hex="$(echo "$funded_json" | jq -r '.hex')"

  signed_json="$(wallet_btc signrawtransactionwithwallet "$funded_hex")"
  signed_hex="$(echo "$signed_json" | jq -r '.hex')"
  complete="$(echo "$signed_json" | jq -r '.complete')"

  if [ "$complete" != "true" ]; then
    echo "Failed to fully sign transaction." >&2
    exit 1
  fi

  txid="$(wallet_btc sendrawtransaction "$signed_hex")"

  echo "Sent transaction: $txid"
  if [ -n "$op_return_hex" ]; then
    echo "Included OP_RETURN data: $op_return_hex"
  fi
  echo "Mine one block to confirm it:"
  echo "  $0 mine 1"
}

mine_blocks() {
  local n="${1:-1}"
  local addr
  addr="$(wallet_btc getnewaddress "mining" "bech32")"
  btc generatetoaddress "$n" "$addr" >/dev/null
  echo "Mined $n block(s) to $addr"
}

show_treasury_address() {
  if [ -f "$TREASURY_ADDRESS_FILE" ]; then
    cat "$TREASURY_ADDRESS_FILE"
  else
    echo "Treasury address not found. Start the node first." >&2
    exit 1
  fi
}

case "${1:-start}" in
  start)
    start_node
    ;;
  stop)
    stop_node
    ;;
  reset)
    reset_node
    ;;
  status)
    status_node
    ;;
  mine)
    mine_blocks "${2:-1}"
    ;;
  send)
    send_demo_tx "${2:-}" "${3:-1.0}" "${4:-}"
    ;;
  treasury-address)
    show_treasury_address
    ;;
  *)
    echo "Usage: $0 {start|stop|reset|status|mine [n]|send <address> [amount] [op_return_hex]|treasury-address}" >&2
    exit 1
    ;;
esac