# Documentation guide

This file explains what the repository documentation is for and which documents should be
treated as current. When documentation conflicts with the code, the current code and its tests
win.

## Recommended reading order

1. [`../README.md`](../README.md) — setup and the shortest project overview.
2. [`CODEBASE_MAP.md`](CODEBASE_MAP.md) — current source-tree ownership and runtime flow.
3. [`../data/README.md`](../data/README.md) — prepared data contents and exclusions.
4. [`LOCAL_SETUP_AND_OPERATIONS.md`](LOCAL_SETUP_AND_OPERATIONS.md) — local startup, shutdown, reset, and test commands.
5. [`GRADING_VALIDATION.md`](GRADING_VALIDATION.md) — test suites, commands, evidence, and limits.
6. The focused evidence document for the feature you are changing.

## `docs/` inventory

| Document | What it contains | Status | Team guidance |
| --- | --- | --- | --- |
| `CODEBASE_MAP.md` | Current code ownership, runtime/data flow, and change locations | Current | Start here when navigating the code |
| `DOCUMENTATION_GUIDE.md` | This inventory and source-of-truth policy | Current | Update when docs are added, removed, or reclassified |
| `LOCAL_SETUP_AND_OPERATIONS.md` | Local real-data, fixture-mode, and diagnostic commands | Current operational reference | Use for day-to-day local operations |
| `GRADING_VALIDATION.md` | Complete Compose validation runner, category commands, feature/test matrix, setup, and known limitations | Current operational reference | Use it for test claims and clean-machine validation |
| `CORRIDOR_MATCHER_BENCHMARK.md` | Matcher decision, reproducible inputs, benchmark results, accuracy/stability checks, and visual evidence | Current technical evidence | Use it when changing matcher behavior or performance assumptions |
| `RISK_DATA_REFRESH_REPORT.md` | Measured national risk-data refresh for `national-risk-2026-08-01` | Current immutable evidence snapshot | Use it as evidence for that version; create a new report for a new refresh |
| `ROUTING_TEST_EXECUTION_NOTES.md` | Dated test exceptions and unresolved verification deferrals | Current exception log | Read before claiming all route/deployment evidence is complete |
| `assets/corridor-matcher-overlays/*.svg` | Visual overlays generated/reviewed for matcher benchmark cases | Supporting evidence | Keep with the benchmark; not standalone product documentation |

## What is necessary today

For normal onboarding and development, the necessary documentation set is:

- root `README.md`
- `CODEBASE_MAP.md`
- `data/README.md`
- `osrm/README.md` when working with the routing graph
- `LOCAL_SETUP_AND_OPERATIONS.md` for day-to-day local operations
- `GRADING_VALIDATION.md` when running or reporting tests
- `CORRIDOR_MATCHER_BENCHMARK.md` when working on spatial matching
- `RISK_DATA_REFRESH_REPORT.md` when working on risk data
- `ROUTING_TEST_EXECUTION_NOTES.md` before reporting final verification status

## Known documentation drift

`PROJECT_REQUIREMENTS.md` contains older status statements and TODOs from earlier project phases.
It remains useful for course scope, but it is not the current implementation inventory.

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
