#!/usr/bin/env bash
set -euo pipefail

base_project="road-risk-validation-${USER:-runner}-$$"
services=(
  unit-tests frontend-tests foundation-tests risk-data-tests corridor-matcher-tests
  osrm-contract-tests route-job-tests route-history-tests geocoding-tests auth-tests
  forum-tests forum-seed-tests messages-tests notifications-tests abuse-tests forum-abuse-tests gateway-tests e2e-tests stress-tests
)

run_service() {
  local service="$1"
  local project="${base_project}-${service}"
  local compose=(docker compose --project-name "$project" --env-file .env.test -f compose.yaml -f compose.test.yaml)
  if [[ "$service" == "stress-tests" ]]; then compose+=(--profile stress); fi

  cleanup_service() { "${compose[@]}" down --volumes --remove-orphans; }
  trap cleanup_service RETURN
  "${compose[@]}" up --build --wait --scale worker=2 postgres redis fake-osrm fake-geocoder api worker frontend abuse-api stress-api secure-auth-api auth-unavailable-api geocoding-unavailable-api queue-unavailable-api
  "${compose[@]}" run --rm --no-deps "$service"
  trap - RETURN
  cleanup_service
}

for service in "${services[@]}"; do run_service "$service"; done
