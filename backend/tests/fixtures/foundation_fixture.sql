CREATE SCHEMA IF NOT EXISTS canonical_network;
CREATE SCHEMA IF NOT EXISTS accident_attribution;

CREATE TABLE IF NOT EXISTS canonical_network.canonical_corridors (
    corridor_id TEXT PRIMARY KEY,
    corridor_family TEXT NOT NULL,
    road_id TEXT,
    primary_ref TEXT,
    primary_name TEXT,
    length_m DOUBLE PRECISION NOT NULL,
    atom_count INTEGER NOT NULL,
    build_basis TEXT NOT NULL,
    split_from_reason TEXT NOT NULL,
    geometry geometry(LineString, 2039) NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical_network.official_segment_links (
    official_segment_id TEXT NOT NULL,
    segment_key TEXT NOT NULL,
    road_number TEXT,
    target_object_type TEXT NOT NULL,
    target_object_id TEXT NOT NULL,
    link_method TEXT NOT NULL,
    link_strength TEXT NOT NULL,
    source_match_confidence TEXT,
    distance_m DOUBLE PRECISION,
    is_multi_target BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS accident_attribution.accident_attributions (
    accident_id TEXT PRIMARY KEY,
    accident_year INTEGER,
    severity INTEGER,
    road_number TEXT,
    locality_code INTEGER,
    geographic_domain INTEGER,
    corridor_id TEXT,
    corridor_family TEXT,
    road_id TEXT,
    corridor_primary_ref TEXT,
    corridor_primary_name TEXT,
    attribution_status TEXT NOT NULL,
    confidence_tier TEXT NOT NULL,
    assignment_method TEXT NOT NULL,
    unresolved_reason TEXT,
    confidence_reason_code TEXT,
    review_needed BOOLEAN NOT NULL,
    distance_to_corridor_m DOUBLE PRECISION,
    second_best_distance_m DOUBLE PRECISION,
    official_reference_effect TEXT,
    diagnostics_json TEXT,
    attribution_version TEXT NOT NULL,
    geometry geometry(Point, 4326)
);

CREATE TABLE IF NOT EXISTS accident_attribution.accident_attribution_summary (
    attribution_version TEXT PRIMARY KEY,
    total_accident_count INTEGER NOT NULL,
    review_needed_count INTEGER NOT NULL,
    status_breakdown JSONB NOT NULL,
    confidence_breakdown JSONB NOT NULL,
    unresolved_reason_breakdown JSONB NOT NULL,
    official_reference_effect_breakdown JSONB NOT NULL,
    assigned_rate DOUBLE PRECISION NOT NULL,
    assigned_with_warnings_rate DOUBLE PRECISION NOT NULL,
    unresolved_rate DOUBLE PRECISION NOT NULL
);

INSERT INTO canonical_network.canonical_corridors
    (corridor_id, corridor_family, road_id, primary_ref, primary_name, length_m,
     atom_count, build_basis, split_from_reason, geometry)
VALUES
    ('fixture-corridor-1', 'named_road', 'fixture-road-1', '1', 'Fixture Road',
     1000.0, 1, 'fixture', 'not_split',
     ST_Transform(ST_GeomFromText('LINESTRING(34.78 32.07, 34.79 32.08)', 4326), 2039))
ON CONFLICT (corridor_id) DO NOTHING;

INSERT INTO canonical_network.official_segment_links
    (official_segment_id, segment_key, road_number, target_object_type,
     target_object_id, link_method, link_strength, source_match_confidence,
     distance_m, is_multi_target)
SELECT
    'fixture-segment-1', 'fixture-key-1', '1', 'corridor', 'fixture-corridor-1',
    'fixture', 'strong', 'high', 0.0, FALSE
WHERE NOT EXISTS (
    SELECT 1 FROM canonical_network.official_segment_links
    WHERE official_segment_id = 'fixture-segment-1'
);

INSERT INTO accident_attribution.accident_attributions
    (accident_id, accident_year, severity, road_number, locality_code,
     geographic_domain, corridor_id, corridor_family, road_id,
     corridor_primary_ref, corridor_primary_name, attribution_status,
     confidence_tier, assignment_method, unresolved_reason,
     confidence_reason_code, review_needed, distance_to_corridor_m,
     second_best_distance_m, official_reference_effect, diagnostics_json,
     attribution_version, geometry)
VALUES
    ('fixture-accident-1', 2023, 2, '1', 5000, 1, 'fixture-corridor-1',
     'named_road', 'fixture-road-1', '1', 'Fixture Road', 'assigned', 'high',
     'nearest_corridor', NULL, 'fixture_match', FALSE, 0.0, 25.0,
     'confirmed', '{"fixture": true}', 'fixture-v1',
     ST_SetSRID(ST_MakePoint(34.785, 32.075), 4326))
ON CONFLICT (accident_id) DO NOTHING;

INSERT INTO accident_attribution.accident_attribution_summary
    (attribution_version, total_accident_count, review_needed_count,
     status_breakdown, confidence_breakdown, unresolved_reason_breakdown,
     official_reference_effect_breakdown, assigned_rate,
     assigned_with_warnings_rate, unresolved_rate)
VALUES
    ('fixture-v1', 1, 0, '{"assigned": 1}', '{"high": 1}', '{}',
     '{"confirmed": 1}', 1.0, 0.0, 0.0)
ON CONFLICT (attribution_version) DO NOTHING;
