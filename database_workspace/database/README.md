# Database (PostgreSQL 16)

PostgreSQL container for the Infrastructure Asset Health & Predictive Maintenance Tracker
(STEP-01 scaffold, STEP-02 roles).

- Start (idempotent): `./startup.sh` - initialises the cluster on first run, starts the server on port 5432,
  creates the application database `asset_health`, provisions the roles below, and writes `db_connection.txt`
  and `database_urls.env` (both git-ignored).
- Stop: `./stop.sh`
- Readiness: `pg_isready -h localhost -p 5432`
- Admin connect: `$(cat db_connection.txt)`

## Roles and privileges (AC-17)

| Role (default name) | Purpose | Privileges |
| --- | --- | --- |
| `appadmin` (`DB_ADMIN_USER`) | Cluster superuser, used only by `startup.sh` | Superuser |
| `asset_migrator` (`DB_MIGRATION_USER`) | Owns database `asset_health` and schema `public`; Alembic runs as this role | DDL and all privileges on its own objects; not a superuser |
| `asset_app` (`DB_APP_USER`) | API and worker runtime | `CONNECT`, `USAGE` on `public`; `SELECT, INSERT, UPDATE` on tables and `USAGE, SELECT` on sequences that the migration role creates (via `ALTER DEFAULT PRIVILEGES`); no `CREATE`, no `DELETE` |

`DELETE` is never granted to the runtime role, which protects the append-only tables `audit_logs`,
`work_order_status_history`, `health_score_history`, and `alerts`. A migration that needs row deletion on a
specific non-history table must grant it explicitly; migrations may also `REVOKE UPDATE` on the history tables.
`PUBLIC` has no privileges on the database or schema. Role creation, grants, and default privileges are
idempotent, and role passwords are re-synced from the environment on each run.

## Backend settings

`startup.sh` writes `database_urls.env` containing:

- `MIGRATION_DATABASE_URL` - migration role URL used by `alembic upgrade head` (STEP-03).
- `DATABASE_URL` - runtime role URL used by the API and worker.

Format: `postgresql+psycopg://<user>:<url-encoded password>@localhost:5432/asset_health`. Values in this
repository are development-only defaults; real credentials are supplied at deploy time from environment or
secret storage (override via `DB_*_USER` / `DB_*_PASSWORD`) and are never committed. Names and defaults are
listed in `.env.example`.

## Data directory

The cluster lives in `~/.local/share/asset-health-postgres/pgdata` (override with `PGDATA`), deliberately
outside the workspace: the platform resets workspace file modes to 0777 within seconds, and PostgreSQL refuses
to start on a data directory that is not 0700/0750. `startup.sh` also re-applies `chmod 0700` before starting.
The data is development-only and is not part of the repository.

The user approved the workspace PostgreSQL 16 server (no local installation needed) in place of the original
PostgreSQL 15 target. Schema DDL belongs to the backend (Alembic migrations, STEP-03).
