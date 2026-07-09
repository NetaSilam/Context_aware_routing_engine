export interface GeocodeResult {
  label: string;
  lat: number;
  lon: number;
}

export interface Coordinate {
  lat: number;
  lon: number;
}

export interface RouteCandidate {
  geometry: {
    type: "LineString";
    coordinates: [number, number][];
  };
  distance_m: number;
  duration_s: number;
  accident_count: number;
  risk_density: number;
  normalized_time: number;
  normalized_risk: number;
  cost: number;
}

export interface RouteResponse {
  time_of_day: "day" | "night";
  weights: { w_safe: number; w_time: number };
  chosen_route: RouteCandidate;
  alternatives: RouteCandidate[];
  explanation: string;
}
