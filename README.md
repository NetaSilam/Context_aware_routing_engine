# Context-Aware Safe Routing Engine

Backend navigation microservice that ranks driving routes by balancing travel
time against historical road-accident risk, personalized to the user's
profile and preferences. Built for Software Engineering for ML (Spring 2026).

See [`PROJECT_REQUIREMENTS.md`](PROJECT_REQUIREMENTS.md) for the full spec,
architecture, and TODO list.

For team onboarding, start with the [project codebase map](docs/CODEBASE_MAP.md) and the
[documentation guide](docs/DOCUMENTATION_GUIDE.md). The guide identifies which documents are
current evidence and which are historical planning material.

## Development foundation

The route page is currently an asynchronous-job UI shell. The supporting
foundation is now reproducible: Alembic owns the application schema, a one-shot
initializer verifies foundation-data identity, and Compose starts PostGIS,
Redis, FastAPI, workers, and the compiled React application behind Nginx in
dependency order.

The initializer also builds an immutable `RISK_DATA_VERSION` from the prepared
corridors and accident attributions. It reports source and output counts,
confidence-tier counts, the full included year range, refresh duration, storage
use, and the length-weighted risk p95. A validated version is activated
transactionally; a failed refresh leaves the prior version active. Run a new
national-data refresh as an initialization/maintenance operation, never from a
public route request.

The verified full-data row counts, p95, duration, and storage measurement are
recorded in [`docs/RISK_DATA_REFRESH_REPORT.md`](docs/RISK_DATA_REFRESH_REPORT.md).

Copy `.env.example` to `.env`, replace every placeholder, then run:

```sh
docker compose up --build
```

`FOUNDATION_DATA_MODE=fixture` loads the small committed explorer fixture. For
an existing national dataset, use `FOUNDATION_DATA_MODE=verify`, provide its
version and checksum, and ensure the required foundation tables are already
present. Initialization refuses stale checksums, changed row counts, partial
tables, or missing tables.

Only the Nginx frontend gateway publishes a host port. PostgreSQL, Redis, OSRM,
initialization, workers, and FastAPI communicate only on the Compose network.
Redis uses append-only storage;
PostgreSQL and Redis both use persistent named volumes.

For local frontend development, run `npm run dev` in `frontend/`; Vite remains a
development-only server. The deployed Compose gateway serves the production build
on `FRONTEND_PORT` (default `8080`). Scale route workers without assigning a
container name:

```sh
docker compose up --build --scale worker=2
```

The prepared data exports are documented in `data/README.md`. They are no
longer loaded by FastAPI startup code.

The canonical-network and accident-attribution explorer pages and read APIs
remain in the repository during the routing rebuild.

## Running the tests

```
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m pytest -q -m "not integration" backend/tests

docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm frontend-tests
```

The clean-container foundation test uses only the committed SQL fixture:

```sh
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml \
  up --build --abort-on-container-exit --exit-code-from foundation-tests foundation-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml \
  up --build --abort-on-container-exit --exit-code-from risk-data-tests risk-data-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml down -v
```

The complete clean-machine grading validation, category commands, feature-to-test matrix,
performance evidence, and current verified deferrals are in
[`docs/GRADING_VALIDATION.md`](docs/GRADING_VALIDATION.md).
