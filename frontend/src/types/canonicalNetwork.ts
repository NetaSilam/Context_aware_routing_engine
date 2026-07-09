export type GeometryCoordinates = number[] | number[][] | number[][][];

export interface GeoJsonLineGeometry {
  type: "LineString" | "MultiLineString";
  coordinates: GeometryCoordinates;
}

export interface CanonicalNetworkSummary {
  atom_count: number;
  road_count: number;
  corridor_count: number;
  graph_node_count: number;
  atoms_with_road_identity: number;
  atoms_without_road_identity: number;
  excluded_atom_count: number;
  excluded_atom_reason: string;
  corridor_family_breakdown: Record<string, number>;
  road_identity_type_breakdown: Record<string, number>;
  build_basis_breakdown: Record<string, number>;
  split_reason_breakdown: Record<string, number>;
  official_link_target_type_breakdown: Record<string, number>;
  official_link_method_breakdown: Record<string, number>;
  official_link_strength_breakdown: Record<string, number>;
  official_link_row_count: number;
  official_linked_segment_count: number;
  official_unlinked_segment_count: number;
}

export interface CorridorListItem {
  corridor_id: string;
  corridor_family: string;
  road_id: string | null;
  primary_ref: string | null;
  primary_name: string | null;
  length_m: number;
  build_basis: string;
  geometry: GeoJsonLineGeometry;
}

export interface CorridorListResponse {
  bbox: {
    min_lon: number;
    min_lat: number;
    max_lon: number;
    max_lat: number;
  };
  max_results: number;
  returned_count: number;
  truncated: boolean;
  corridors: CorridorListItem[];
}

export interface RoadIdentitySummary {
  road_id: string;
  road_identity_type: string;
  primary_ref: string | null;
  primary_name: string | null;
  component_count: number;
  atom_count: number;
}

export interface OfficialSegmentLink {
  official_segment_id: string;
  segment_key: string;
  road_number: string | null;
  link_method: string;
  link_strength: string;
  source_match_confidence: string | null;
  distance_m: number | null;
  is_multi_target: boolean;
}

export interface OfficialLinkSummary {
  official_segment_count: number;
  link_method_breakdown: Record<string, number>;
  link_strength_breakdown: Record<string, number>;
  links: OfficialSegmentLink[];
}

export interface CorridorDetail {
  corridor_id: string;
  corridor_family: string;
  road_id: string | null;
  primary_ref: string | null;
  primary_name: string | null;
  length_m: number;
  atom_count: number;
  build_basis: string;
  split_from_reason: string;
  geometry: GeoJsonLineGeometry;
  build_description: string;
  road: RoadIdentitySummary | null;
  official_link_summary: OfficialLinkSummary | null;
}
