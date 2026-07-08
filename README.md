# Context-Aware Safe Routing Engine

Backend navigation microservice that ranks driving routes by balancing travel
time against historical road-accident risk, personalized to the user's
profile and preferences. Built for Software Engineering for ML (Spring 2026).

See [`PROJECT_REQUIREMENTS.md`](PROJECT_REQUIREMENTS.md) for the full spec,
architecture, and TODO list.

## Status

Early scaffold. The accident/road-corridor data pipeline was built in a
separate foundation project (see `data/README.md` for what each file is);
its parquet/geoparquet exports go in `data/` and are loaded into PostGIS
automatically on first startup by `backend/app/seed.py`. **The data files
themselves aren't committed yet** (see `data/README.md` and the team for how
to get them) - `.gitignore` excludes `data/*.parquet`/`*.geoparquet` for now;
without them the app still boots, it just has no rows in `foundation_data`,
`canonical_network`, or `accident_attribution`.

## Running the app

```
cp .env.example .env
# Place the foundation pipeline's exports in data/ (see data/README.md) first.
docker compose up --build
```

- API: http://localhost:8000 (`/health`, `/health/db`)
- On first startup, the `web` container loads `data/*.parquet`/`*.geoparquet`
  into PostGIS (schemas `foundation_data`, `canonical_network`,
  `accident_attribution`) if those tables are empty. Subsequent restarts skip
  seeding since the tables are already populated. Verified locally: all 8
  tables load with real row counts (49,941 accidents, 362,922 corridors, etc.).

## Running the tests

```
cd backend
pip install -r requirements.txt
pytest
```
