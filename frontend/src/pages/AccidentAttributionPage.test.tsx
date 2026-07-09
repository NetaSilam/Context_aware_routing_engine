import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createAccidentAttributionClient,
  type BBoxQuery,
} from "../api/accidentAttribution";
import AccidentAttributionPage from "./AccidentAttributionPage";

let mockBounds = {
  west: 34.8,
  south: 31.8,
  east: 35.1,
  north: 32.15,
};
let moveEndHandler: (() => void) | undefined;

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="mock-map">{children}</div>
  ),
  TileLayer: () => null,
  CircleMarker: ({
    eventHandlers,
  }: {
    eventHandlers?: { click?: () => void };
  }) => <button type="button" onClick={eventHandlers?.click}>marker</button>,
  useMap: () => ({
    fitBounds: vi.fn((bounds: [[number, number], [number, number]]) => {
      mockBounds = {
        west: bounds[0][1],
        south: bounds[0][0],
        east: bounds[1][1],
        north: bounds[1][0],
      };
      moveEndHandler?.();
    }),
    getBounds: () => ({
      getWest: () => mockBounds.west,
      getSouth: () => mockBounds.south,
      getEast: () => mockBounds.east,
      getNorth: () => mockBounds.north,
    }),
  }),
  useMapEvents: (handlers: { moveend?: () => void }) => {
    moveEndHandler = handlers.moveend;
    return null;
  },
}));

function createMockClient() {
  const getSummary = vi.fn().mockResolvedValue({
    attribution_version: "todo2-attribution-v1",
    total_accident_count: 8315,
    review_needed_count: 2123,
    status_breakdown: {
      assigned: 5120,
      assigned_with_warnings: 2840,
      unresolved: 355,
    },
    confidence_breakdown: {
      high: 5120,
      medium: 1800,
      low: 1040,
      unresolved: 355,
    },
    unresolved_reason_breakdown: {
      missing_geometry: 10,
      no_candidate_within_radius: 345,
    },
    official_reference_effect_breakdown: {
      strong_support: 3200,
      support: 1800,
      conflict: 340,
      strong_conflict: 80,
      not_available: 2895,
    },
    assigned_rate: 0.6158,
    assigned_with_warnings_rate: 0.3415,
    unresolved_rate: 0.0427,
  });

  const nationwideAccidents = [
    {
      accident_id: "2024-1",
      accident_year: 2024,
      severity: 3,
      road_number: "4",
      corridor_id: "corridor:1",
      road_id: "road:1",
      corridor_label: "4",
      attribution_status: "assigned",
      confidence_tier: "high",
      confidence_reason_code: "distance_high",
      geometry: {
        type: "Point" as const,
        coordinates: [34.82, 32.06] as [number, number],
      },
    },
    {
      accident_id: "2024-2",
      accident_year: 2024,
      severity: 2,
      road_number: null,
      corridor_id: "corridor:2",
      road_id: null,
      corridor_label: "Market Lane",
      attribution_status: "assigned_with_warnings",
      confidence_tier: "low",
      confidence_reason_code: "weak_corridor_construction",
      geometry: {
        type: "Point" as const,
        coordinates: [35.0, 31.9] as [number, number],
      },
    },
  ];

  const centralAccidents = [
    {
      accident_id: "2024-3",
      accident_year: 2024,
      severity: 1,
      road_number: "20",
      corridor_id: null,
      road_id: null,
      corridor_label: null,
      attribution_status: "unresolved",
      confidence_tier: "unresolved",
      confidence_reason_code: "no_candidate_within_radius",
      geometry: {
        type: "Point" as const,
        coordinates: [34.9, 32.0] as [number, number],
      },
    },
  ];

  const getAccidents = vi.fn(
    async (bbox: BBoxQuery, filters?: { status?: string; confidence?: string; year?: number }) => {
      const source = bbox.minLon >= 34.7 ? centralAccidents : nationwideAccidents;
      const filtered = source.filter((accident) => {
        if (filters?.status && accident.attribution_status !== filters.status) {
          return false;
        }
        if (filters?.confidence && accident.confidence_tier !== filters.confidence) {
          return false;
        }
        if (filters?.year && accident.accident_year !== filters.year) {
          return false;
        }
        return true;
      });
      return {
        bbox: {
          min_lon: bbox.minLon,
          min_lat: bbox.minLat,
          max_lon: bbox.maxLon,
          max_lat: bbox.maxLat,
        },
        max_results: 400,
        returned_count: filtered.length,
        truncated: false,
        accidents: filtered,
      };
    },
  );

  const getAccidentDetail = vi.fn(async (accidentId: string) => ({
    accident: {
      accident_id: accidentId,
      accident_year: 2024,
      severity: accidentId === "2024-3" ? 1 : 2,
      road_number: accidentId === "2024-3" ? "20" : null,
      locality_code: 3000,
      geographic_domain: 1,
      geometry: {
        type: "Point" as const,
        coordinates: [34.9, 32.0] as [number, number],
      },
    },
    attribution: {
      corridor_id: accidentId === "2024-3" ? null : "corridor:2",
      corridor_family: accidentId === "2024-3" ? null : "local_unnamed_corridor",
      road_id: null,
      corridor_primary_ref: null,
      corridor_primary_name: accidentId === "2024-3" ? null : "Market Lane",
      attribution_status:
        accidentId === "2024-3" ? "unresolved" : "assigned_with_warnings",
      confidence_tier: accidentId === "2024-3" ? "unresolved" : "low",
      assignment_method:
        accidentId === "2024-3"
          ? "unresolved_no_candidate_within_radius"
          : "nearest_corridor",
      unresolved_reason: accidentId === "2024-3" ? "no_candidate_within_radius" : null,
      confidence_reason_code:
        accidentId === "2024-3"
          ? "no_candidate_within_radius"
          : "weak_corridor_construction",
      review_needed: true,
      distance_to_corridor_m: accidentId === "2024-3" ? null : 18.4,
      second_best_distance_m: accidentId === "2024-3" ? null : 27.1,
      official_reference_effect: "not_available",
      attribution_version: "todo2-attribution-v1",
    },
    diagnostics:
      accidentId === "2024-3"
        ? { candidate_count_within_radius: 0 }
        : { secondary_reason_codes: ["distance_far"] },
    explanation_snippets:
      accidentId === "2024-3"
        ? ["No corridor fell inside the configured search radius."]
        : ["Upstream corridor construction quality limited confidence."],
  }));

  return {
    getSummary,
    getAccidents,
    getAccidentDetail,
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
  mockBounds = {
    west: 34.8,
    south: 31.8,
    east: 35.1,
    north: 32.15,
  };
  moveEndHandler = undefined;
  cleanup();
});

