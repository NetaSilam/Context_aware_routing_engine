import type {
  AccidentAttributionSummary,
  AttributedAccidentDetail,
  AttributedAccidentListResponse,
  GeoJsonPointGeometry,
} from "../types/accidentAttribution";

const DEFAULT_API_BASE_URL = "/api/accident-attribution";

export interface BBoxQuery {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

export interface AccidentAttributionClientOptions {
  apiBaseUrl?: string;
  fetchImpl?: typeof fetch;
}

export interface AccidentAttributionFilters {
  status?: string;
  confidence?: string;
  year?: number;
}

export function createAccidentAttributionClient(
  options: AccidentAttributionClientOptions = {},
) {
  const apiBaseUrl = options.apiBaseUrl ?? DEFAULT_API_BASE_URL;
  const fetchImpl = options.fetchImpl ?? fetch;

  return {
    getSummary: async (): Promise<AccidentAttributionSummary> => {
      const response = await fetchJson(`${apiBaseUrl}/summary`, fetchImpl);
      return parseAccidentAttributionSummary(response);
    },
    getAccidents: async (
      bbox: BBoxQuery,
      filters: AccidentAttributionFilters = {},
      limit?: number,
    ): Promise<AttributedAccidentListResponse> => {
      const search = new URLSearchParams({
        bbox: `${bbox.minLon},${bbox.minLat},${bbox.maxLon},${bbox.maxLat}`,
      });
      if (typeof limit === "number") {
        search.set("limit", String(limit));
      }
      if (filters.status) {
        search.set("status", filters.status);
      }
      if (filters.confidence) {
        search.set("confidence", filters.confidence);
      }
      if (typeof filters.year === "number") {
        search.set("year", String(filters.year));
      }
      const response = await fetchJson(`${apiBaseUrl}/accidents?${search.toString()}`, fetchImpl);
      return parseAttributedAccidentListResponse(response);
    },
    getAccidentDetail: async (accidentId: string): Promise<AttributedAccidentDetail> => {
      const response = await fetchJson(
        `${apiBaseUrl}/accidents/${encodeURIComponent(accidentId)}`,
        fetchImpl,
      );
      return parseAttributedAccidentDetail(response);
    },
  };
}

async function fetchJson(url: string, fetchImpl: typeof fetch): Promise<unknown> {
  const response = await fetchImpl(url, {
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(`Accident attribution request failed with status ${response.status}.`);
  }
  return response.json();
}

export function parseAccidentAttributionSummary(
  payload: unknown,
): AccidentAttributionSummary {
  const value = expectRecord(payload, "summary response");
  return {
    attribution_version: expectString(value.attribution_version, "summary.attribution_version"),
    total_accident_count: expectNumber(value.total_accident_count, "summary.total_accident_count"),
    review_needed_count: expectNumber(value.review_needed_count, "summary.review_needed_count"),
    status_breakdown: expectNumberRecord(value.status_breakdown, "summary.status_breakdown"),
    confidence_breakdown: expectNumberRecord(
      value.confidence_breakdown,
      "summary.confidence_breakdown",
    ),
    unresolved_reason_breakdown: expectNumberRecord(
      value.unresolved_reason_breakdown,
      "summary.unresolved_reason_breakdown",
    ),
    official_reference_effect_breakdown: expectNumberRecord(
      value.official_reference_effect_breakdown,
      "summary.official_reference_effect_breakdown",
    ),
    assigned_rate: expectNumber(value.assigned_rate, "summary.assigned_rate"),
    assigned_with_warnings_rate: expectNumber(
      value.assigned_with_warnings_rate,
      "summary.assigned_with_warnings_rate",
    ),
    unresolved_rate: expectNumber(value.unresolved_rate, "summary.unresolved_rate"),
  };
}

export function parseAttributedAccidentListResponse(
  payload: unknown,
): AttributedAccidentListResponse {
  const value = expectRecord(payload, "accident list response");
  const bbox = expectRecord(value.bbox, "accidents.bbox");
  return {
    bbox: {
      min_lon: expectNumber(bbox.min_lon, "accidents.bbox.min_lon"),
      min_lat: expectNumber(bbox.min_lat, "accidents.bbox.min_lat"),
      max_lon: expectNumber(bbox.max_lon, "accidents.bbox.max_lon"),
      max_lat: expectNumber(bbox.max_lat, "accidents.bbox.max_lat"),
    },
    max_results: expectNumber(value.max_results, "accidents.max_results"),
    returned_count: expectNumber(value.returned_count, "accidents.returned_count"),
    truncated: expectBoolean(value.truncated, "accidents.truncated"),
    accidents: expectArray(value.accidents, "accidents.accidents").map((item, index) =>
      parseAttributedAccidentListItem(item, `accidents.accidents[${index}]`),
    ),
  };
}

export function parseAttributedAccidentDetail(
  payload: unknown,
): AttributedAccidentDetail {
  const value = expectRecord(payload, "accident detail response");
  const accident = expectRecord(value.accident, "detail.accident");
  const attribution = expectRecord(value.attribution, "detail.attribution");
  return {
    accident: {
      accident_id: expectString(accident.accident_id, "detail.accident.accident_id"),
      accident_year: expectNullableNumber(
        accident.accident_year,
        "detail.accident.accident_year",
      ),
      severity: expectNullableNumber(accident.severity, "detail.accident.severity"),
      road_number: expectNullableString(accident.road_number, "detail.accident.road_number"),
      locality_code: expectNullableNumber(
        accident.locality_code,
        "detail.accident.locality_code",
      ),
      geographic_domain: expectNullableNumber(
        accident.geographic_domain,
        "detail.accident.geographic_domain",
      ),
      geometry:
        accident.geometry == null
          ? null
          : parseGeoJsonPointGeometry(accident.geometry, "detail.accident.geometry"),
    },
    attribution: {
      corridor_id: expectNullableString(
        attribution.corridor_id,
        "detail.attribution.corridor_id",
      ),
      corridor_family: expectNullableString(
        attribution.corridor_family,
        "detail.attribution.corridor_family",
      ),
      road_id: expectNullableString(attribution.road_id, "detail.attribution.road_id"),
      corridor_primary_ref: expectNullableString(
        attribution.corridor_primary_ref,
        "detail.attribution.corridor_primary_ref",
      ),
      corridor_primary_name: expectNullableString(
        attribution.corridor_primary_name,
        "detail.attribution.corridor_primary_name",
      ),
      attribution_status: expectString(
        attribution.attribution_status,
        "detail.attribution.attribution_status",
      ),
      confidence_tier: expectString(
        attribution.confidence_tier,
        "detail.attribution.confidence_tier",
      ),
      assignment_method: expectString(
        attribution.assignment_method,
        "detail.attribution.assignment_method",
      ),
      unresolved_reason: expectNullableString(
        attribution.unresolved_reason,
        "detail.attribution.unresolved_reason",
      ),
      confidence_reason_code: expectNullableString(
        attribution.confidence_reason_code,
        "detail.attribution.confidence_reason_code",
      ),
      review_needed: expectBoolean(
        attribution.review_needed,
        "detail.attribution.review_needed",
      ),
      distance_to_corridor_m: expectNullableNumber(
        attribution.distance_to_corridor_m,
        "detail.attribution.distance_to_corridor_m",
      ),
      second_best_distance_m: expectNullableNumber(
        attribution.second_best_distance_m,
        "detail.attribution.second_best_distance_m",
      ),
      official_reference_effect: expectNullableString(
        attribution.official_reference_effect,
        "detail.attribution.official_reference_effect",
      ),
      attribution_version: expectString(
        attribution.attribution_version,
        "detail.attribution.attribution_version",
      ),
    },
    diagnostics:
      value.diagnostics == null ? null : expectRecord(value.diagnostics, "detail.diagnostics"),
    explanation_snippets: expectArray(
      value.explanation_snippets,
      "detail.explanation_snippets",
    ).map((entry, index) =>
      expectString(entry, `detail.explanation_snippets[${index}]`),
    ),
  };
}

function parseAttributedAccidentListItem(payload: unknown, label: string) {
  const value = expectRecord(payload, label);
  return {
    accident_id: expectString(value.accident_id, `${label}.accident_id`),
    accident_year: expectNullableNumber(value.accident_year, `${label}.accident_year`),
    severity: expectNullableNumber(value.severity, `${label}.severity`),
    road_number: expectNullableString(value.road_number, `${label}.road_number`),
    corridor_id: expectNullableString(value.corridor_id, `${label}.corridor_id`),
    road_id: expectNullableString(value.road_id, `${label}.road_id`),
    corridor_label: expectNullableString(value.corridor_label, `${label}.corridor_label`),
    attribution_status: expectString(value.attribution_status, `${label}.attribution_status`),
    confidence_tier: expectString(value.confidence_tier, `${label}.confidence_tier`),
    confidence_reason_code: expectNullableString(
      value.confidence_reason_code,
      `${label}.confidence_reason_code`,
    ),
    geometry: parseGeoJsonPointGeometry(value.geometry, `${label}.geometry`),
  };
}

function parseGeoJsonPointGeometry(payload: unknown, label: string): GeoJsonPointGeometry {
  const value = expectRecord(payload, label);
  if (expectString(value.type, `${label}.type`) !== "Point") {
    throw new Error(`${label}.type must be Point.`);
  }
  if (!Array.isArray(value.coordinates) || value.coordinates.length !== 2) {
    throw new Error(`${label}.coordinates must be a two-item array.`);
  }
  return {
    type: "Point",
    coordinates: value.coordinates as [number, number],
  };
}

function expectRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function expectArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array.`);
  }
  return value;
}

function expectString(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new Error(`${label} must be a string.`);
  }
  return value;
}

function expectNullableString(value: unknown, label: string): string | null {
  if (value == null) {
    return null;
  }
  return expectString(value, label);
}

function expectNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new Error(`${label} must be a number.`);
  }
  return value;
}

function expectNullableNumber(value: unknown, label: string): number | null {
  if (value == null) {
    return null;
  }
  return expectNumber(value, label);
}

function expectBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean.`);
  }
  return value;
}

function expectNumberRecord(value: unknown, label: string): Record<string, number> {
  const record = expectRecord(value, label);
  return Object.fromEntries(
    Object.entries(record).map(([key, entryValue]) => [
      key,
      expectNumber(entryValue, `${label}.${key}`),
    ]),
  );
}
