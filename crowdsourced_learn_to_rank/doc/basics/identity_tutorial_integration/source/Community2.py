import os
from dataclasses import dataclass

from ipv8.community import Community, CommunitySettings
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload
from ipv8.peer import Peer


@dataclass
class MyMessage(DataClassPayload[1]):
    clock: int


class MyCommunity(Community):
    community_id = os.urandom(20)

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)

        self.add_message_handler(MyMessage, self.on_message)


        self.lamport_clock = 0

    def started(self) -> None:
        async def start_communication() -> None:
            if not self.lamport_clock:

                for p in self.get_peers():
                    self.ez_send(p, MyMessage(self.lamport_clock))
            else:
                self.cancel_pending_task("start_communication")

        self.register_task("start_communication", start_communication, interval=5.0, delay=0)

    @lazy_wrapper(MyMessage)
    def on_message(self, peer: Peer, payload: MyMessage) -> None:
        self.lamport_clock = max(self.lamport_clock, payload.clock) + 1
        print(">>> COMMUNITY2 LOADED <<<", self.my_peer, "current clock:", self.lamport_clock)
        self.ez_send(peer, MyMessage(self.lamport_clock))
