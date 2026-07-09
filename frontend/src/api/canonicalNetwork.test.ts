import { describe, expect, it } from "vitest";

import {
  parseCanonicalNetworkSummary,
  parseCorridorDetail,
  parseCorridorListResponse,
} from "./canonicalNetwork";

describe("canonicalNetwork API parsing", () => {
  it("parses a valid summary payload", () => {
    const summary = parseCanonicalNetworkSummary({
      atom_count: 10,
      road_count: 3,
      corridor_count: 4,
      graph_node_count: 8,
      atoms_with_road_identity: 6,
      atoms_without_road_identity: 4,
      excluded_atom_count: 0,
      excluded_atom_reason: "none",
      corridor_family_breakdown: { ref_road_corridor: 2, local_unnamed_corridor: 2 },
      road_identity_type_breakdown: { ref: 2, name: 1 },
      build_basis_breakdown: { road_identity: 3, local_grouping: 1 },
      split_reason_breakdown: { terminal: 2, major_junction: 2 },
      official_link_target_type_breakdown: { corridor: 2 },
      official_link_method_breakdown: { osm_match: 2 },
      official_link_strength_breakdown: { strong: 2 },
      official_link_row_count: 2,
      official_linked_segment_count: 2,
      official_unlinked_segment_count: 0,
    });

    expect(summary.corridor_count).toBe(4);
    expect(summary.corridor_family_breakdown.ref_road_corridor).toBe(2);
  });

  it("parses a valid corridor list payload", () => {
    const response = parseCorridorListResponse({
      bbox: { min_lon: 34, min_lat: 29, max_lon: 36, max_lat: 33 },
      max_results: 1,
      returned_count: 1,
      truncated: false,
      corridors: [
        {
          corridor_id: "corridor:1",
          corridor_family: "ref_road_corridor",
          road_id: "road:1",
          primary_ref: "4",
          primary_name: null,
          length_m: 1234,
          build_basis: "road_identity",
          geometry: {
            type: "LineString",
            coordinates: [
              [34, 32],
              [34.1, 32.1],
            ],
          },
        },
      ],
    });

    expect(response.corridors).toHaveLength(1);
    expect(response.corridors[0].corridor_id).toBe("corridor:1");
  });

  it("parses a valid corridor detail payload", () => {
    const detail = parseCorridorDetail({
      corridor_id: "corridor:2",
      corridor_family: "local_unnamed_corridor",
      road_id: null,
      primary_ref: null,
      primary_name: null,
      length_m: 87,
      atom_count: 3,
      build_basis: "local_grouping",
      split_from_reason: "major_junction",
      geometry: {
        type: "MultiLineString",
        coordinates: [
          [
            [34, 32],
            [34.1, 32.1],
          ],
        ],
      },
      build_description: "Built from connected local OSM atoms without a strong shared road identity.",
      road: null,
      official_link_summary: {
        official_segment_count: 1,
        link_method_breakdown: { osm_match: 1 },
        link_strength_breakdown: { weak: 1 },
        links: [
          {
            official_segment_id: "official:1",
            segment_key: "4-12",
            road_number: "4",
            link_method: "osm_match",
            link_strength: "weak",
            source_match_confidence: "medium",
            distance_m: 15,
            is_multi_target: false,
          },
        ],
      },
    });

    expect(detail.official_link_summary?.links[0].official_segment_id).toBe("official:1");
  });

  it("fails fast when a required field is missing", () => {
    expect(() =>
      parseCorridorListResponse({
        bbox: { min_lon: 34, min_lat: 29, max_lon: 36, max_lat: 33 },
        max_results: 1,
        returned_count: 1,
        truncated: false,
        corridors: [
          {
            corridor_id: "corridor:1",
            corridor_family: "ref_road_corridor",
            road_id: "road:1",
            primary_ref: "4",
            primary_name: null,
            build_basis: "road_identity",
            geometry: {
              type: "LineString",
              coordinates: [
                [34, 32],
                [34.1, 32.1],
              ],
            },
          },
        ],
      }),
    ).toThrowError("corridors.corridors[0].length_m must be a number.");
  });
});
