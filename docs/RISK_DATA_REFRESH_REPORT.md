# National corridor-risk refresh report

Measured on 2026-08-01 against the prepared artifacts committed under `data/`.
The refresh ran in an isolated Docker Compose PostgreSQL/PostGIS database; it
was not invoked through a public application request.

## Environment

- Host: Apple arm64, macOS 26.5.2 (build 25F84)
- Docker Desktop: client/server 29.6.2, arm64 Linux VM
- Database image: `postgis/postgis:16-3.4` (amd64 emulation on this host)
- Application image: Python 3.12 slim
- Risk schema version: `corridor-risk-v1`
- Risk data version: `national-risk-2026-08-01`
- Combined SHA-256 identity for the four loaded foundation artifacts:
  `c3d6e0eeec723a139917f19a53cca2ee2ab7701aa1e75578870d52b10eb9a45c`

## Refresh result

| Measurement | Result |
| --- | ---: |
| Input corridors | 362,922 |
| Input accidents | 49,941 |
| Successfully attributed accidents | 49,646 |
| Unassigned accidents | 295 |
| High-confidence attributed | 5,579 |
| Medium-confidence attributed | 24,045 |
| Low-confidence attributed | 20,022 |
| Output corridor-risk rows | 362,922 |
| Included year range | 2020-2024 |
| Length-weighted reference risk p95 | 16.557781606822537 accidents/km |
| Refresh calculation time | 69,951.55 ms |
| Recorded row payload | 98,609,392 bytes |
| PostgreSQL table storage | 101,064,704 bytes |
| PostgreSQL index storage | 39,804,928 bytes |
| PostgreSQL total relation storage | 141,180,928 bytes |

The version passed validation and became the sole active risk-data version.
The storage breakdown was read from `pg_relation_size`, `pg_indexes_size`, and
`pg_total_relation_size` in this disposable single-version database. The
refresh command's persisted `storage_bytes` is the per-version row payload,
calculated with `pg_column_size`, so it remains meaningful when multiple
immutable versions share the same physical table and indexes.
