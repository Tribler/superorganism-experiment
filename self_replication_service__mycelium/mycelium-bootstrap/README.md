# Mycelium Production VPS Deployer

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
python fund_sporestack.py fund 100     # 100$ 
```

### 3. Acquire VPS
```bash
python acquire_vps.py
```

### 4. Deploy mycelium to VPS
```bash
python deploy_mycelium.py
```

# Mycelium Local Simulation:

### Install Dependencies:

#### 1. Python 3.11+
```bash
python3 --version   # must be 3.11 or newer
```

#### 2. LXD 
```bash

sudo snap install lxd
sudo lxd init --auto
sudo usermod -aG lxd $USER
# Log out and back in (or: newgrp lxd) for group to take effect
```

#### 3. Bitcoin Core (`bitcoind` + `bitcoin-cli`)
Download directly from bitcoincore.org (the PPA is unmaintained):
```bash
VERSION="31.0"   # check https://bitcoincore.org/en/download/ for latest
wget https://bitcoincore.org/bin/bitcoin-core-${VERSION}/bitcoin-${VERSION}-x86_64-linux-gnu.tar.gz
tar -xzf bitcoin-${VERSION}-x86_64-linux-gnu.tar.gz
sudo install -m 0755 -t /usr/local/bin bitcoin-${VERSION}/bin/bitcoind bitcoin-${VERSION}/bin/bitcoin-cli
```

#### 4. Electrs (Electrum server)
Requires Rust and a C linker. Build from source:
```bash
sudo apt install build-essential clang libclang-dev
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
git clone https://github.com/romanz/electrs /tmp/electrs
cd /tmp/electrs && cargo build --release
sudo install -m 0755 /tmp/electrs/target/release/electrs /usr/local/bin/electrs
```

#### 5. Python packages
From the `mycelium-bootstrap/` directory:
```bash
pip install -r requirements.txt
```

### Run Simulation

  From `cd self_replication_service__mycelium/mycelium-bootstrap/sim`:
```bash
  ./run_simulation.py --rebuild-images
````
```bash
./stop_simulation.sh && python3 run_simulation.py 
```

Default configurable parameters can be found in `/sim/config.toml`

To check the logs of any running container, in a secondary terminal:
```bash
  lxc list                                                    # pick whichever m-<12hex> id, then
  lxc exec   m-<hex_here> -- cat /root/logs/orchestrator.log  # orchestrator logs
```
Stop + delete all containers:
```bash
  ./stop_simulation.sh
````

Saves events.jsonl to sim/data/runs/<timestamp>/, kills the host services, deletes the containers. Images and the genesis wallet stay.

## CLI Reference for Production Deployment Scripts

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

## Data Storage
All persistent data is stored in `~/.mycelium/`:

```
~/.mycelium/
├── wallets/           # Bitcoin wallet databases
├── sporestack_token   # SporeStack API token
├── ssh/deploy_key     # SSH keypair for VPS access
└── server.json        # Acquired VPS info
```
