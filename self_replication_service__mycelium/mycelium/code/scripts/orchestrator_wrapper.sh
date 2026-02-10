#!/bin/bash
#
# Orchestrator wrapper script for process supervision.
#
# Monitors orchestrator exit code and restarts on code updates.
# Exit code 42 indicates restart required after code update.
# Other exit codes terminate the wrapper.

MYCELIUM_SUBPATH="self_replication_service__mycelium/mycelium"
ORCHESTRATOR_DIR="${MYCELIUM_BASE_DIR:-/root/mycelium}/${MYCELIUM_SUBPATH}/code"
LOG_DIR="${MYCELIUM_LOG_DIR:-/root/logs}"
EXIT_RESTART=42

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Wrapper started"

while true; do
    log "Starting orchestrator"

    cd "$ORCHESTRATOR_DIR" || {
        log "ERROR: Cannot access $ORCHESTRATOR_DIR"
        exit 1
    }

    python3 main.py
    EXIT_CODE=$?

    log "Orchestrator exited with code $EXIT_CODE"

    if [ $EXIT_CODE -eq $EXIT_RESTART ]; then
        log "Restart requested, restarting orchestrator"
        sleep 2
        continue
    else
        log "Terminating wrapper"
        exit $EXIT_CODE
    fi
done
