#!/usr/bin/env sh
set -eu
data_dir=${1:-osrm/data}
image='ghcr.io/project-osrm/osrm-backend:v6.0.0@sha256:729461bcc9ae9e6aafa92c0f93db9b060a32e85d5e72092c01ae4a4a9f1eb564'
pbf=israel-and-palestine-260731.osm.pbf
sha=e9b3db1a669140565f75c05a1483f054b7f0df695ce483681791f84cfb80802a
mkdir -p "$data_dir"
if [ ! -f "$data_dir/$pbf" ]; then curl --fail --location -o "$data_dir/$pbf" "https://download.geofabrik.de/asia/$pbf"; fi
printf '%s  %s\n' "$sha" "$data_dir/$pbf" | shasum -a 256 -c -
cp osrm/road-risk-car.lua "$data_dir/road-risk-car.lua"
for command in "osrm-extract -p /data/road-risk-car.lua /data/$pbf" "osrm-partition /data/${pbf%.pbf}.osrm" "osrm-customize /data/${pbf%.pbf}.osrm"; do
  docker run --rm -v "$(cd "$data_dir" && pwd):/data" "$image" sh -c "$command"
done
