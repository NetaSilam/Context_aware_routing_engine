# Local Operations

Run commands from the repository root. Docker Desktop must be running.

## Option 1: Run the application with real data

Required files under `data/`:

```text
canonical_corridors.geoparquet
official_segment_links.parquet
accident_attributions.geoparquet
accident_attribution_summary.parquet
```

Create the local environment once:

```sh
cp .env.real.example .env.real
```

Edit `.env.real` and replace the database password, JWT secret, and geocoder user agent.
These values are local-only and must not be committed.

Start the app:

```sh
docker compose --env-file .env.real up --build --detach
docker compose --env-file .env.real ps
```

Open [http://localhost:8080](http://localhost:8080). On the first run, the initializer loads
the four files, verifies the checksum and row counts, builds the active risk version, and
cold-seeds forum demo data (6 seed accounts, 9 historical hazard reports, comments, and votes).
Later runs reuse and revalidate the existing database; re-seeding is idempotent and never
duplicates content.

Check internal readiness:

```sh
docker compose --env-file .env.real exec -T api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
```

Stop the app without deleting data:

```sh
docker compose --env-file .env.real down
```

Reset the local real database and reload everything:

```sh
docker compose --env-file .env.real down --volumes
docker compose --env-file .env.real up --build --detach
```

The reset command deletes the local Postgres and Redis volumes. The Parquet files under
`data/` are not deleted.

## Option 2: Run fixture/test mode

This mode uses the committed SQL fixture and fake upstream services. It is intended for
automated validation, not national-data exploration.

Run the complete validation package:

```sh
./scripts/run_grading_validation.sh
```

Run one category, for example foundation or risk refresh:

```sh
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml \
  run --rm foundation-tests

docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml \
  run --rm risk-data-tests
```

Clean test containers and volumes afterward when needed:

```sh
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml down --volumes
```

## Option 3: Verify an externally provisioned database

Set `FOUNDATION_DATA_MODE=verify` and provide `FOUNDATION_DATA_VERSION` and
`FOUNDATION_DATA_CHECKSUM` in an environment file. Then run the normal Compose command:

```sh
docker compose --env-file .env up --build --detach
```

`verify` does not load files. Use `real` for a new local database populated from `data/`.

## Useful diagnostics

```sh
docker compose --env-file .env.real logs -f initialize
docker compose --env-file .env.real logs -f api
docker compose --env-file .env.real ps
```

The real mode also requires the prepared OSRM graph under `osrm/data/`; the foundation loader
does not create that graph.
