#!/usr/bin/env bash
# Start the integrated API role and the durable worker role from one backend artifact.
# The migration role is used only by Alembic; the API and worker use DATABASE_URL.
set -euo pipefail

HOST="${1:-0.0.0.0}"
PORT="${2:-8000}"
WORKER_PID=""
API_PID=""

cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM

  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
  fi
  if [[ -n "$WORKER_PID" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
    kill "$WORKER_PID" 2>/dev/null || true
  fi

  wait "$API_PID" 2>/dev/null || true
  wait "$WORKER_PID" 2>/dev/null || true
  exit "$status"
}

trap cleanup EXIT HUP INT TERM

# Alembic reads MIGRATION_DATABASE_URL; startup aborts rather than serving stale schema.
python -m alembic upgrade head

# The worker is intentionally a separate runtime process, even though it shares this codebase.
python -m app.worker.main &
WORKER_PID=$!

UVICORN_ARGS=(src.api.main:app --host "$HOST" --port "$PORT")
if [[ "${TRUST_PROXY:-false}" =~ ^(1|true|yes|on)$ ]]; then
  # Trust forwarded headers only after the deployment explicitly enables this setting.
  UVICORN_ARGS+=(--proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}")
fi

uvicorn "${UVICORN_ARGS[@]}" &
API_PID=$!

# Keep PreviewManager attached to the API while the EXIT trap stops both runtime roles.
wait "$API_PID"