describe("AccidentAttributionPage", () => {
  it("renders summary, filters visible accidents, refetches on focus change, and opens detail", async () => {
    const user = userEvent.setup();
    const client = createMockClient();

    render(<AccidentAttributionPage client={client} />);

    expect(await screen.findByText("Total Accidents")).toBeTruthy();
    expect(await screen.findByText("8,315")).toBeTruthy();

    await waitFor(() => {
      expect(client.getAccidents).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("Market Lane")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("Confidence tier"), "low");
    await waitFor(() => {
      expect(client.getAccidents).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByText("Market Lane")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    await user.click(screen.getByRole("button", { name: "Central focus" }));
    await waitFor(() => {
      expect(client.getAccidents).toHaveBeenCalledTimes(4);
    });
    expect(await screen.findByRole("button", { name: /unresolved/ })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /unresolved/ }));
    await waitFor(() => {
      expect(client.getAccidentDetail).toHaveBeenCalledWith("2024-3");
    });
    expect(
      await screen.findByText("No corridor fell inside the configured search radius."),
    ).toBeTruthy();
    expect(client.getAccidents).toHaveBeenCalledTimes(4);
  });

  it("runs through the typed client contract with bbox, filters, and detail parsing", async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn(
      async (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.endsWith("/summary")) {
          return createJsonResponse({
            attribution_version: "todo2-attribution-v1",
            total_accident_count: 8315,
            review_needed_count: 2123,
            status_breakdown: {
              assigned: 5120,
              assigned_with_warnings: 2840,
              unresolved: 355,
            },
            confidence_breakdown: {
              high: 5120,
              medium: 1800,
              low: 1040,
              unresolved: 355,
            },
            unresolved_reason_breakdown: {
              missing_geometry: 10,
              no_candidate_within_radius: 345,
            },
            official_reference_effect_breakdown: {
              strong_support: 3200,
              support: 1800,
              conflict: 340,
              strong_conflict: 80,
              not_available: 2895,
            },
            assigned_rate: 0.6158,
            assigned_with_warnings_rate: 0.3415,
            unresolved_rate: 0.0427,
          });
        }

        if (url.includes("/accidents?bbox=34.7%2C31.7%2C35.3%2C32.3")) {
          return createJsonResponse({
            bbox: { min_lon: 34.7, min_lat: 31.7, max_lon: 35.3, max_lat: 32.3 },
            max_results: 400,
            returned_count: 1,
            truncated: false,
            accidents: [
              {
                accident_id: "2024-3",
                accident_year: 2024,
                severity: 1,
                road_number: "20",
                corridor_id: null,
                road_id: null,
                corridor_label: null,
                attribution_status: "unresolved",
                confidence_tier: "unresolved",
                confidence_reason_code: "no_candidate_within_radius",
                geometry: {
                  type: "Point",
                  coordinates: [34.9, 32.0],
                },
              },
            ],
          });
        }

        if (url.includes("/accidents/2024-3")) {
          return createJsonResponse({
            accident: {
              accident_id: "2024-3",
              accident_year: 2024,
              severity: 1,
              road_number: "20",
              locality_code: 3000,
              geographic_domain: 1,
              geometry: {
                type: "Point",
                coordinates: [34.9, 32.0],
              },
            },
            attribution: {
              corridor_id: null,
              corridor_family: null,
              road_id: null,
              corridor_primary_ref: null,
              corridor_primary_name: null,
              attribution_status: "unresolved",
              confidence_tier: "unresolved",
              assignment_method: "unresolved_no_candidate_within_radius",
              unresolved_reason: "no_candidate_within_radius",
              confidence_reason_code: "no_candidate_within_radius",
              review_needed: true,
              distance_to_corridor_m: null,
              second_best_distance_m: null,
              official_reference_effect: "not_available",
              attribution_version: "todo2-attribution-v1",
            },
            diagnostics: {
              candidate_count_within_radius: 0,
            },
            explanation_snippets: ["No corridor fell inside the configured search radius."],
          });
        }

        if (url.includes("/accidents?bbox=34%2C29.4%2C36%2C33.5")) {
          return createJsonResponse({
            bbox: { min_lon: 34, min_lat: 29.4, max_lon: 36, max_lat: 33.5 },
            max_results: 400,
            returned_count: 2,
            truncated: false,
            accidents: [
              {
                accident_id: "2024-1",
                accident_year: 2024,
                severity: 3,
                road_number: "4",
                corridor_id: "corridor:1",
                road_id: "road:1",
                corridor_label: "4",
                attribution_status: "assigned",
                confidence_tier: "high",
                confidence_reason_code: "distance_high",
                geometry: {
                  type: "Point",
                  coordinates: [34.82, 32.06],
                },
              },
              {
                accident_id: "2024-2",
                accident_year: 2024,
                severity: 2,
                road_number: null,
                corridor_id: "corridor:2",
                road_id: null,
                corridor_label: "Market Lane",
                attribution_status: "assigned_with_warnings",
                confidence_tier: "low",
                confidence_reason_code: "weak_corridor_construction",
                geometry: {
                  type: "Point",
                  coordinates: [35.0, 31.9],
                },
              },
            ],
          });
        }

        throw new Error(`Unexpected request: ${url}`);
      },
    );

    const client = createAccidentAttributionClient({ fetchImpl: fetchImpl as typeof fetch });
    render(<AccidentAttributionPage client={client} />);

    expect(await screen.findByText("5,120")).toBeTruthy();
    expect(await screen.findByText("2,840")).toBeTruthy();
    expect(await screen.findByText("355")).toBeTruthy();
    expect(await screen.findByText("Market Lane")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Central focus" }));
    await user.click(screen.getByRole("button", { name: /unresolved/ }));
    expect(await screen.findByText("No corridor fell inside the configured search radius.")).toBeTruthy();
  });
});
