#!/bin/bash
# Runs ONCE when the local PostgreSQL container is first created (mounted into /docker-entrypoint-initdb.d).
# Creates: one database per service, one app login and one migrator login per database.
#
# Why: the boundary between services is physical. identity_app can connect to identity and nothing else,
# so no service can query another service's data even by accident.
#
#   <svc>_migrator  owns the database; Alembic connects as this to change the schema
#   <svc>_app       what the running service uses; member of app_user, so forced RLS applies to it
#
# The roles app_user / app_worker / app_migrator are created by each service's baseline migration
# (tools/db-split/_epilogue.sql). We create them here too, so the logins can be granted into them first.
set -euo pipefail

SERVICES="identity access hierarchy tasks time"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user')     THEN CREATE ROLE app_user NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker')   THEN CREATE ROLE app_worker NOLOGIN BYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_migrator') THEN CREATE ROLE app_migrator NOLOGIN; END IF;
END \$\$;
SQL

for svc in $SERVICES; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE ${svc}_migrator LOGIN PASSWORD '${DB_MIGRATOR_PASSWORD}' IN ROLE app_migrator;
CREATE ROLE ${svc}_app      LOGIN PASSWORD '${DB_APP_PASSWORD}'      IN ROLE app_user;
CREATE DATABASE ${svc} OWNER ${svc}_migrator;
REVOKE ALL ON DATABASE ${svc} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${svc} TO ${svc}_app, ${svc}_migrator;
SQL
done
