export type RouteJobState = "queued" | "running" | "completed" | "failed";

export interface RouteCandidateResult {
  candidate_index: number;
  distance_m: number;
  duration_seconds: number;
  matched_route_length_m: number;
  accident_score: number;
  historical_accident_density_per_km: number;
  coverage: number;
  warning: string | null;
  time_penalty: number;
  normalized_risk: number;
  time_contribution: number;
  safety_contribution: number;
  final_cost: number;
  geometry: { type: "LineString"; coordinates: [number, number][] };
}

export interface RouteJobResult {
  schema_version: string;
  chosen_index: number;
  risk_choice_available: boolean;
  candidates: RouteCandidateResult[];
  safety_weight: number;
  time_weight: number;
  safety_factor_contributions: Record<string, number>;
  reference_risk_p95: number;
  low_coverage_threshold: number;
  risk_data_version: string;
  formula_version: string;
  matcher_version: string;
  graph_version: string;
  included_year_start: number;
  included_year_end: number;
  risk_metric_name: string;
  risk_metric_description: string;
}

export interface RouteJob {
  id: string;
  status: RouteJobState;
  origin_longitude: number;
  origin_latitude: number;
  destination_longitude: number;
  destination_latitude: number;
  origin_label: string | null;
  destination_label: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  failure: { code: string; message: string; retryable: boolean } | null;
  result: RouteJobResult | null;
}

export interface RouteHistorySummary {
  id: string;
  origin_label: string | null;
  destination_label: string | null;
  origin_longitude: number;
  origin_latitude: number;
  destination_longitude: number;
  destination_latitude: number;
  completed_at: string;
  chosen_index: number;
  route_count: number;
  distance_m: number;
  duration_seconds: number;
  historical_accident_density_per_km: number;
  coverage: number;
  final_cost: number;
  risk_choice_available: boolean;
}

export interface RouteHistoryPage {
  items: RouteHistorySummary[];
  offset: number;
  limit: number;
  has_more: boolean;
}
