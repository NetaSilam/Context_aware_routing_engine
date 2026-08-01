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

The graph is local benchmark/manual-test input, not an automated-test
dependency. Graph archive publishing/download, runtime Compose wiring, health
checks, compatibility enforcement, and full exclusion smoke tests remain in
the later deployment ticket.
