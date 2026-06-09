# Seedbox Production VPS Deployer

Autonomous VPS provisioning system using Bitcoin payments and SporeStack API. Deploys Mycelium a BitTorrent seedbox orchestrator for Creative Commons content.

> Looking to test this offline? See [`../seedbox-local-simulation/`](../seedbox-local-simulation/README.md).

## Quick Start
### 0. Install dependencies
```bash
pip install -r requirements.txt
```
### 1. Create and fund Bitcoin wallet
```bash
python bootstrap-scripts/wallet.py create mycelium
python bootstrap-scripts/wallet.py address mycelium      # Send BTC to this address
python bootstrap-scripts/wallet.py scan mycelium         # Verify funds received
```
### 2. Fund SporeStack account
```bash
python bootstrap-scripts/fund_sporestack.py fund 100     # 100$ 
```

### 3. Acquire VPS
```bash
python bootstrap-scripts/acquire_vps.py
```

### 4. Deploy mycelium to VPS
```bash
python bootstrap-scripts/deploy_seedbox.py
```

## CLI Reference for Production Deployment Scripts

The scripts live in `bootstrap-scripts/`; run them from the `seedbox-bootstrap/` directory.

### wallet.py

Bitcoin HD wallet management.

```
python bootstrap-scripts/wallet.py <command> <wallet_name>

Commands:
  create <name>     Create new wallet (outputs mnemonic - save it!)
  address <name>    Get receiving address
  balance <name>    Check wallet balance
  scan <name>       Scan blockchain for updates
  xpub <name>       Get extended public key
  load <name>       Load and display wallet info
  interactive       Interactive wallet setup
```

### fund_sporestack.py

SporeStack account funding via Bitcoin.

```
python bootstrap-scripts/fund_sporestack.py <command> [amount]

Commands:
  fund [amount]     Fund account (default: $10)
  balance           Check SporeStack balance
  token             Display saved token
  help              Show usage
```

### acquire_vps.py

Provision a VPS from SporeStack.

```
python bootstrap-scripts/acquire_vps.py [options]

Options:
  --token TOKEN       SporeStack token (default: ~/.mycelium/sporestack_token)
  --flavor FLAVOR     Server size (default: vultr.vc2-2c-4gb)
  --os OS             Operating system (default: ubuntu-24-04)
  --provider PROV     VPS provider (default: vultr.ams)
  --days DAYS         Server lifetime (default: 30)
  --hostname NAME     Server hostname (default: mycelium)
  --list-flavors      List available server sizes
  --list-os           List available operating systems
```

### deploy_seedbox.py

Deploy mycelium to a VPS.

```
python bootstrap-scripts/deploy_seedbox.py [options]

Options:
  --host IP           Server IP (default: from ~/.mycelium/server.json)
  --port PORT         SSH port (default: 22)
  --ssh-key PATH      SSH key path (default: ~/.mycelium/ssh/deploy_key)
  --content-dir DIR   Content directory to upload
  --no-content        Skip content upload
  --wallet NAME       Wallet name for xpub (default: mycelium)
  --no-xpub           Deploy without Bitcoin wallet
```

## Data Storage
All persistent data is stored in `~/.mycelium/`:

```
~/.mycelium/
├── wallets/           # Bitcoin wallet databases
├── sporestack_token   # SporeStack API token
├── ssh/deploy_key     # SSH keypair for VPS access
└── server.json        # Acquired VPS info
```
