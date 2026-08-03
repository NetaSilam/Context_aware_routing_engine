# Documentation guide

This file explains what the repository documentation is for and which documents should be
treated as current. When a document conflicts with the code, the current code and its tests win;
this guide records the conflict so it is visible to the team.

## Recommended reading order

1. [`../README.md`](../README.md) — setup and the shortest project overview.
2. [`CODEBASE_MAP.md`](CODEBASE_MAP.md) — current source-tree ownership and runtime flow.
3. [`../data/README.md`](../data/README.md) — prepared data contents and exclusions.
4. [`GRADING_VALIDATION.md`](GRADING_VALIDATION.md) — test suites, commands, evidence, and limits.
5. The focused evidence or design document for the feature you are changing.

## `docs/` inventory

| Document | What it contains | Status | Team guidance |
| --- | --- | --- | --- |
| `CODEBASE_MAP.md` | Current code ownership, runtime/data flow, and change locations | Current | Start here when navigating the code |
| `DOCUMENTATION_GUIDE.md` | This inventory and source-of-truth policy | Current | Update when docs are added, removed, or reclassified |
| `GRADING_VALIDATION.md` | Complete Compose validation runner, category commands, feature/test matrix, setup, and known limitations | Current operational reference | Use it for test claims and clean-machine validation |
| `CORRIDOR_MATCHER_BENCHMARK.md` | Matcher decision, reproducible inputs, benchmark results, accuracy/stability checks, and visual evidence | Current technical evidence | Use it when changing matcher behavior or performance assumptions |
| `RISK_DATA_REFRESH_REPORT.md` | Measured national risk-data refresh for `national-risk-2026-08-01` | Current immutable evidence snapshot | Use it as evidence for that version; create a new report for a new refresh |
| `ROUTING_TEST_EXECUTION_NOTES.md` | Dated test exceptions and unresolved verification deferrals | Current exception log | Read before claiming all route/deployment evidence is complete |
| `ROUTING_ARCHITECTURE_DECISIONS.md` | Design rationale, rejected alternatives, boundaries, and implementation order | Historical / partially stale | Useful for why decisions were made; do not use its “current implementation” statements as a code map |
| `ROUTING_FEATURE_PRD.md` | Detailed route-risk product requirements, user stories, contracts, and test decisions | Historical specification / partially stale | Use for intended behavior and grading scope; verify every requirement against code/tests |
| `route-risk-calculation-tickets.md` | Ordered implementation tickets for the routing rebuild | Historical backlog / stale statuses | Useful for traceability; its repeated `ready-for-agent` statuses are not the current task board |
| `assets/corridor-matcher-overlays/*.svg` | Visual overlays generated/reviewed for matcher benchmark cases | Supporting evidence | Keep with the benchmark; not standalone product documentation |

## What is necessary today

For normal onboarding and development, the necessary documentation set is:

- root `README.md`
- `CODEBASE_MAP.md`
- `data/README.md`
- `osrm/README.md` when working with the routing graph
- `GRADING_VALIDATION.md` when running or reporting tests
- `CORRIDOR_MATCHER_BENCHMARK.md` when working on spatial matching
- `RISK_DATA_REFRESH_REPORT.md` when working on risk data
- `ROUTING_TEST_EXECUTION_NOTES.md` before reporting final verification status

The architecture, PRD, and ticket documents are not needed to understand the current code path,
but they should not be deleted yet: they preserve the original requirements, trade-offs, and
implementation history. They need a future cleanup pass if the team wants one authoritative
requirements document instead of historical planning material.

## Known documentation drift

These statements in older documents should not be copied into new code or reports without checking
the repository:

- `ROUTING_ARCHITECTURE_DECISIONS.md` says the current routing backend/frontend are still a proof
  of concept and that key boundaries still need implementation. The current repository has the
  asynchronous route-job path, Celery worker, risk matcher, scoring service, route history, and
  validation suites described in `CODEBASE_MAP.md`.
- `ROUTING_FEATURE_PRD.md` opens by describing synchronous routing as the current state. That is
  historical context, not the current route-job implementation.
- `route-risk-calculation-tickets.md` labels completed implementation tickets as `ready-for-agent`.
  Treat it as a historical sequence, not as an active backlog.
- `PROJECT_REQUIREMENTS.md` contains several older status statements and TODOs from earlier
  project phases. It remains useful for course scope, but it is not the current implementation
  inventory.

## Suggested maintenance rule

When behavior changes, update documentation in this order:

1. Code and tests.
2. `README.md` for setup or user-visible runtime changes.
3. `CODEBASE_MAP.md` for ownership or data-flow changes.
4. `GRADING_VALIDATION.md` for test commands, evidence, or limitations.
5. The focused benchmark/report/decision document.
6. This inventory if the document's purpose or status changes.

Do not delete old planning documents solely because they contain historical text. Either add a
dated status note, update them to match the implementation, or explicitly move them to an archive
directory in a separate cleanup change.
