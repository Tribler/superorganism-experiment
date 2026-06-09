#!/bin/sh
# Entrypoint for the mycelium-base LXC image.
# mock_sporestack pushes /root/sim_env (mode 600) before `lxc start`.
# Format: KEY=VALUE lines, plus __SECRET_B64__<absolute_path>=<base64> lines
# for each entry of the SimDeployer `secrets` dict.
set -eu

SIM_ENV="/root/sim_env"
DATA_DIR="/root/data"
CODE_DIR="/root/mycelium/code"
LOG_DIR="/root/logs"

mkdir -p "${DATA_DIR}" "${LOG_DIR}"
chmod 700 "${DATA_DIR}"

if [ ! -f "${SIM_ENV}" ]; then
    echo "[entrypoint] FATAL: ${SIM_ENV} missing — mock_sporestack must push it before lxc start" >&2
    exit 1
fi

# Pass 1: export env vars only (defer secrets so bitcoinlib's first-run install
# below doesn't run with stale config and can't clobber files we haven't written yet).
while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
        ""|"#"*|__SECRET_B64__*)
            continue
            ;;
        *=*)
            key="${line%%=*}"
            val="${line#*=}"
            export "${key}=${val}"
            ;;
        *)
            echo "[entrypoint] WARN: skipping malformed line: ${line}" >&2
            ;;
    esac
done < "${SIM_ENV}"

# Trigger bitcoinlib's first-run installer NOW. It writes ~/.bitcoinlib/{providers.json,
# install.log, ...} from package templates the first time it's imported. If we let
# main.py do it, it would overwrite our injected /root/.bitcoinlib/providers.json
# (which has the regtest electrumx provider entry the rest of the system depends on).
python3 -c "import bitcoinlib.main" >/dev/null 2>&1 || true

# Pass 2: decode secrets — overwrites whatever bitcoinlib install just wrote.
while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
        __SECRET_B64__*)
            rest="${line#__SECRET_B64__}"
            secret_path="${rest%%=*}"
            secret_b64="${rest#*=}"
            mkdir -p "$(dirname "${secret_path}")"
            printf '%s' "${secret_b64}" | base64 -d > "${secret_path}"
            chmod 600 "${secret_path}"
            ;;
    esac
done < "${SIM_ENV}"

cd "${CODE_DIR}"
exec python3 main.py
