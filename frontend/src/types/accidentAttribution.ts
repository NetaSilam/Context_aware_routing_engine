export interface GeoJsonPointGeometry {
  type: "Point";
  coordinates: [number, number];
}

export interface AccidentAttributionSummary {
  attribution_version: string;
  total_accident_count: number;
  review_needed_count: number;
  status_breakdown: Record<string, number>;
  confidence_breakdown: Record<string, number>;
  unresolved_reason_breakdown: Record<string, number>;
  official_reference_effect_breakdown: Record<string, number>;
  assigned_rate: number;
  assigned_with_warnings_rate: number;
  unresolved_rate: number;
}

export interface AttributedAccidentListItem {
  accident_id: string;
  accident_year: number | null;
  severity: number | null;
  road_number: string | null;
  corridor_id: string | null;
  road_id: string | null;
  corridor_label: string | null;
  attribution_status: string;
  confidence_tier: string;
  confidence_reason_code: string | null;
  geometry: GeoJsonPointGeometry;
}

export interface AttributedAccidentListResponse {
  bbox: {
    min_lon: number;
    min_lat: number;
    max_lon: number;
    max_lat: number;
  };
  max_results: number;
  returned_count: number;
  truncated: boolean;
  accidents: AttributedAccidentListItem[];
}

export interface AttributedAccidentDetail {
  accident: {
    accident_id: string;
    accident_year: number | null;
    severity: number | null;
    road_number: string | null;
    locality_code: number | null;
    geographic_domain: number | null;
    geometry: GeoJsonPointGeometry | null;
  };
  attribution: {
    corridor_id: string | null;
    corridor_family: string | null;
    road_id: string | null;
    corridor_primary_ref: string | null;
    corridor_primary_name: string | null;
    attribution_status: string;
    confidence_tier: string;
    assignment_method: string;
    unresolved_reason: string | null;
    confidence_reason_code: string | null;
    review_needed: boolean;
    distance_to_corridor_m: number | null;
    second_best_distance_m: number | null;
    official_reference_effect: string | null;
    attribution_version: string;
  };
  diagnostics: Record<string, unknown> | null;
  explanation_snippets: string[];
}
