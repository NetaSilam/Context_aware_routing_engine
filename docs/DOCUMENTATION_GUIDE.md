# Documentation guide

This file explains what the repository documentation is for and which documents should be
treated as current. When documentation conflicts with the code, the current code and its tests
win.

## Recommended reading order

1. [`../README.md`](../README.md) — setup and the shortest project overview.
2. [`CODEBASE_MAP.md`](CODEBASE_MAP.md) — current source-tree ownership and runtime flow.
3. [`../data/README.md`](../data/README.md) — prepared data contents and exclusions.
4. [`LOCAL_SETUP_AND_OPERATIONS.md`](LOCAL_SETUP_AND_OPERATIONS.md) — local startup, shutdown, reset, and test commands.
5. [`ROUTING_FEATURE_PRD.md`](ROUTING_FEATURE_PRD.md) and [`FORUM_FEATURE_PRD.md`](FORUM_FEATURE_PRD.md) — the authoritative design record for each feature vertical.
6. The focused evidence document for the feature you are changing.

## `docs/` inventory

| Document | What it contains | Status | Team guidance |
| --- | --- | --- | --- |
| `CODEBASE_MAP.md` | Current code ownership, runtime/data flow, and change locations | Current | Start here when navigating the code |
| `DOCUMENTATION_GUIDE.md` | This inventory and source-of-truth policy | Current | Update when docs are added, removed, or reclassified |
| `LOCAL_SETUP_AND_OPERATIONS.md` | Local real-data, fixture-mode, and diagnostic commands | Current operational reference | Use for day-to-day local operations |
| `ROUTING_FEATURE_PRD.md` | Problem statement, solution, user stories, implementation/testing decisions, and out-of-scope items for the routing vertical | Current design record | Read before changing routing, scoring, jobs, or OSRM/matcher behavior |
| `route-risk-calculation-tickets.md` | Ordered, blocked-by ticket breakdown implementing the routing PRD | Current design record | Use to see routing implementation sequencing and per-ticket acceptance criteria |
| `FORUM_FEATURE_PRD.md` | Problem statement, solution, user stories, implementation/testing decisions, and out-of-scope items for the forum/DM/notifications vertical | Current design record | Read before changing forum, messaging, or notification behavior |
| `forum-feature-tickets.md` | Ordered, blocked-by ticket breakdown implementing the forum PRD | Current design record | Use to see forum implementation sequencing and per-ticket acceptance criteria |
| `assets/corridor-matcher-overlays/*.svg` | Visual overlays generated/reviewed for matcher benchmark cases | Supporting evidence | Keep with the benchmark; not standalone product documentation |

## What is necessary today

For normal onboarding and development, the necessary documentation set is:

- root `README.md`
- `CODEBASE_MAP.md`
- `data/README.md`
- `osrm/README.md` when working with the routing graph
- `LOCAL_SETUP_AND_OPERATIONS.md` for day-to-day local operations
- `ROUTING_FEATURE_PRD.md` and `route-risk-calculation-tickets.md` when working on routing
- `FORUM_FEATURE_PRD.md` and `forum-feature-tickets.md` when working on the forum

## Known documentation drift

`PROJECT_REQUIREMENTS.md` contains older status statements and TODOs from earlier project phases.
It remains useful for course scope, but it is not the current implementation inventory.

Commit `c9ad7f6` ("Clean up project documentation") deleted `GRADING_VALIDATION.md`,
`CORRIDOR_MATCHER_BENCHMARK.md`, `RISK_DATA_REFRESH_REPORT.md`, `ROUTING_TEST_EXECUTION_NOTES.md`,
and `ROUTING_ARCHITECTURE_DECISIONS.md`, and added `LOCAL_SETUP_AND_OPERATIONS.md`, but this
inventory still listed the deleted files as "Current" until this revision. If test-suite
evidence, matcher-benchmark results, or a risk-data refresh report are needed again, they must be
regenerated and re-added as new documents — do not assume their old content still applies without
checking the current code and tests.

## Suggested maintenance rule

When behavior changes, update documentation in this order:

1. Code and tests.
2. `README.md` for setup or user-visible runtime changes.
3. `CODEBASE_MAP.md` for ownership or data-flow changes.
4. `GRADING_VALIDATION.md` for test commands, evidence, or limitations.
5. The focused benchmark or report.
6. This inventory if the document's purpose or status changes.

Keep this guide aligned with the files that remain in the active documentation set. Remove an
entry when its document is deleted or archived, and add an entry when a new current document is
introduced.
