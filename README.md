# Context-Aware Safe Routing Engine

Backend navigation microservice that ranks driving routes by balancing travel
time against historical road-accident risk, personalized to the user's
profile and preferences. Built for Software Engineering for ML (Spring 2026).

See [`PROJECT_REQUIREMENTS.md`](PROJECT_REQUIREMENTS.md) for the full spec,
architecture, and TODO list.

## Status

Early scaffold. The accident/road-corridor data pipeline was built in a
separate foundation project — see `db/seed/README.md` for how its output gets
loaded into this project's database.

## Running the app

```
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000 (`/health`, `/health/db`)
- The `postgis` service restores `db/seed/road_risk_mapper.dump` automatically
  on first start if present (see `db/seed/README.md`).

## Running the tests

```
cd backend
pip install -r requirements.txt
pytest
```
