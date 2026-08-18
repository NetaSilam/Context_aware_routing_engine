# Sa Bracha — Context-Aware Safe Routing Engine

Sa Bracha ("סע ברכה") is a full-stack driving-safety platform, not just a routing algorithm:
it ranks candidate routes by balancing travel time against historical accident risk, guides
drivers live with turn-by-turn navigation and automatic rerouting, and lets the community
report and discuss road hazards in a moderated forum — all personalized to each driver's
profile. Built for Software Engineering for ML (Spring 2026).

**Live deployment:** http://sweng-group-14.eastus.cloudapp.azure.com/ (the Azure VM must be
powered on; see [Deploying to Azure](#deploying-to-azure) below).

## Features

- **Risk-aware route planning.** An authenticated user submits an origin and destination (by
  address search, map click, or numeric coordinates); a background worker requests up to three
  OSRM candidates, scores each against precomputed historical accident-density corridors, and
  ranks them by a combined safety/time cost. Every input to the ranking — raw metrics,
  normalized values, weights, and an AI-generated explanation of the pick — is shown to the
  user, not just the final answer.
- **Personalized safety weighting.** The safety weight is derived automatically from driving
  experience, vehicle type, and time of day, then scaled by an explicit user preference (Low /
  Balanced / High — how much *they* personally weigh safety vs. time), set at signup or in
  profile preferences. See the "Safety Preference Extension" section of
  [`docs/ROUTING_FEATURE_PRD.md`](docs/ROUTING_FEATURE_PRD.md).
- **Live turn-by-turn navigation.** Starting navigation on a chosen route hands off to a
  full-screen driving view with voice and text guidance, automatic off-route detection and
  rerouting (scored with the same weighting as the original plan), and nearby hazard-report
  alerts — see the "Live Navigation Extension" section of the same PRD.
- **Community hazard forum.** Drivers report potholes, flooding, broken signals, and other
  hazards with photos, discuss them in comments, and vote. Every report is automatically
  triaged by an LLM for severity and checked for near-duplicates against nearby/recent reports,
  clearly labeled as AI-generated and never presented as verified fact — see
  [`docs/FORUM_FEATURE_PRD.md`](docs/FORUM_FEATURE_PRD.md) and
  [`docs/LLM_FEATURE_PRD.md`](docs/LLM_FEATURE_PRD.md).
- **Accident-attribution and canonical-network explorers.** Read-only pages for inspecting the
  underlying prepared accident and road-network data the risk scoring is built on.

See [`PROJECT_REQUIREMENTS.md`](PROJECT_REQUIREMENTS.md) for the full spec, architecture, and
TODO list.

For team onboarding, start with the [project codebase map](docs/CODEBASE_MAP.md) and the
[documentation guide](docs/DOCUMENTATION_GUIDE.md). The guide identifies which documents are
current evidence and which are historical planning material.

For day-to-day local startup, shutdown, reset, and test commands, see
[`docs/LOCAL_SETUP_AND_OPERATIONS.md`](docs/LOCAL_SETUP_AND_OPERATIONS.md).

## Architecture

Alembic owns the application schema, a one-shot initializer verifies foundation-data identity
and builds the derived risk dataset, and Compose starts PostGIS, Redis, self-hosted OSRM,
FastAPI, Celery workers (route scoring and LLM triage/dedup/explanation, on physically separate
queues), and the compiled React application behind Nginx, in dependency order. Only the Nginx
gateway publishes a host port — PostgreSQL, Redis, OSRM, and FastAPI communicate only on the
Compose network.

The initializer builds an immutable `RISK_DATA_VERSION` from the prepared corridors and accident
attributions. It reports source and output counts, confidence-tier counts, the full included
year range, refresh duration, storage use, and the length-weighted risk p95. A validated version
is activated transactionally; a failed refresh leaves the prior version active. Run a new
national-data refresh as an initialization/maintenance operation, never from a public route
request. The verified full-data row counts, p95, duration, and storage measurement are recorded
in [`docs/RISK_DATA_REFRESH_REPORT.md`](docs/RISK_DATA_REFRESH_REPORT.md).

## Running it locally

Copy `.env.example` to `.env`, replace every placeholder, then run:

```sh
docker compose up --build
```

`FOUNDATION_DATA_MODE=fixture` loads the small committed explorer fixture. For an existing
national dataset, use `FOUNDATION_DATA_MODE=verify`, provide its version and checksum, and
ensure the required foundation tables are already present. Initialization refuses stale
checksums, changed row counts, partial tables, or missing tables.

For the prepared real-data artifacts committed under `data/`, copy `.env.real.example` to
`.env.real` and replace the local secret placeholders (including an LLM provider key —
`GEMINI_API_KEY` by default):

```sh
docker compose --env-file .env.real up --build
```

The one-shot initializer loads the four canonical/attribution Parquet files, verifies their
manifest checksum and database row counts, then builds and activates the active risk-data
version. The data directory is mounted read-only only into the initializer; API and worker
containers use the PostGIS tables. The template also uses a separate Compose project name, so
its Postgres and Redis volumes are isolated from the test stack.

For local frontend development, run `npm run dev` in `frontend/`; Vite remains a
development-only server. The deployed Compose gateway serves the production build on
`FRONTEND_PORT` (default `8080`). Scale route workers without assigning a container name:

```sh
docker compose up --build --scale worker=2
```

The prepared data exports are documented in `data/README.md`. They are loaded by the one-shot
initializer in real mode, not by FastAPI startup code.

## Running the tests

```sh
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
[`docs/GRADING_VALIDATION.md`](docs/GRADING_VALIDATION.md). The same suite runs automatically
on every push via `.github/workflows/grading-validation.yml`.

## Deploying to Azure

The production site runs as the same Compose stack (`--env-file .env.real`) on a single Azure
VM, fronted by Nginx on port 80. To deploy the current `master` (or any branch):

1. Make sure the VM is powered on (Azure Portal).
2. From the repository's **Actions** tab, run the **deploy** workflow (`workflow_dispatch`) —
   any collaborator can trigger it. It pulls the selected branch onto the VM, rebuilds and
   restarts the stack, and fails the run if the site or its `/api` proxy doesn't come back
   healthy within about three minutes.

The workflow (`.github/workflows/deploy.yml`) authenticates over SSH with a dedicated,
read-only-scoped deploy key (distinct from any collaborator's personal key) and reconstructs
`.env.real` from GitHub repository secrets on each run, so the VM's production configuration
has a source of truth outside the VM itself. Docker Compose's `restart: unless-stopped` policy
brings the whole stack back automatically after a VM reboot — no manual steps needed beyond
powering the VM back on.
