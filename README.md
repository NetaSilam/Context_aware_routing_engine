# Context-Aware Safe Routing Engine

Backend navigation microservice that ranks driving routes by balancing travel
time against historical road-accident risk, personalized to the user's
profile and preferences. Built for Software Engineering for ML (Spring 2026).

See [`PROJECT_REQUIREMENTS.md`](PROJECT_REQUIREMENTS.md) for the full spec,
architecture, and TODO list.

## Status

The obsolete synchronous routing prototype has been removed. The route page is
currently an asynchronous-job UI shell only.

This is a temporary post-cleanup milestone, not the final runnable deployment.
Database migrations, deterministic initialization, PostGIS, Redis, and new
Compose wiring are restored by the next implementation ticket. Until then,
there is intentionally no supported full-stack startup command.

The prepared data exports are documented in `data/README.md`. They are no
longer loaded by FastAPI startup code.

The canonical-network and accident-attribution explorer pages and read APIs
remain in the repository during the routing rebuild.

## Running the tests

```
cd backend
pip install -r requirements.txt
pytest

cd ../frontend
npm install
npm test
npm run build   # tsc typecheck + production build
```
