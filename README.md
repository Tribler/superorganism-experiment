# superorganism-experiment
We are creating our own society. A place citizens have FULL control, have their own MONEY, have AI that serves THEM, and CONTROL together. Unstoppable by design, self-replicating, self-hosted, self-evolving, and human oversight with democratic governance. Well, that is our Utopian dream! It now runs and empowers a network of _seedboxes_.

Our work contains several novelties: 
- ⏩ Streaming Torrents. Quality streaming in P2P, competitive to Tiktok/Youtube/Netflix {warning: [still on seperate branch](https://github.com/Tribler/tribler/discussions/9003). Streaming GUI requires QT, decoder, Javascript bloat 🥹}.
- 🪞 Self-replication. Servers that can buy other servers using Bitcoin. Fully automated cloning of servers.
- ⚡ Trust. First trust framework and true Peer-to-Peer agent communication fabric. No DNS, no central control.
- 🧑‍🚒 AI models in a real-time competition for survival of the fittest using multi-arm-bandit and model score gossip.
- 👓 Find information using decentralized relevance ranking
- 🥇 First decentralized voting system. Your place, your control, your vote. Our vibe coded demo we're implementing [with real crypto](https://arxiv.org/pdf/2507.09453).
- 🥼 User-driven self-evolution. The emergent voting behavior is that users drive the roadmap using democracy. No lawyer or company can stop the will of the people.

![demo_of_democratic_voting_process](https://github.com/user-attachments/assets/c5881768-71df-4a82-8f7b-ad3c02a64ceb)

Disclaimer is that each novelty still requires years of polish, but they work and together form a unique system.
<img width="1838" height="885" alt="Image" src="https://github.com/user-attachments/assets/971b1bfb-7566-4e3f-b51a-04b8202c8c14" />

## Technical documentation

Superorganism is the joint work of professors, post-docs, phd students and master students (e.g. the ones doing the real work!).
Algorithms and key components are documented in these documents.

Algorithm | Superorganism algorithm extensive documentation
---|---
SurvivalRank | [Evolutionary survival of fittest algorithm using decentralized multi-arm bandits](https://github.com/user-attachments/files/29499230/SurvivalRank.Decentralized.Evolution.of.Search.Models.pdf)
FuSST | [Social Capital Accounting for trust with Sybil resilience](https://github.com/user-attachments/files/29458168/Master_Thesis___Towards_Solving_Sybil_Attacks_Using_Social_Capital_Accounting-4.pdf)
TwoStepDemocracy | [TwoStepDemocracy: prototyping of self-evolving, democratic, and decentralized systems](https://arxiv.org/html/2606.25559v1) {[#8812](https://github.com/Tribler/tribler/issues/8812)}
SelfReplicate | [Self-replicating seedbox servers using programmable money](https://github.com/user-attachments/files/29197003/MSc__Matei_Dogariu_arXiv.pdf)
DelftClaw | [Infrastructure for decentralized OpenClaw semantic search agents: identity, trust, communication, and self-replication](https://github.com/tribler/tribler/issues/8923) (5 bsc students, needs integration)

## Features - Everything we built so far 

Now that the basic components are all operational, we're working on integration.

1) A [million URLs with creative commons](https://github.com/Tribler/superorganism-experiment/blob/main/self_replication_service__mycelium/seedbox-bootstrap/yt-cc-dataset-id-extraction/cc_video_ids.txt.tar.bz2) content on Youtube + download tooling + Bittorrent [autoseeding](https://github.com/Tribler/superorganism-experiment/tree/main/self_replication_service__mycelium/seedbox-bootstrap)
2) Decentralized [survival-of-fittest learn-to-rank](https://github.com/Tribler/superorganism-experiment/tree/main/crowdsourced_learn_to_rank) algorithm.
3) Semantic overlay (ToDo [integrate our decentralized semantic overlay](https://arxiv.org/html/2502.10151v1))
4) Search engine (ToDo [integrate our decentralized learn-to-rank AI algorithms](https://arxiv.org/html/2505.07452v1))
5) Voting and use your Bitcoin wallet to stake your identity (ToDo move from testnet to mainnet)

## General

Qt UI resources are listed in the [ui/resources/](ui/resources/) directory, including icons, fonts, images, and the resource manifest. They must be converted using the PySide6 resource compiler. Run the following command after adding new UI resources:

```bash
pyside6-rcc ui/resources/resources.qrc -o ui/resources/resources_rc.py
```

## Local Bitcoin regtest environment

This project uses a local **Bitcoin Core regtest node** for development and integration testing. Regtest is a private blockchain intended for testing. It does not connect to mainnet, and blocks can be mined on demand.

The script `scripts/regtest.sh` automates the local setup by:

- creating a dedicated regtest data directory inside the project
- generating a bitcoin.conf
- starting bitcoind
- creating or loading a wallet
- mining initial blocks so the wallet has spendable funds
- exposing simple commands for status, reset, mining, and demo transactions

### Dependencies

The script requires:

- bash
- bitcoind (part of **Bitcoin Core**)
- bitcoin-cli (part of **Bitcoin Core**)
- jq (for JSON parsing)

### Installing dependencies

#### macOS

```bash
brew install bitcoin
```

```bash
brew install jq
```

### Project-local data directory

The script stores all regtest data inside the repository:

```aiignore
.bitcoin/regtest-demo/
```

### Configuration

The script supports a few environment variables, but all have sensible defaults.

| Variable         | Default                   | Description                      |
|------------------|---------------------------|----------------------------------|
| `BITCOIND_BIN`   | `bitcoind`                | Path to the `bitcoind` binary    |
| `BITCOINCLI_BIN` | `bitcoin-cli`             | Path to the `bitcoin-cli` binary |
| `DATA_DIR`       | `./.bitcoin/regtest-demo` | Regtest data directory           |
| `WALLET_NAME`    | `demo`                    | Wallet name used for testing     |
| `RPC_USER`       | `demo`                    | RPC username                     |
| `RPC_PASSWORD`   | `superorganism`           | RPC password                     |
| `RPC_PORT`       | `18443`                   | Regtest RPC port                 |
| `P2P_PORT`       | `18444`                   | Regtest P2P port                 |
| `HOST`           | `127.0.0.1`               | Host interface for the node      |

### Usage

The script supports the following commands:

```bash
scripts/regtest.sh start
scripts/regtest.sh stop
scripts/regtest.sh reset
scripts/regtest.sh status
scripts/regtest.sh mine [n]
scripts/regtest.sh send <address> [amount] [op_return_hex]
scripts/regtest.sh treasury-address
scripts/regtest.sh sign-psbt <psbt_base64>
```

| Command            | Description                                                                                                                                                                                                                                                    |
|--------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `start`            | Starts the regtest node, creates the config file if needed, loads or creates the wallet, and ensures the wallet is funded. On first startup, the script mines 101 blocks. This is necessary because coinbase rewards must mature before they become spendable. |
| `stop`             | Stops the running regtest node.                                                                                                                                                                                                                                |
| `reset`            | Deletes the local regtest blockchain and wallet state, then starts from a clean environment. This is useful for repeatable integration tests.                                                                                                                  |
| `status`           | Prints basic blockchain and wallet state.                                                                                                                                                                                                                      |
| `mine`             | Mines one or more new regtest blocks. This is especially useful for confirming transactions during testing.                                                                                                                                                    |
| `send`             | Sends a demo transaction from the local wallet.                                                                                                                                                                                                                |
| `treasury-address` | Prints the address of the treasury. This is useful for funding the wallet from external tools or for testing incoming transactions.                                                                                                                            |
| `sign-psbt`        | Signs a base64 PSBT with the local demo wallet using `ALL\|ANYONECANPAY` and prints the signed PSBT. This is intended for the local funding-pledge flow.                                                                                                       |

## Mycelium

Autonomous VPS provisioning system using Bitcoin payments and SporeStack API. Deploys Mycelium a BitTorrent seedbox orchestrator for Creative Commons content.

### What it does

- Seeds content via BitTorrent (libtorrent)
- Auto-updates from GitHub and restarts on changes
- Broadcasts seeded content to IPV8 peers for health monitoring
