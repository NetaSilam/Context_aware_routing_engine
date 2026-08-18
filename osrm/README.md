# OSRM routing data

`data/` holds the prepared OSRM graph for Israel/Palestine and is never
committed. Ticket 5 and the later deployment ticket share this pinned graph
definition:

- OSRM image: `ghcr.io/project-osrm/osrm-backend:v6.0.0@sha256:729461bcc9ae9e6aafa92c0f93db9b060a32e85d5e72092c01ae4a4a9f1eb564`
- OSM source: Geofabrik `israel-and-palestine-260731.osm.pbf`, containing OSM
  data through `2026-07-31T20:21:56Z`
- Source SHA-256: `e9b3db1a669140565f75c05a1483f054b7f0df695ce483681791f84cfb80802a`
- Profile: committed [`road-risk-car.lua`](road-risk-car.lua), which explicitly
  supports the required `toll`, `motorway`, and combined exclusions
- Graph data version: `israel-palestine-2026-07-31-osrm-6.0.0-profile-v1`

Download and verify the pinned source:

```
mkdir -p osrm/data
cd osrm/data
curl --fail --location -o israel-and-palestine-260731.osm.pbf \
  https://download.geofabrik.de/asia/israel-and-palestine-260731.osm.pbf
echo "e9b3db1a669140565f75c05a1483f054b7f0df695ce483681791f84cfb80802a  israel-and-palestine-260731.osm.pbf" | shasum -a 256 -c

cp ../road-risk-car.lua ./road-risk-car.lua

docker run --rm -t -v "$(pwd):/data" \
  ghcr.io/project-osrm/osrm-backend:v6.0.0@sha256:729461bcc9ae9e6aafa92c0f93db9b060a32e85d5e72092c01ae4a4a9f1eb564 \
  osrm-extract -p /data/road-risk-car.lua /data/israel-and-palestine-260731.osm.pbf
docker run --rm -t -v "$(pwd):/data" \
  ghcr.io/project-osrm/osrm-backend:v6.0.0@sha256:729461bcc9ae9e6aafa92c0f93db9b060a32e85d5e72092c01ae4a4a9f1eb564 \
  osrm-partition /data/israel-and-palestine-260731.osrm
docker run --rm -t -v "$(pwd):/data" \
  ghcr.io/project-osrm/osrm-backend:v6.0.0@sha256:729461bcc9ae9e6aafa92c0f93db9b060a32e85d5e72092c01ae4a4a9f1eb564 \
  osrm-customize /data/israel-and-palestine-260731.osrm
```

Takes under 2 minutes total on a normal machine (Israel is a small extract).
On Windows Git Bash, prefix each `docker run` with `MSYS_NO_PATHCONV=1` or the
`/opt/car.lua` argument gets mangled into a Windows path.

The graph is local benchmark/manual-test input, not an automated-test dependency.

## Artifact delivery (Ticket 13 deferral)

`graph-artifact-manifest.template.json` records the graph/profile/image identity and the
fields required for an external archive. Archive publication is user-approved deferred tech debt:
copy the template to an ignored manifest, fill `archive_url` and `archive_sha256` only after the
archive is actually published, then run:

```sh
python3 osrm/download_graph.py --manifest osrm/graph-artifact-manifest.json
```

The command fails clearly while those fields are empty. It downloads, verifies, and extracts
into ignored `osrm/data`. Ticket 15 must disclose this deferral and must not claim clean-machine
archive-download verification until publication occurs.

The independent reproducible rebuild command is:

```sh
./osrm/rebuild_graph.sh
```

It downloads the pinned PBF when needed, verifies its checksum, and runs extract, partition, and
customize with the same pinned image and profile. Optional/manual real-graph smoke checks use the
frozen representative corpus and are never authoritative automated tests.

The 2026-08-03 smoke covers all four hard-preference combinations, but does not replace national
PostGIS matching measurements. Before final evidence, run the corpus with every exclusion against
the active national risk version, record coverage and matcher timing, and update the compatibility
evidence. See `docs/CORRIDOR_MATCHER_BENCHMARK.md`.

## Turn-by-turn steps

Every `/route/v1/driving/...` request from the backend (`OsrmClient.request_routes`, in
`backend/app/routing/osrm_client.py`) now includes `steps=true`. This adds per-leg maneuver
instructions (turn type, modifier, street name, and maneuver location) to each candidate, which
both the initial route plan and the live-navigation reroute endpoint surface as `steps` on every
candidate for turn-by-turn text and voice guidance. This graph/profile pin does not need to change
for this — `steps=true` is a request parameter, not a build-time graph option.
