# OSRM routing data

`data/` holds the prepared OSRM graph for Israel/Palestine - not committed
(raw + prepared files run ~650MB total; see root `.gitignore`). Regenerate it
once with:

```
mkdir -p osrm/data
cd osrm/data
curl -L -o israel-and-palestine-latest.osm.pbf \
  https://download.geofabrik.de/asia/israel-and-palestine-latest.osm.pbf

docker run -t -v "$(pwd):/data" osrm/osrm-backend \
  osrm-extract -p /opt/car.lua /data/israel-and-palestine-latest.osm.pbf
docker run -t -v "$(pwd):/data" osrm/osrm-backend \
  osrm-partition /data/israel-and-palestine-latest.osrm
docker run -t -v "$(pwd):/data" osrm/osrm-backend \
  osrm-customize /data/israel-and-palestine-latest.osrm
```

Takes under 2 minutes total on a normal machine (Israel is a small extract).
On Windows Git Bash, prefix each `docker run` with `MSYS_NO_PATHCONV=1` or the
`/opt/car.lua` argument gets mangled into a Windows path.

Once `israel-and-palestine-latest.osrm` (and its sibling files) exist here,
`docker compose up` starts `osrm-routed` against them automatically - no
further steps.
