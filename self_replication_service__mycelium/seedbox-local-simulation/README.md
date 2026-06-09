# Seedbox Local Simulation

Offline test harness that runs mycelium. No real money, no public BTC network. Produces data for the thesis graphs. The target stack is Alpine Linux + LXC
containers + Bitcoin regtest.

It drives the deployment tooling in [`../seedbox-bootstrap/`](../seedbox-bootstrap/README.md):
`run_simulation.py` cross-imports `lib/` from there, so install its requirements too (below).

## Install Dependencies

### 1. Python 3.11+
```bash
python3 --version   # must be 3.11 or newer
```

### 2. LXD
```bash
sudo snap install lxd
sudo lxd init --auto
sudo usermod -aG lxd $USER
# Log out and back in (or: newgrp lxd) for group to take effect
```

### 3. Bitcoin Core (`bitcoind` + `bitcoin-cli`)
Download directly from bitcoincore.org (the PPA is unmaintained):
```bash
VERSION="31.0"   # check https://bitcoincore.org/en/download/ for latest
wget https://bitcoincore.org/bin/bitcoin-core-${VERSION}/bitcoin-${VERSION}-x86_64-linux-gnu.tar.gz
tar -xzf bitcoin-${VERSION}-x86_64-linux-gnu.tar.gz
sudo install -m 0755 -t /usr/local/bin bitcoin-${VERSION}/bin/bitcoind bitcoin-${VERSION}/bin/bitcoin-cli
```

### 4. Electrs (Electrum server)
Requires Rust and a C linker. Build from source:
```bash
sudo apt install build-essential clang libclang-dev
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
git clone https://github.com/romanz/electrs /tmp/electrs
cd /tmp/electrs && cargo build --release
sudo install -m 0755 /tmp/electrs/target/release/electrs /usr/local/bin/electrs
```

### 5. Python packages
The simulation reuses the bootstrap tooling's dependencies:
```bash
pip install -r ../seedbox-bootstrap/requirements.txt
```

## Run Simulation

From `cd self_replication_service__mycelium/seedbox-local-simulation`:
```bash
./run_simulation.py --rebuild-images
```
```bash
./stop_simulation.sh && python3 run_simulation.py
```

Default configurable parameters can be found in `sim_config.toml`.

To check the logs of any running container, in a secondary terminal:
```bash
lxc list                                                    # pick whichever m-<12hex> id, then
lxc exec   m-<hex_here> -- cat /root/logs/orchestrator.log  # orchestrator logs
```

Stop + delete all containers:
```bash
./stop_simulation.sh
```

Saves events.jsonl to `data/runs/<timestamp>/`, kills the host services, deletes the containers.
Images and the genesis wallet stay.

## Analysis

After a run, open `analysis/analysis.ipynb` (pandas + matplotlib + networkx). The loader
auto-picks the latest `data/events-*.jsonl` (or an archived `data/runs/events-*.jsonl`) and
produces the thesis graphs + tables.
