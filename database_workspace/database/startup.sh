#!/usr/bin/env bash
# Start (and, on first run, initialise) the local development PostgreSQL instance,
# then idempotently provision the application database and least-privilege roles
# (STEP-02, AC-17). Safe to re-run. Credentials below are DEVELOPMENT-ONLY defaults
# and can be overridden through the environment; never reuse them in production.
#
# Roles:
#   DB_ADMIN_USER      cluster superuser, used only by this script
#   DB_MIGRATION_USER  owns the database and the public schema; the only role that
#                      may run DDL (Alembic runs as this role)
#   DB_APP_USER        runtime role used by the API and worker: CONNECT, USAGE, and
#                      SELECT/INSERT/UPDATE on tables (and USAGE/SELECT on sequences)
#                      created by the migration role. No CREATE, no DELETE.
#
# The data directory lives OUTSIDE the workspace by default. The workspace is
# permission-normalised to 0777 by the platform, and PostgreSQL refuses to start
# on a data directory that is not 0700/0750.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PG_BIN="${PG_BIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -n 1)}"
DB_PORT="${DB_PORT:-5432}"
DB_HOST="${DB_HOST:-localhost}"
DB_NAME="${DB_NAME:-asset_health}"
DB_ADMIN_USER="${DB_ADMIN_USER:-appadmin}"
DB_ADMIN_PASSWORD="${DB_ADMIN_PASSWORD:-dev-only-change-me}"
DB_MIGRATION_USER="${DB_MIGRATION_USER:-asset_migrator}"
DB_MIGRATION_PASSWORD="${DB_MIGRATION_PASSWORD:-dev-only-migrator-change-me}"
DB_APP_USER="${DB_APP_USER:-asset_app}"
DB_APP_PASSWORD="${DB_APP_PASSWORD:-dev-only-app-change-me}"
PGDATA="${PGDATA:-${XDG_DATA_HOME:-$HOME/.local/share}/asset-health-postgres/pgdata}"
LOG_FILE="$HERE/postgres.log"

if [ -z "$PG_BIN" ] || [ ! -x "$PG_BIN/postgres" ]; then
  echo "PostgreSQL server binaries not found (set PG_BIN)." >&2
  exit 1
fi

# Role and database names are interpolated as quoted identifiers below; keep them simple.
for ident in "$DB_NAME" "$DB_MIGRATION_USER" "$DB_APP_USER"; do
  if ! [[ "$ident" =~ ^[a-z_][a-z0-9_]*$ ]]; then
    echo "Invalid identifier '$ident' (use lowercase letters, digits, underscore)." >&2
    exit 1
  fi
done
if [ "$DB_MIGRATION_USER" = "$DB_APP_USER" ]; then
  echo "DB_MIGRATION_USER and DB_APP_USER must differ (least privilege)." >&2
  exit 1
fi

if "$PG_BIN/pg_isready" -q -h "$DB_HOST" -p "$DB_PORT"; then
  echo "PostgreSQL already accepting connections on $DB_HOST:$DB_PORT"
else
  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initialising cluster in $PGDATA"
    mkdir -p "$(dirname "$PGDATA")"
    PWFILE="$(mktemp)"
    printf '%s' "$DB_ADMIN_PASSWORD" > "$PWFILE"
    "$PG_BIN/initdb" -D "$PGDATA" -U "$DB_ADMIN_USER" --pwfile="$PWFILE" \
      --auth-local=scram-sha-256 --auth-host=scram-sha-256 --encoding=UTF8
    rm -f "$PWFILE"
  fi
  # Restore the required data-directory mode in case something widened it.
  chmod 0700 "$PGDATA"
  "$PG_BIN/pg_ctl" -D "$PGDATA" -l "$LOG_FILE" -w \
    -o "-p $DB_PORT -c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp" start
fi

export PGPASSWORD="$DB_ADMIN_PASSWORD"
PSQL=("$PG_BIN/psql" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_ADMIN_USER" -v ON_ERROR_STOP=1 -tA)

# Escape a value for use inside a single-quoted SQL string literal.
sql_literal() { printf '%s' "${1//\'/\'\'}"; }

# 1. Roles (cluster-level). Created if missing; passwords are re-synced on every run
#    so a rotated secret in the environment takes effect.
for spec in "$DB_MIGRATION_USER:$DB_MIGRATION_PASSWORD" "$DB_APP_USER:$DB_APP_PASSWORD"; do
  role="${spec%%:*}"
  pw="$(sql_literal "${spec#*:}")"
  if [ "$("${PSQL[@]}" -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname='$role'")" != "1" ]; then
    "${PSQL[@]}" -d postgres -c "CREATE ROLE \"$role\" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '$pw'"
  else
    "${PSQL[@]}" -d postgres -c "ALTER ROLE \"$role\" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '$pw'"
  fi
done

# 2. Application database, owned by the migration role.
if [ "$("${PSQL[@]}" -d postgres -c "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" != "1" ]; then
  "${PSQL[@]}" -d postgres -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_MIGRATION_USER\""
else
  "${PSQL[@]}" -d postgres -c "ALTER DATABASE \"$DB_NAME\" OWNER TO \"$DB_MIGRATION_USER\""
fi

# 3. Privileges (all statements are idempotent). The default-privilege rules apply to
#    objects the migration role creates later, so no per-table grants are needed.
#    DELETE is deliberately never granted to the runtime role, which protects the
#    append-only tables (audit_logs, work_order_status_history, health_score_history,
#    alerts). Migrations may also REVOKE UPDATE on those tables.
"${PSQL[@]}" -d "$DB_NAME" -q <<SQL
REVOKE ALL ON DATABASE "$DB_NAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE "$DB_NAME" TO "$DB_APP_USER";
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE "$DB_NAME" TO "$DB_MIGRATION_USER";
ALTER SCHEMA public OWNER TO "$DB_MIGRATION_USER";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM "$DB_APP_USER";
GRANT USAGE ON SCHEMA public TO "$DB_APP_USER";
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "$DB_APP_USER";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "$DB_APP_USER";
ALTER DEFAULT PRIVILEGES FOR ROLE "$DB_MIGRATION_USER" IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO "$DB_APP_USER";
ALTER DEFAULT PRIVILEGES FOR ROLE "$DB_MIGRATION_USER" IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "$DB_APP_USER";
SQL

# 4. Publish connection settings (git-ignored). Real deployments must supply these
#    values from environment or secret storage. Passwords are URL-encoded.
urlenc() { python3 -c 'import sys,urllib.parse as u; print(u.quote(sys.argv[1], safe=""))' "$1"; }
MIG_URL="postgresql+psycopg://$DB_MIGRATION_USER:$(urlenc "$DB_MIGRATION_PASSWORD")@$DB_HOST:$DB_PORT/$DB_NAME"
APP_URL="postgresql+psycopg://$DB_APP_USER:$(urlenc "$DB_APP_PASSWORD")@$DB_HOST:$DB_PORT/$DB_NAME"
umask 077
{
  echo "MIGRATION_DATABASE_URL=$MIG_URL"
  echo "DATABASE_URL=$APP_URL"
} > "$HERE/database_urls.env"
echo "psql postgresql://$DB_ADMIN_USER:$DB_ADMIN_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME" > "$HERE/db_connection.txt"
echo "PostgreSQL ready: database '$DB_NAME' on $DB_HOST:$DB_PORT with roles '$DB_MIGRATION_USER' (DDL) and '$DB_APP_USER' (DML, no DELETE)."
echo "Backend settings written to database_urls.env (MIGRATION_DATABASE_URL, DATABASE_URL); admin connection saved to db_connection.txt"
