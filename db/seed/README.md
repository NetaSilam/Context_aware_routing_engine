# Seed data

Place the exported PostGIS dump from the foundation pipeline repo here as
`road_risk_mapper.dump`. `db/init/01-load-seed.sh` restores it automatically
the first time the `postgis` container starts with an empty data volume.

To (re)generate it from the foundation repo
(github.com/RotemBorenstein/Context-Aware-Safe-Routing-Engine):

```
pg_dump -Fc -U <user> -d <db> -f road_risk_mapper.dump
```

Then copy `road_risk_mapper.dump` into this folder. This file is intentionally
not committed if it's large — see the root `.gitignore` and add a real backup
location (course-provided storage, a release asset, etc.) once you have it.
