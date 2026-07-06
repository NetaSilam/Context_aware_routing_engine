#!/bin/sh
# Runs automatically on first container init (empty data dir) via
# docker-entrypoint-initdb.d. Restores the foundation project's exported
# PostGIS dump so the app has real road/accident data with zero manual steps.
set -e

SEED_DUMP="/seed/road_risk_mapper.dump"

if [ -f "$SEED_DUMP" ]; then
  echo "Restoring seed data from $SEED_DUMP ..."
  pg_restore --no-owner --role="$POSTGRES_USER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$SEED_DUMP"
  echo "Seed restore complete."
else
  echo "No seed dump found at $SEED_DUMP - starting with an empty schema."
  echo "Export it from the foundation pipeline repo with:"
  echo "  pg_dump -Fc -U <user> -d <db> -f road_risk_mapper.dump"
  echo "and place it at db/seed/road_risk_mapper.dump before running for real data."
fi
