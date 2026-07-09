import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createCanonicalNetworkClient,
  type BBoxQuery,
} from "../api/canonicalNetwork";
import CanonicalNetworkPage from "./CanonicalNetworkPage";

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="mock-map">{children}</div>
  ),
  TileLayer: () => null,
  Polyline: () => null,
  useMap: () => ({
    fitBounds: vi.fn(),
    getBounds: () => ({
      getWest: () => 34.6,
      getSouth: () => 31.8,
      getEast: () => 35.1,
      getNorth: () => 32.4,
    }),
  }),
  useMapEvents: () => null,
}));

function createMockClient() {
  const getSummary = vi.fn().mockResolvedValue({
    atom_count: 597661,
    road_count: 17929,
    corridor_count: 362922,
    graph_node_count: 412221,
    atoms_with_road_identity: 233137,
    atoms_without_road_identity: 364524,
    excluded_atom_count: 0,
    excluded_atom_reason: "none",
    corridor_family_breakdown: {
      ref_road_corridor: 1,
      local_unnamed_corridor: 1,
    },
    road_identity_type_breakdown: {
      ref: 12000,
      name: 5929,
    },
    build_basis_breakdown: {
      road_identity: 1,
      local_grouping: 1,
    },
    split_reason_breakdown: {
      major_junction: 1,
      terminal: 1,
    },
    official_link_target_type_breakdown: {
      corridor: 1,
    },
    official_link_method_breakdown: {
      osm_match: 1,
    },
    official_link_strength_breakdown: {
      strong: 1,
    },
    official_link_row_count: 1,
    official_linked_segment_count: 1,
    official_unlinked_segment_count: 4,
  });

  const nationwideCorridors = [
    {
      corridor_id: "corridor:1",
      corridor_family: "ref_road_corridor",
      road_id: "road:1",
      primary_ref: "4",
      primary_name: null,
      length_m: 1200,
      build_basis: "road_identity",
      geometry: {
        type: "LineString" as const,
        coordinates: [
          [34.8, 32.0],
          [34.81, 32.01],
        ],
      },
    },
    {
      corridor_id: "corridor:2",
      corridor_family: "local_unnamed_corridor",
      road_id: null,
      primary_ref: null,
      primary_name: "Market Lane",
      length_m: 180,
      build_basis: "local_grouping",
      geometry: {
        type: "LineString" as const,
        coordinates: [
          [34.9, 32.1],
          [34.91, 32.11],
        ],
      },
    },
  ];

  const coastalCorridors = [
    {
      corridor_id: "corridor:3",
      corridor_family: "named_urban_corridor",
      road_id: "road:5",
      primary_ref: null,
      primary_name: "Coastal Spine",
      length_m: 840,
      build_basis: "road_identity",
      geometry: {
        type: "LineString" as const,
        coordinates: [
          [34.7, 32.05],
          [34.72, 32.08],
        ],
      },
    },
  ];

  const getCorridors = vi.fn(
    async (bbox: BBoxQuery) =>
      bbox.minLon > 34.5
        ? {
            bbox: { min_lon: bbox.minLon, min_lat: bbox.minLat, max_lon: bbox.maxLon, max_lat: bbox.maxLat },
            max_results: 250,
            returned_count: coastalCorridors.length,
            truncated: false,
            corridors: coastalCorridors,
          }
        : {
            bbox: { min_lon: bbox.minLon, min_lat: bbox.minLat, max_lon: bbox.maxLon, max_lat: bbox.maxLat },
            max_results: 250,
            returned_count: nationwideCorridors.length,
            truncated: false,
            corridors: nationwideCorridors,
          },
  );

  const getCorridorDetail = vi.fn(async (corridorId: string) => ({
    corridor_id: corridorId,
    corridor_family:
      corridorId === "corridor:1"
        ? "ref_road_corridor"
        : corridorId === "corridor:3"
          ? "named_urban_corridor"
          : "local_unnamed_corridor",
    road_id:
      corridorId === "corridor:1" ? "road:1" : corridorId === "corridor:3" ? "road:5" : null,
    primary_ref: corridorId === "corridor:1" ? "4" : null,
    primary_name:
      corridorId === "corridor:3" ? "Coastal Spine" : corridorId === "corridor:1" ? null : "Market Lane",
    length_m: corridorId === "corridor:1" ? 1200 : corridorId === "corridor:3" ? 840 : 180,
    atom_count: corridorId === "corridor:1" ? 5 : corridorId === "corridor:3" ? 4 : 2,
    build_basis:
      corridorId === "corridor:1" || corridorId === "corridor:3"
        ? "road_identity"
        : "local_grouping",
    split_from_reason: "major_junction",
    geometry: {
      type: "LineString" as const,
      coordinates: [
        [34.8, 32.0],
        [34.81, 32.01],
      ],
    },
    build_description:
      corridorId === "corridor:1"
        ? "Built from connected OSM segments sharing road ref 4."
        : corridorId === "corridor:3"
          ? "Built from connected OSM segments merged by the stable street name Coastal Spine."
          : "Built from connected local OSM atoms without a strong shared road identity.",
    road:
      corridorId === "corridor:1"
        ? {
            road_id: "road:1",
            road_identity_type: "ref",
            primary_ref: "4",
            primary_name: null,
            component_count: 1,
            atom_count: 5,
          }
        : corridorId === "corridor:3"
          ? {
              road_id: "road:5",
              road_identity_type: "name",
              primary_ref: null,
              primary_name: "Coastal Spine",
              component_count: 1,
              atom_count: 4,
            }
        : null,
    official_link_summary: null,
  }));

  return {
    getSummary,
    getCorridors,
    getCorridorDetail,
  };
}

function createJsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response;
}

afterEach(() => {
  cleanup();
});

describe("CanonicalNetworkPage", () => {
  it("renders summary cards, loads bbox-scoped data, filters visible corridors, and opens detail", async () => {
    const user = userEvent.setup();
    const client = createMockClient();

    render(<CanonicalNetworkPage client={client} />);

    expect(await screen.findByText("Network Atoms")).toBeTruthy();
    expect(await screen.findByText("597,661")).toBeTruthy();

    await waitFor(() => {
      expect(client.getCorridors).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("Market Lane")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("Corridor family"), "local_unnamed_corridor");
    expect(screen.getByText("Market Lane")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("Corridor family"), "all");
    await user.click(screen.getByRole("button", { name: "Coastal focus" }));

    await waitFor(() => {
      expect(client.getCorridors).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Coastal Spine")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Coastal Spine named_urban_corridor" }));
    await waitFor(() => {
      expect(client.getCorridorDetail).toHaveBeenCalledWith("corridor:3");
    });
    expect(await screen.findByText("Selected Corridor")).toBeTruthy();
    expect(await screen.findByText("Built from connected OSM segments merged by the stable street name Coastal Spine.")).toBeTruthy();
    expect(await screen.findByText("major_junction")).toBeTruthy();
  });

  it("runs the UI inspection workflow through the real typed client contract", async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith("/summary")) {
        return createJsonResponse({
          atom_count: 597661,
          road_count: 17929,
          corridor_count: 362922,
          graph_node_count: 475999,
          atoms_with_road_identity: 233137,
          atoms_without_road_identity: 364524,
          excluded_atom_count: 0,
          excluded_atom_reason: "none_currently_excluded",
          corridor_family_breakdown: {
            link_ramp_corridor: 9845,
            local_unnamed_corridor: 265640,
            named_urban_corridor: 74524,
            ref_road_corridor: 12913,
          },
          road_identity_type_breakdown: {
            name: 17163,
            ref: 766,
          },
          build_basis_breakdown: {
            link_ramp: 9845,
            local_connectivity: 265640,
            named_identity: 74524,
            ref_identity: 12913,
          },
          split_reason_breakdown: {
            chain_segment: 354931,
            cycle_component: 6145,
            length_cap_split: 1846,
          },
          official_link_target_type_breakdown: {
            atom: 2507,
            corridor: 1005,
            unlinked: 4,
          },
          official_link_method_breakdown: {
            major_class_fallback: 199,
            missing_match_record: 4,
            nearest_feature_fallback: 67,
            same_ref_anchor: 3246,
          },
          official_link_strength_breakdown: {
            medium: 22,
            none: 4,
            strong: 3224,
            weak: 266,
          },
          official_link_row_count: 3516,
          official_linked_segment_count: 840,
          official_unlinked_segment_count: 4,
        });
      }

      if (url.includes("/corridors?bbox=34.65%2C31.75%2C35.1%2C32.35")) {
        return createJsonResponse({
          bbox: { min_lon: 34.65, min_lat: 31.75, max_lon: 35.1, max_lat: 32.35 },
          max_results: 250,
          returned_count: 1,
          truncated: false,
          corridors: [
            {
              corridor_id: "corridor:official",
              corridor_family: "named_urban_corridor",
              road_id: "road:5",
              primary_ref: null,
              primary_name: "Coastal Spine",
              length_m: 840,
              build_basis: "named_identity",
              geometry: {
                type: "LineString",
                coordinates: [
                  [34.7, 32.05],
                  [34.72, 32.08],
                ],
              },
            },
          ],
        });
      }

      if (url.includes("/corridors/corridor%3Aofficial")) {
        return createJsonResponse({
          corridor_id: "corridor:official",
          corridor_family: "named_urban_corridor",
          road_id: "road:5",
          primary_ref: null,
          primary_name: "Coastal Spine",
          length_m: 840,
          atom_count: 4,
          build_basis: "named_identity",
          split_from_reason: "chain_segment",
          geometry: {
            type: "LineString",
            coordinates: [
              [34.7, 32.05],
              [34.72, 32.08],
            ],
          },
          build_description:
            "Built from connected OSM segments merged by the stable street name Coastal Spine.",
          road: {
            road_id: "road:5",
            road_identity_type: "name",
            primary_ref: null,
            primary_name: "Coastal Spine",
            component_count: 1,
            atom_count: 4,
          },
          official_link_summary: {
            official_segment_count: 2,
            link_method_breakdown: { same_ref_anchor: 2 },
            link_strength_breakdown: { strong: 2 },
            links: [
              {
                official_segment_id: "official:1",
                segment_key: "4-12",
                road_number: "4",
                link_method: "same_ref_anchor",
                link_strength: "strong",
                source_match_confidence: "high",
                distance_m: 4.0,
                is_multi_target: false,
              },
              {
                official_segment_id: "official:2",
                segment_key: "4-13",
                road_number: "4",
                link_method: "same_ref_anchor",
                link_strength: "strong",
                source_match_confidence: "high",
                distance_m: 6.0,
                is_multi_target: false,
              },
            ],
          },
        });
      }

      if (url.includes("/corridors?bbox=34%2C29.4%2C36%2C33.5")) {
        return createJsonResponse({
          bbox: { min_lon: 34, min_lat: 29.4, max_lon: 36, max_lat: 33.5 },
          max_results: 250,
          returned_count: 2,
          truncated: false,
          corridors: [
            {
              corridor_id: "corridor:1",
              corridor_family: "ref_road_corridor",
              road_id: "road:1",
              primary_ref: "4",
              primary_name: null,
              length_m: 1200,
              build_basis: "ref_identity",
              geometry: {
                type: "LineString",
                coordinates: [
                  [34.8, 32.0],
                  [34.81, 32.01],
                ],
              },
            },
            {
              corridor_id: "corridor:2",
              corridor_family: "local_unnamed_corridor",
              road_id: null,
              primary_ref: null,
              primary_name: "Market Lane",
              length_m: 180,
              build_basis: "local_connectivity",
              geometry: {
                type: "LineString",
                coordinates: [
                  [34.9, 32.1],
                  [34.91, 32.11],
                ],
              },
            },
          ],
        });
      }

      throw new Error(`Unexpected request: ${url}`);
    });

    const client = createCanonicalNetworkClient({ fetchImpl: fetchImpl as typeof fetch });
    render(<CanonicalNetworkPage client={client} />);

    expect(await screen.findByText("597,661")).toBeTruthy();
    expect(await screen.findByText("17,929")).toBeTruthy();
    expect(await screen.findByText("362,922")).toBeTruthy();
    expect(await screen.findByText("840")).toBeTruthy();
    expect(
      await screen.findByText("4 official segments remain unlinked"),
    ).toBeTruthy();

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledWith(
        "/api/canonical-network/summary",
        expect.objectContaining({
          headers: { Accept: "application/json" },
        }),
      );
    });
    expect(await screen.findByText("Market Lane")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("Road identity"), "without-road");
    expect(screen.getByText("Market Lane")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "4 ref_road_corridor" }),
    ).toBeNull();

    await user.selectOptions(screen.getByLabelText("Road identity"), "all");
    await user.click(screen.getByRole("button", { name: "Coastal focus" }));

    expect(await screen.findByText("Coastal Spine")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Coastal Spine named_urban_corridor" }));

    expect(
      await screen.findByText("Built from connected OSM segments merged by the stable street name Coastal Spine."),
    ).toBeTruthy();
    expect(
      await screen.findByText("2 official segment links are attached to this corridor."),
    ).toBeTruthy();
  });
});
