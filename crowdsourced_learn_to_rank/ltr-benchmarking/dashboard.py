"""Dashboard server for LTR MAB experiments.

Run with: python dashboard.py
Then open http://127.0.0.1:8085 in your browser to configure and start experiments.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from aiohttp import web

sys.path.insert(0, str(Path(__file__).parent))


class DashboardState:
    """Shared state between experiment and dashboard."""

    def __init__(self):
        self.communities = []
        self.current_round = 0
        self.phase = "idle"
        self.config = {}
        self.oracle = {}
        self.events = []
        self.round_history = []  # list of per-round snapshots for charts
        self.t0 = time.time()
        self.running = False

    def reset(self):
        self.communities = []
        self.current_round = 0
        self.phase = "idle"
        self.config = {}
        self.oracle = {}
        self.events = []
        self.round_history = []
        self.t0 = time.time()
        self.running = False

    def event(self, msg: str, kind: str = "info"):
        self.events.append({"t": round(time.time() - self.t0, 2), "kind": kind, "msg": msg})
        if len(self.events) > 200:
            self.events = self.events[-200:]

    def snapshot(self) -> dict:
        peers = []
        for c in self.communities:
            stats = c.bandit.get_stats()
            q = c.queries_processed or 1
            peers.append({
                "id": c.peer_id,
                "queries": c.queries_processed,
                "active": sorted(c.active_models),
                "excluded": sorted(c.excluded_models),
                "best": c.bandit.get_best_arm() if c.bandit.total_pulls > 0 else None,
                "scores": {str(k): round(v / q, 4) for k, v in c.cumulative_scores.items()},
                "arms": {
                    name: {
                        "pulls": s["pulls"],
                        "reward": round(c._get_mean_reward(s), 4),
                        "status": "excluded" if name in c.excluded_models else "active",
                    }
                    for name, s in stats.items()
                },
            })
        return {
            "round": self.current_round,
            "phase": self.phase,
            "running": self.running,
            "config": self.config,
            "oracle": self.oracle,
            "elapsed": round(time.time() - self.t0, 1),
            "peers": peers,
            "round_history": self.round_history,
        }


state = DashboardState()


async def _index(_):
    return web.FileResponse(Path(__file__).parent / "dashboard.html")

async def _api(_):
    return web.Response(text=json.dumps(state.snapshot()), content_type="application/json")

async def _events(req):
    since = float(req.query.get("since", 0))
    return web.Response(
        text=json.dumps([e for e in state.events if e["t"] > since]),
        content_type="application/json",
    )

async def _datasets(_):
    from datasets import detect_datasets
    datasets = detect_datasets(Path(__file__).parent / "data")
    return web.Response(text=json.dumps(datasets), content_type="application/json")

async def _start(req):
    if state.running:
        return web.Response(
            text=json.dumps({"error": "Experiment already running"}),
            content_type="application/json",
            status=409,
        )

    body = await req.json()
    dataset = body.get("dataset", "mslr-web10k")
    peers = int(body.get("peers", 5))
    rounds = int(body.get("rounds", 5))
    queries = int(body.get("queries", 100))
    gossip = bool(body.get("gossip", True))
    hotswap_round = int(body.get("hotswap_round", 0))
    algorithm = body.get("algorithm", "ucb1")
    metric = body.get("metric", "ndcg")

    state.reset()
    state.running = True
    state.phase = "loading"
    state.t0 = time.time()
    state.event(f"Starting experiment: {dataset}, {peers} peers, {rounds} rounds, {algorithm}, {metric.upper()}, gossip={'on' if gossip else 'off'}, hotswap={'round '+str(hotswap_round) if hotswap_round else 'off'}", "round")

    asyncio.ensure_future(_run_experiment(dataset, peers, rounds, queries, gossip, hotswap_round, algorithm, metric, state))

    return web.Response(text=json.dumps({"ok": True}), content_type="application/json")

async def _run_experiment(dataset, peers, rounds, queries, gossip, hotswap_round, algorithm, metric, dashboard_state):
    import traceback
    try:
        from local_experiment import run_local_experiment
        await run_local_experiment(
            dataset_id=dataset,
            num_peers=peers,
            num_rounds=rounds,
            queries_per_round=queries,
            gossip_enabled=gossip,
            hotswap_round=hotswap_round,
            algorithm=algorithm,
            metric=metric,
            dashboard_state=dashboard_state,
        )
    except Exception as e:
        traceback.print_exc()
        dashboard_state.phase = "error"
        dashboard_state.event(f"Error: {e}", "exclusion")
    finally:
        dashboard_state.running = False


async def start_dashboard(host="127.0.0.1", port=8085):
    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/api", _api)
    app.router.add_get("/api/events", _events)
    app.router.add_get("/api/datasets", _datasets)
    app.router.add_post("/api/start", _start)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner


if __name__ == "__main__":
    async def main():
        runner = await start_dashboard()
        print("Dashboard running at http://127.0.0.1:8085")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await runner.cleanup()

    asyncio.run(main())
