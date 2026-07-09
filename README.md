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

- **App: http://localhost:5173** - a React/Leaflet map viewer with two pages
  (Canonical Network, Accident Attribution), ported from the foundation
  project. This is the only container exposed to the host; the API is
  reachable only from the frontend container over the compose network.
- The backend API (`/health`, `/health/db`, `/api/canonical-network/*`,
  `/api/accident-attribution/*`) is not published to the host on purpose -
  only `frontend` talks to it directly, matching the course's "only the web
  container is exposed to clients" requirement. To hit it directly for
  debugging, temporarily add a `ports:` mapping to the `web` service.
- On first startup, the `web` container loads `data/*.parquet`/`*.geoparquet`
  into PostGIS (schemas `foundation_data`, `canonical_network`,
  `accident_attribution`) if those tables are empty. Subsequent restarts skip
  seeding since the tables are already populated. Verified locally: all 8
  tables load with real row counts (49,941 accidents, 362,922 corridors, etc.),
  and the frontend renders real data through the proxy end-to-end.
- Dropped from the port: the foundation project's Traffic Coverage page/API -
  no traffic-count data is in this export (see `data/README.md`).

## Running the tests

```
cd backend
pip install -r requirements.txt
pytest

cd ../frontend
npm install
npm test        # vitest - 4 suites, 9 tests, all passing as of this port
npm run build   # tsc typecheck + production build
```
