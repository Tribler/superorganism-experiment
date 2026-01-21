# Mycelium

Autonomous BitTorrent orchestrator that seeds Creative Commons content.

## What it does

- Seeds content via BitTorrent (libtorrent)
- Auto-updates from GitHub and restarts on changes
- Broadcasts seeded content to IPV8 peers for health monitoring

## Deployment

This is deployed to a SporeStack VPS via `mycelium-bootstrap/`. See that directory for deployment instructions.

## Running locally

```bash
pip install -r code/requirements.txt
cd code && python main.py
```

## Configuration

All config via `MYCELIUM_*` environment variables. See `code/config.py` for defaults.