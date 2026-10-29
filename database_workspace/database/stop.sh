#!/usr/bin/env bash
# Stop the local development PostgreSQL instance started by startup.sh.
set -euo pipefail
PG_BIN="${PG_BIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -n 1)}"
PGDATA="${PGDATA:-${XDG_DATA_HOME:-$HOME/.local/share}/asset-health-postgres/pgdata}"
if [ -s "$PGDATA/postmaster.pid" ]; then
  "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast -w stop
else
  echo "No managed PostgreSQL instance is running in $PGDATA"
fi
