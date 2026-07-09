import type {
  CanonicalNetworkSummary,
  CorridorDetail,
  CorridorListResponse,
  GeoJsonLineGeometry,
  OfficialLinkSummary,
  OfficialSegmentLink,
  RoadIdentitySummary,
} from "../types/canonicalNetwork";

const DEFAULT_API_BASE_URL = "/api/canonical-network";

export interface BBoxQuery {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

export interface CanonicalNetworkClientOptions {
  apiBaseUrl?: string;
  fetchImpl?: typeof fetch;
}

export function createCanonicalNetworkClient(
  options: CanonicalNetworkClientOptions = {},
) {
  const apiBaseUrl = options.apiBaseUrl ?? DEFAULT_API_BASE_URL;
  const fetchImpl = options.fetchImpl ?? fetch;

  return {
    getSummary: async (): Promise<CanonicalNetworkSummary> => {
      const response = await fetchJson(`${apiBaseUrl}/summary`, fetchImpl);
      return parseCanonicalNetworkSummary(response);
    },
    getCorridors: async (
      bbox: BBoxQuery,
      limit?: number,
    ): Promise<CorridorListResponse> => {
      const search = new URLSearchParams({
        bbox: `${bbox.minLon},${bbox.minLat},${bbox.maxLon},${bbox.maxLat}`,
      });
      if (typeof limit === "number") {
        search.set("limit", String(limit));
      }
      const response = await fetchJson(`${apiBaseUrl}/corridors?${search.toString()}`, fetchImpl);
      return parseCorridorListResponse(response);
    },
    getCorridorDetail: async (corridorId: string): Promise<CorridorDetail> => {
      const response = await fetchJson(
        `${apiBaseUrl}/corridors/${encodeURIComponent(corridorId)}`,
        fetchImpl,
      );
      return parseCorridorDetail(response);
    },
  };
}

export async function fetchJson(
  url: string,
  fetchImpl: typeof fetch,
): Promise<unknown> {
  const response = await fetchImpl(url, {
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(`Canonical network request failed with status ${response.status}.`);
  }
  return response.json();
}

export function parseCanonicalNetworkSummary(payload: unknown): CanonicalNetworkSummary {
  const value = expectRecord(payload, "summary response");
  return {
    atom_count: expectNumber(value.atom_count, "summary.atom_count"),
    road_count: expectNumber(value.road_count, "summary.road_count"),
    corridor_count: expectNumber(value.corridor_count, "summary.corridor_count"),
    graph_node_count: expectNumber(value.graph_node_count, "summary.graph_node_count"),
    atoms_with_road_identity: expectNumber(
      value.atoms_with_road_identity,
      "summary.atoms_with_road_identity",
    ),
    atoms_without_road_identity: expectNumber(
      value.atoms_without_road_identity,
      "summary.atoms_without_road_identity",
    ),
    excluded_atom_count: expectNumber(value.excluded_atom_count, "summary.excluded_atom_count"),
    excluded_atom_reason: expectString(value.excluded_atom_reason, "summary.excluded_atom_reason"),
    corridor_family_breakdown: expectNumberRecord(
      value.corridor_family_breakdown,
      "summary.corridor_family_breakdown",
    ),
    road_identity_type_breakdown: expectNumberRecord(
      value.road_identity_type_breakdown,
      "summary.road_identity_type_breakdown",
    ),
    build_basis_breakdown: expectNumberRecord(
      value.build_basis_breakdown,
      "summary.build_basis_breakdown",
    ),
    split_reason_breakdown: expectNumberRecord(
      value.split_reason_breakdown,
      "summary.split_reason_breakdown",
    ),
    official_link_target_type_breakdown: expectNumberRecord(
      value.official_link_target_type_breakdown,
      "summary.official_link_target_type_breakdown",
    ),
    official_link_method_breakdown: expectNumberRecord(
      value.official_link_method_breakdown,
      "summary.official_link_method_breakdown",
    ),
    official_link_strength_breakdown: expectNumberRecord(
      value.official_link_strength_breakdown,
      "summary.official_link_strength_breakdown",
    ),
    official_link_row_count: expectNumber(
      value.official_link_row_count,
      "summary.official_link_row_count",
    ),
    official_linked_segment_count: expectNumber(
      value.official_linked_segment_count,
      "summary.official_linked_segment_count",
    ),
    official_unlinked_segment_count: expectNumber(
      value.official_unlinked_segment_count,
      "summary.official_unlinked_segment_count",
    ),
  };
}

export function parseCorridorListResponse(payload: unknown): CorridorListResponse {
  const value = expectRecord(payload, "corridor list response");
  return {
    bbox: {
      min_lon: expectNumber(value.bbox && expectRecord(value.bbox, "corridors.bbox").min_lon, "corridors.bbox.min_lon"),
      min_lat: expectNumber(value.bbox && expectRecord(value.bbox, "corridors.bbox").min_lat, "corridors.bbox.min_lat"),
      max_lon: expectNumber(value.bbox && expectRecord(value.bbox, "corridors.bbox").max_lon, "corridors.bbox.max_lon"),
      max_lat: expectNumber(value.bbox && expectRecord(value.bbox, "corridors.bbox").max_lat, "corridors.bbox.max_lat"),
    },
    max_results: expectNumber(value.max_results, "corridors.max_results"),
    returned_count: expectNumber(value.returned_count, "corridors.returned_count"),
    truncated: expectBoolean(value.truncated, "corridors.truncated"),
    corridors: expectArray(value.corridors, "corridors.corridors").map((item, index) =>
      parseCorridorListItem(item, `corridors.corridors[${index}]`),
    ),
  };
}

export function parseCorridorDetail(payload: unknown): CorridorDetail {
  const value = expectRecord(payload, "corridor detail response");
  return {
    corridor_id: expectString(value.corridor_id, "detail.corridor_id"),
    corridor_family: expectString(value.corridor_family, "detail.corridor_family"),
    road_id: expectNullableString(value.road_id, "detail.road_id"),
    primary_ref: expectNullableString(value.primary_ref, "detail.primary_ref"),
    primary_name: expectNullableString(value.primary_name, "detail.primary_name"),
    length_m: expectNumber(value.length_m, "detail.length_m"),
    atom_count: expectNumber(value.atom_count, "detail.atom_count"),
    build_basis: expectString(value.build_basis, "detail.build_basis"),
    split_from_reason: expectString(value.split_from_reason, "detail.split_from_reason"),
    geometry: parseGeoJsonLineGeometry(value.geometry, "detail.geometry"),
    build_description: expectString(value.build_description, "detail.build_description"),
    road: value.road == null ? null : parseRoadIdentitySummary(value.road, "detail.road"),
    official_link_summary:
      value.official_link_summary == null
        ? null
        : parseOfficialLinkSummary(value.official_link_summary, "detail.official_link_summary"),
  };
}

function parseCorridorListItem(payload: unknown, label: string) {
  const value = expectRecord(payload, label);
  return {
    corridor_id: expectString(value.corridor_id, `${label}.corridor_id`),
    corridor_family: expectString(value.corridor_family, `${label}.corridor_family`),
    road_id: expectNullableString(value.road_id, `${label}.road_id`),
    primary_ref: expectNullableString(value.primary_ref, `${label}.primary_ref`),
    primary_name: expectNullableString(value.primary_name, `${label}.primary_name`),
    length_m: expectNumber(value.length_m, `${label}.length_m`),
    build_basis: expectString(value.build_basis, `${label}.build_basis`),
    geometry: parseGeoJsonLineGeometry(value.geometry, `${label}.geometry`),
  };
}

function parseRoadIdentitySummary(payload: unknown, label: string): RoadIdentitySummary {
  const value = expectRecord(payload, label);
  return {
    road_id: expectString(value.road_id, `${label}.road_id`),
    road_identity_type: expectString(value.road_identity_type, `${label}.road_identity_type`),
    primary_ref: expectNullableString(value.primary_ref, `${label}.primary_ref`),
    primary_name: expectNullableString(value.primary_name, `${label}.primary_name`),
    component_count: expectNumber(value.component_count, `${label}.component_count`),
    atom_count: expectNumber(value.atom_count, `${label}.atom_count`),
  };
}

function parseOfficialLinkSummary(payload: unknown, label: string): OfficialLinkSummary {
  const value = expectRecord(payload, label);
  return {
    official_segment_count: expectNumber(
      value.official_segment_count,
      `${label}.official_segment_count`,
    ),
    link_method_breakdown: expectNumberRecord(
      value.link_method_breakdown,
      `${label}.link_method_breakdown`,
    ),
    link_strength_breakdown: expectNumberRecord(
      value.link_strength_breakdown,
      `${label}.link_strength_breakdown`,
    ),
    links: expectArray(value.links, `${label}.links`).map((item, index) =>
      parseOfficialSegmentLink(item, `${label}.links[${index}]`),
    ),
  };
}

function parseOfficialSegmentLink(payload: unknown, label: string): OfficialSegmentLink {
  const value = expectRecord(payload, label);
  return {
    official_segment_id: expectString(value.official_segment_id, `${label}.official_segment_id`),
    segment_key: expectString(value.segment_key, `${label}.segment_key`),
    road_number: expectNullableString(value.road_number, `${label}.road_number`),
    link_method: expectString(value.link_method, `${label}.link_method`),
    link_strength: expectString(value.link_strength, `${label}.link_strength`),
    source_match_confidence: expectNullableString(
      value.source_match_confidence,
      `${label}.source_match_confidence`,
    ),
    distance_m:
      value.distance_m == null ? null : expectNumber(value.distance_m, `${label}.distance_m`),
    is_multi_target: expectBoolean(value.is_multi_target, `${label}.is_multi_target`),
  };
}

function parseGeoJsonLineGeometry(payload: unknown, label: string): GeoJsonLineGeometry {
  const value = expectRecord(payload, label);
  const geometryType = expectString(value.type, `${label}.type`);
  if (geometryType !== "LineString" && geometryType !== "MultiLineString") {
    throw new Error(`${label}.type must be LineString or MultiLineString.`);
  }
  const coordinates = value.coordinates;
  if (!Array.isArray(coordinates)) {
    throw new Error(`${label}.coordinates must be an array.`);
  }
  return {
    type: geometryType,
    coordinates: coordinates as GeoJsonLineGeometry["coordinates"],
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

function expectBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean.`);
  }
  return value;
}

function expectNumberRecord(value: unknown, label: string): Record<string, number> {
  const record = expectRecord(value, label);
  return Object.fromEntries(
    Object.entries(record).map(([key, entryValue]) => [key, expectNumber(entryValue, `${label}.${key}`)]),
  );
}
