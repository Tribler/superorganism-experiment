#!/usr/bin/env bash
# Build the mycelium-base LXC image used by the offline thesis sim.
# Reproducible: drop into ~/.bash_history-free repo state and re-run safely.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MYCELIUM_CODE="$(cd "${SCRIPT_DIR}/../../../mycelium/code" && pwd)"

BUILDER="mycelium-builder"
ALIAS="mycelium-base"

echo "[build.sh] mycelium code: ${MYCELIUM_CODE}"
echo "[build.sh] builder: ${BUILDER} -> alias: ${ALIAS}"

# Idempotent cleanup of any previous failed build.
lxc delete --force "${BUILDER}" 2>/dev/null || true
lxc image delete "${ALIAS}" 2>/dev/null || true

# 1. Launch Alpine 3.20.
lxc launch images:alpine/3.20 "${BUILDER}"

# Wait for network — image install needs DNS + outbound HTTP.
echo "[build.sh] waiting for container network..."
until lxc exec "${BUILDER}" -- ping -c1 -W2 1.1.1.1 >/dev/null 2>&1; do
    sleep 1
done

# 2a. Runtime apk deps.
lxc exec "${BUILDER}" -- apk add --no-cache \
    python3 py3-pip git libsodium ca-certificates

# 2b. Transient build deps in a virtual package so we can apk del them in one shot.
# Required because Alpine/musl often lacks musllinux wheels for cryptography/bcrypt/pynacl.
lxc exec "${BUILDER}" -- apk add --no-cache --virtual .build-deps \
    build-base python3-dev libffi-dev openssl-dev libsodium-dev rust cargo

# 3. Push mycelium code into /root/mycelium/code/.
lxc exec "${BUILDER}" -- mkdir -p /root/mycelium /root/data /root/logs
lxc file push -r "${MYCELIUM_CODE}" "${BUILDER}/root/mycelium/"
lxc exec "${BUILDER}" -- chmod 700 /root/data

# 4. Push slim requirements + pip install, then drop build deps.
lxc file push "${SCRIPT_DIR}/requirements-sim.txt" "${BUILDER}/root/requirements-sim.txt"
lxc exec "${BUILDER}" -- pip install --no-cache-dir --break-system-packages \
    -r /root/requirements-sim.txt
lxc exec "${BUILDER}" -- apk del .build-deps
lxc exec "${BUILDER}" -- sh -c 'rm -rf /root/.cache /tmp/* /var/cache/apk/*'

# 5. Push entrypoint to a stable path on PATH.
lxc file push --mode=0755 "${SCRIPT_DIR}/entrypoint.sh" \
    "${BUILDER}/usr/local/bin/mycelium-entrypoint"

# 6. Stop, snapshot, publish, clean up the builder.
lxc stop "${BUILDER}"
lxc snapshot "${BUILDER}" base
lxc publish "${BUILDER}/base" --alias "${ALIAS}"
lxc delete --force "${BUILDER}"

echo "[build.sh] published image: ${ALIAS}"
lxc image info "${ALIAS}" | grep -E "(Size|Fingerprint)" || true
