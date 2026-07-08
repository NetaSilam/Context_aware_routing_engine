# Non-Traffic Downstream Artifacts

This folder contains copied artifacts from the project that are used in the non-traffic data flow.

It is meant for someone who wants:

- accident data
- OSM-based road mapping data
- the final road-analysis network
- the final accident-to-road assignment outputs

It does **not** include traffic count artifacts.

## Simple Data Flow

The project works like this:

1. Start with raw accident records and raw OSM road geometry.
2. Clean them into reusable base datasets.
3. Build a cleaner road-analysis network from the OSM and official road references.
4. Attach accidents to that final network.

This folder contains copies from steps 2, 3, and 4.

## Terminology

`prepared`

- means cleaned and standardized
- not raw source data
- safe to use as input for later stages

`OSM roads`

- road lines that come from OpenStreetMap
- these are the base map roads before the project builds its own analysis network

`official segments`

- official government road reference segments
- these are not traffic counts
- they are reference road pieces used to help align the OSM network to an official road system

`segment to OSM matches`

- a table saying which official segment most likely matches which OSM road feature

`corridors`

- the final road-analysis units used by the project
- a corridor is a stable stretch of road built from many smaller OSM pieces
- the project uses corridors instead of raw OSM segments because raw OSM is too fragmented for stable accident analysis

`accident attribution`

- the final assignment of each accident to a corridor

`GeoParquet`

- a Parquet file with geometry and coordinate-system metadata
- use it when the file contains points or lines on a map

`Parquet`

- a normal column table
- use it when the file is just rows and columns and has no map geometry

## Files In This Folder

### Foundation Data

`prepared_accidents.geoparquet`

- cleaned accident records with point geometry
- one row per accident
- this is the accident dataset used downstream

`prepared_osm_roads.geoparquet`

- cleaned OSM road geometry
- this is the base map-road dataset used to build the project road network

`prepared_official_segments.geoparquet`

- cleaned official road reference segments with geometry
- used to connect the OSM road network to the official road system

`prepared_segment_osm_matches.parquet`

- a lookup table between official segments and OSM road features
- used downstream when building and validating the mapped road network

### Canonical Network

`canonical_corridors.geoparquet`

- the final road-analysis network
- each row is a corridor, which is the main road unit used for later analysis

`official_segment_links.parquet`

- links between official segments and the final canonical network objects
- used as supporting evidence in downstream attribution logic

### Accident Attribution

`accident_attributions.geoparquet`

- the final accident output with geometry
- each row is an accident plus the corridor it was assigned to

`accident_attribution_summary.parquet`

- summary table for the attribution results
- contains aggregate counts and rates, not one row per accident

## What Is Excluded

Traffic-count data is intentionally excluded.

That means this folder does **not** contain:

- `prepared_traffic_exposure.parquet`
- `prepared_traffic_year_selection_audit.parquet`
- any raw files from `Data/traffic count data/`

## If You Only Need The Smallest Useful Set

If someone only wants the most important non-traffic outputs, start with these four files:

- `prepared_accidents.geoparquet`
- `prepared_osm_roads.geoparquet`
- `canonical_corridors.geoparquet`
- `accident_attributions.geoparquet`
