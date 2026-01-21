# Mycelium VPS Deployer

Autonomous VPS provisioning system using Bitcoin payments and SporeStack API. Deploys [mycelium](https://github.com/DogariuMatei/mycelium), a BitTorrent orchestrator for Creative Commons content.

## Quick Start
### 0. Install dependencies
```bash
pip install -r requirements.txt
```
### 1. Create and fund Bitcoin wallet
```bash
python wallet.py create mycelium
python wallet.py address mycelium      # Send BTC to this address
python wallet.py scan mycelium         # Verify funds received
```
### 2. Fund SporeStack account
```bash
python fund_sporestack.py fund 100
```

### 3. Acquire VPS
```bash
python acquire_vps.py
```

### 4. Deploy mycelium to VPS
```bash
python deploy_mycelium.py
```
### 5. (Optional) Stop mycelium
```bash
python stop_mycelium.py
```

## CLI Reference

### wallet.py

Bitcoin HD wallet management.

```
python wallet.py <command> <wallet_name>

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
python fund_sporestack.py <command> [amount]

Commands:
  fund [amount]     Fund account (default: $10)
  balance           Check SporeStack balance
  token             Display saved token
  help              Show usage
```

### acquire_vps.py

Provision a VPS from SporeStack.

```
python acquire_vps.py [options]

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

### deploy_mycelium.py

Deploy mycelium to a VPS.

```
python deploy_mycelium.py [options]

Options:
  --host IP           Server IP (default: from ~/.mycelium/server.json)
  --port PORT         SSH port (default: 22)
  --ssh-key PATH      SSH key path (default: ~/.mycelium/ssh/deploy_key)
  --content-dir DIR   Content directory to upload
  --no-content        Skip content upload
  --wallet NAME       Wallet name for xpub (default: mycelium)
  --no-xpub           Deploy without Bitcoin wallet
```

### stop_mycelium.py

Stop mycelium orchestrator on the VPS to save resources.

```
python stop_mycelium.py
```

Connects to the VPS and kills the running mycelium process. Run `deploy_mycelium.py` to restart.

## Content Sourcing

Search for Creative Commons videos and download them:

```bash
# Requires YOUTUBE_API_KEY in .env
python yt-api-cc-scripts/yt-api-cc.py
python yt-api-cc-scripts/yt-api-cc-playlists.py

# Download collected URLs
./scripts/parallel_ytdlp_download.sh
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
