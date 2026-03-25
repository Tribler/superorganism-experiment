# superorganism-experiment
We are creating our own society. A place citizens have FULL control, have their own MONEY, have AI that serves THEM, and CONTROL together. Unstoppable by design, self-replicating, self-hosted, self-evolving, and human oversight with democratic governance. Well, that is our Utopian dream! It now runs and empowers a network of _seedboxes_.

Our work contains several novelties: 
- 🪞 Self-replication. Servers that can buy other servers using Bitcoin. Fully automated cloning of servers.
- ⚡ Trust. First trust framework and true Peer-to-Peer agent communication fabric. No DNS, no central control.
- 🧑‍🚒 AI models in a real-time competition for survival of the fittest using multi-arm-bandit and model score gossip.
- 👓 Find information using decentralized relevance ranking
- 🥇 First decentralized voting system. Your place, your control, your vote. Our vibe coded demo we're implementing [with real crypto](https://arxiv.org/pdf/2507.09453).
- 🥼 User-driven self-evolution. The emergent voting behavior is that users drive the roadmap using democracy. No lawyer or company can stop the will of the people.

![demo_of_democratic_voting_process](https://github.com/user-attachments/assets/c5881768-71df-4a82-8f7b-ad3c02a64ceb)

Disclaimer is that each novelty still requires years of polish, but they work and together form a unique system.
<img width="1838" height="885" alt="Image" src="https://github.com/user-attachments/assets/971b1bfb-7566-4e3f-b51a-04b8202c8c14" />

## Detailed progress issues with weekly updates 

Andrei: [live switch between re-ranking algorithm using P2P multi-arm bandit and performance gossip protocol](https://github.com/Tribler/tribler/issues/8666)

Stan: [voting and stake your identity](https://github.com/Tribler/tribler/issues/8812)

Matei: [self-replicating server. Server with wallet can buy antoher server and clone itself.](https://github.com/Tribler/tribler/issues/8664)

Aayush: [trust framework, reputation function of identities, social capital account[keys](keys)ing for Sybil attack detection.](https://github.com/Tribler/tribler/issues/8667)

Marcel: P2P search with [decentralized relevance ranking](https://github.com/mg98/dart-live/)

## Everything we built so far / Desired features for first March release

1) A million URLs with creative commons content
2) Liberate this content to robotic Bittorrent seedboxes fleet
3) Semantic search
4) Bitcoin wallet for donations and funding Seedboxes
5) Voting and use your Bitcoin wallet to stake your identity (public key)

other ideas: Bounties, seedbox fleet? status of IPv8 network? Money in system, amount of discovered users?

## Mycelium

Autonomous BitTorrent orchestrator that seeds Creative Commons content.

### What it does

- Seeds content via BitTorrent (libtorrent)
- Auto-updates from GitHub and restarts on changes
- Broadcasts seeded content to IPV8 peers for health monitoring

### Deployment

This is deployed to a SporeStack VPS via `mycelium-bootstrap/`. See that directory for deployment instructions.

### Running locally

```bash
pip install -r code/requirements.txt
cd code && python main.py
```

### Configuration

All config via `MYCELIUM_*` environment variables. See `code/config.py` for defaults.

## Mycelium-bootstrap (Mycelium VPS Deployer)

Autonomous VPS provisioning system using Bitcoin payments and SporeStack API. Deploys [mycelium](https://github.com/DogariuMatei/mycelium), a BitTorrent orchestrator for Creative Commons content.

### Quick Start
#### 0. Install dependencies
```bash
pip install -r requirements.txt
```
#### 1. Create and fund Bitcoin wallet
```bash
python wallet.py create mycelium
python wallet.py address mycelium      # Send BTC to this address
python wallet.py scan mycelium         # Verify funds received
```
#### 2. Fund SporeStack account
```bash
python fund_sporestack.py fund 100
```

#### 3. Acquire VPS
```bash
python acquire_vps.py
```

#### 4. Deploy mycelium to VPS
```bash
python deploy_mycelium.py
```
#### 5. (Optional) Stop mycelium
```bash
python stop_mycelium.py
```

### CLI Reference

#### wallet.py

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

#### fund_sporestack.py

SporeStack account funding via Bitcoin.

```
python fund_sporestack.py <command> [amount]

Commands:
  fund [amount]     Fund account (default: $10)
  balance           Check SporeStack balance
  token             Display saved token
  help              Show usage
```

#### acquire_vps.py

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

#### deploy_mycelium.py

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

#### stop_mycelium.py

Stop mycelium orchestrator on the VPS to save resources.

```
python stop_mycelium.py
```

Connects to the VPS and kills the running mycelium process. Run `deploy_mycelium.py` to restart.

### Content Sourcing

Search for Creative Commons videos and download them:

```bash
# Requires YOUTUBE_API_KEY in .env
python yt-api-cc-scripts/yt-api-cc.py
python yt-api-cc-scripts/yt-api-cc-playlists.py

# Download collected URLs
./scripts/parallel_ytdlp_download.sh
```

### Data Storage

All persistent data is stored in `~/.mycelium/`:

```
~/.mycelium/
├── wallets/           # Bitcoin wallet databases
├── sporestack_token   # SporeStack API token
├── ssh/deploy_key     # SSH keypair for VPS access
└── server.json        # Acquired VPS info
```

## Mycelium-simulation (Mycelium Economic Simulation)

Simulates the economic lifecycle of self-replicating mycelium nodes: income (faucet), expenses (rent), reproduction (spawning children), and death (running out of funds).

### Quick start

```bash
pip install -r requirements.txt
```

```bash
python -m host.simulator -c config/small.yaml
```

Output goes to `data/events.csv`. Set `tick_interval: 0` in the config to run at full speed.

### Changing parameters

All parameters live in `config/default.yaml`. To experiment, change it or create a new config file.
```bash
python -m host.simulator -c config/<your_file>.yaml
```

### How a tick works

Each tick is a synchronous round:

1. Rent is deducted from every living node
2. Bankrupt nodes are killed
3. Faucet injects funds
4. Every living node decides exactly once: `none`, `spawn`, or `failsafe`
5. Decisions are processed (spawns transfer inheritance; failsafe nodes donate all funds then die)
6. Conservation invariant is checked

### Plotting results

```bash
python analysis/plot.py data/events.csv -o data/plots
```

## Democracy

