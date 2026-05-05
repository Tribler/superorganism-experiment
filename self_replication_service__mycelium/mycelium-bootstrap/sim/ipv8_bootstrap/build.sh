#!/usr/bin/env bash
# Build the ipv8-bootstrap LXC image used by the offline thesis sim (TODO 8.8).
# Standalone IPv8 tracker peer; 8.10 runs one instance and injects its IP as
# MYCELIUM_IPV8_BOOTSTRAP=<ip>:7759 into every mycelium child.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BUILDER="ipv8-bootstrap-builder"
ALIAS="ipv8-bootstrap-base"
INSTANCE="ipv8-bootstrap"

echo "[build.sh] builder: ${BUILDER} -> alias: ${ALIAS}"

# Idempotent cleanup: any prior running instance, builder, or published image.
lxc delete --force "${INSTANCE}" 2>/dev/null || true
lxc delete --force "${BUILDER}" 2>/dev/null || true
lxc image delete "${ALIAS}" 2>/dev/null || true

# 1. Launch Alpine 3.20.
lxc launch images:alpine/3.20 "${BUILDER}"

# Wait for network — pip needs DNS + outbound HTTP.
echo "[build.sh] waiting for container network..."
until lxc exec "${BUILDER}" -- ping -c1 -W2 1.1.1.1 >/dev/null 2>&1; do
    sleep 1
done

# 2a. Runtime apk deps.
lxc exec "${BUILDER}" -- apk add --no-cache \
    python3 py3-pip libsodium ca-certificates

# 2b. Transient build deps in a virtual package — same musllinux-wheel
# rationale as the mycelium-base image (cryptography/pynacl wheels often
# missing on Alpine).
lxc exec "${BUILDER}" -- apk add --no-cache --virtual .build-deps \
    build-base python3-dev libffi-dev openssl-dev libsodium-dev rust cargo

# 3. Install pyipv8 — pinned to match mycelium-base so client and bootstrap
# speak the same IPv8 protocol version.
lxc exec "${BUILDER}" -- pip install --no-cache-dir --break-system-packages \
    pyipv8==3.1.0

# 4. Drop build deps and caches.
lxc exec "${BUILDER}" -- apk del .build-deps
lxc exec "${BUILDER}" -- sh -c 'rm -rf /root/.cache /tmp/* /var/cache/apk/*'

# 5. Push the vendored tracker scripts into /root/tracker/.
lxc exec "${BUILDER}" -- mkdir -p /root/tracker /root/data
lxc exec "${BUILDER}" -- chmod 700 /root/data
lxc file push "${SCRIPT_DIR}/tracker_plugin.py"  "${BUILDER}/root/tracker/tracker_plugin.py"
lxc file push "${SCRIPT_DIR}/tracker_service.py" "${BUILDER}/root/tracker/tracker_service.py"
lxc file push "${SCRIPT_DIR}/__scriptpath__.py"  "${BUILDER}/root/tracker/__scriptpath__.py"

# 6. Push entrypoint to a stable path on PATH.
lxc file push --mode=0755 "${SCRIPT_DIR}/entrypoint.sh" \
    "${BUILDER}/usr/local/bin/ipv8-bootstrap-entrypoint"

# 7. Stop, snapshot, publish, clean up the builder.
lxc stop "${BUILDER}"
lxc snapshot "${BUILDER}" base
lxc publish "${BUILDER}/base" --alias "${ALIAS}"
lxc delete --force "${BUILDER}"

echo "[build.sh] published image: ${ALIAS}"
lxc image info "${ALIAS}" | grep -E "(Size|Fingerprint)" || true
