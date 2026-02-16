import asyncio
import os
import threading

from ipv8.configuration import ConfigBuilder, default_bootstrap_defs, Strategy, WalkerDefinition
from ipv8_service import IPv8
from pathlib import Path
from typing import Callable, Optional

from communities.ElectionCommunity import ElectionCommunity
from config import DATA_PATH
from models.election import Election
from models.person import Person
from models.vote import Vote
from storage.json_store import JSONStore
from ui.app import Application

# -----------------------------
# IPv8 startup / community setup
# -----------------------------
async def start_community(
    user_id: str,
    election_store: JSONStore[Election],
    vote_store: JSONStore[Vote],
    election_added: Callable[[], None],
    vote_added: Callable[[], None]
) -> ElectionCommunity:
    builder = ConfigBuilder().clear_keys().clear_overlays()

    os.makedirs("keys", exist_ok=True)
    builder.add_key("my peer", "curve25519", f"keys/{user_id}.pem")

    builder.add_overlay(
        overlay_class="ElectionCommunity",
        key_alias="my peer",
        walkers=[WalkerDefinition(Strategy.RandomWalk, 10, {"timeout": 3.0})],
        bootstrappers=default_bootstrap_defs,
        initialize={
            "election_store": election_store,
            "vote_store": vote_store,
            "election_added": election_added,
            "vote_added": vote_added
        },
        on_start=[("on_start",)]
    )

    ipv8 = IPv8(builder.finalize(), extra_communities={"ElectionCommunity": ElectionCommunity})
    await ipv8.start()

    # Return the actual overlay instance
    return next(o for o in ipv8.overlays if isinstance(o, ElectionCommunity))

def start_background_event_loop() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()

    def _loop_thread() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_loop_thread, daemon=True)
    thread.start()
    return loop, thread

# -----------------------------
# App entrypoint
# -----------------------------
def main() -> None:
    # --- Session user ---
    user = Person()  # Person generates a random ID by default

    # --- Data stores ---
    election_store = JSONStore[Election](
        path=Path(DATA_PATH + user.id + "/elections.json"),
        model_factory=Election.from_dict,
        dictify=lambda e: e.to_dict()
    )
    vote_store = JSONStore[Vote](
        path=Path(DATA_PATH + user.id + "/votes.json"),
        model_factory=Vote.from_dict,
        dictify=lambda v: v.to_dict()
    )

    # --- Shared state (overlay becomes available after IPv8 starts) ---
    community_ref: dict[str, Optional[ElectionCommunity]] = {"overlay": None}

    # --- IPv8 background loop ---
    loop, thread = start_background_event_loop()

    # --- UI callbacks ---
    def broadcast_new_election(election: Election) -> None:
        overlay: Optional[ElectionCommunity] = community_ref["overlay"]
        if overlay is None:
            # Community not ready yet; could queue these if needed.
            return
        loop.call_soon_threadsafe(overlay.on_create_election, election)

    def broadcast_new_vote(vote: Vote) -> None:
        overlay: Optional[ElectionCommunity] = community_ref["overlay"]
        if overlay is None:
            # Community not ready yet; could queue these if needed.
            return
        loop.call_soon_threadsafe(overlay.on_vote, vote)

    # --- UI creation (main thread) ---
    app = Application(user, election_store, vote_store, broadcast_new_election, broadcast_new_vote)

    # --- IPv8 -> UI callbacks (thread-safe via Tk) ---
    def election_added() -> None:
        app.root.after(0, lambda: app.list_frame.load(app.repo.get_all()))

    def vote_added() -> None:
        election_id = app.repo.get(app.detail_frame.election_id_var.get())
        if election_id:
            app.root.after(0, lambda: app.detail_frame.show(app.repo.get(app.detail_frame.election_id_var.get())))

    # --- Start IPv8 / overlay on background loop ---
    async def start_and_capture() -> None:
        overlay = await start_community(user.id, election_store, vote_store, election_added, vote_added)
        community_ref["overlay"] = overlay

    fut = asyncio.run_coroutine_threadsafe(start_and_capture(), loop)

    def _done_callback(f: asyncio.Future[None]) -> None:
        try:
            f.result(timeout=10)  # will re-raise any exception from the coroutine
        except Exception as e:
            print("IPv8 startup did not complete:", repr(e))
            raise

    fut.add_done_callback(_done_callback)

    # --- Run UI ---
    try:
        app.run()
    finally:
        # Stop the background loop when the application exits
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=1)

if __name__ == "__main__":
    main()
