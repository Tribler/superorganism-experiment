#!/bin/sh
# Entrypoint for the ipv8-bootstrap LXC image (sim TODO 8.8).
# Starts pyipv8's vendored tracker on UDP/7759 — every mycelium sim node is
# pointed at <this_container_ip>:7759 via MYCELIUM_IPV8_BOOTSTRAP by 8.10.
set -eu

cd /root/tracker
exec python3 tracker_plugin.py --listen_port 7759
