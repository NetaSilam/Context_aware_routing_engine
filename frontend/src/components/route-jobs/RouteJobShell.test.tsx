import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => <div {...props}>{children}</div>,
  TileLayer: () => null,
  Polyline: ({ positions }: { positions: unknown }) => <span data-route-line={JSON.stringify(positions)} />,
}));

import RouteJobShell, { type RouteJobShellStatus } from "./RouteJobShell";
import type { RouteJobResult } from "../../types/routeJobs";

afterEach(cleanup);

describe("RouteJobShell", () => {
  it.each<[RouteJobShellStatus, string]>([
    ["empty", "No route job yet"],
    ["submitting", "Submitting route job"],
    ["polling", "Route job in progress"],
    ["completed", "Route job completed"],
    ["failed", "Route job failed"],
  ])("renders the %s state boundary", (status, heading) => {
    render(<RouteJobShell status={status} error="Upstream routing unavailable." />);

    const shell = screen.getByRole("region", { name: "Route job" });
    expect(shell.getAttribute("data-route-job-state")).toBe(status);
    expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
  });

  it("renders a controlled failure message", () => {
    render(<RouteJobShell status="failed" error="Upstream routing unavailable." />);

    expect(screen.getByText("Upstream routing unavailable.")).toBeTruthy();
  });

  it("renders one route honestly with the warning and explanatory metrics", () => {
    const result: RouteJobResult = {
      schema_version: "route-result-v1", chosen_index: 0, risk_choice_available: false,
      safety_weight: 0.4, time_weight: 0.6, safety_factor_contributions: { base: 0.4 },
      reference_risk_p95: 2, low_coverage_threshold: 0.8,
      risk_data_version: "risk-v1", formula_version: "formula-v1", matcher_version: "matcher-v1",
      graph_version: "graph-v1", included_year_start: 2020, included_year_end: 2023,
      risk_metric_name: "historical_accident_density_per_km",
      risk_metric_description: "Historical accident density is a historical risk proxy.",
      candidates: [{
        candidate_index: 0, distance_m: 1000, duration_seconds: 120,
        matched_route_length_m: 500, accident_score: 1,
        historical_accident_density_per_km: 2, coverage: 0.5,
        warning: "Historical accident density is based on incomplete corridor coverage.",
        time_penalty: 0, normalized_risk: 1, time_contribution: 0,
        safety_contribution: 0.4, final_cost: 0.4,
        geometry: { type: "LineString", coordinates: [[34.78, 32.07], [34.79, 32.08]] },
      }],
    };
    render(<RouteJobShell status="completed" result={result} />);

    expect(screen.getByText(/Only one route was available/)).toBeTruthy();
    expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Route result map")).toBeTruthy();
    expect(screen.getByText("Historical accident density")).toBeTruthy();
    expect(screen.getByText(/formula-v1 \/ risk-v1 \/ matcher-v1 \/ graph-v1/)).toBeTruthy();
  });

  it("shows the LLM route explanation once it has been generated", () => {
    const result: RouteJobResult = {
      schema_version: "route-result-v1", chosen_index: 0, risk_choice_available: true,
      safety_weight: 0.4, time_weight: 0.6, safety_factor_contributions: { base: 0.4 },
      reference_risk_p95: 2, low_coverage_threshold: 0.8,
      risk_data_version: "risk-v1", formula_version: "formula-v1", matcher_version: "matcher-v1",
      graph_version: "graph-v1", included_year_start: 2020, included_year_end: 2023,
      risk_metric_name: "historical_accident_density_per_km",
      risk_metric_description: "Historical accident density is a historical risk proxy.",
      candidates: [{
        candidate_index: 0, distance_m: 1000, duration_seconds: 120,
        matched_route_length_m: 1000, accident_score: 1,
        historical_accident_density_per_km: 2, coverage: 1,
        warning: null,
        time_penalty: 0, normalized_risk: 1, time_contribution: 0,
        safety_contribution: 0.4, final_cost: 0.4,
        geometry: { type: "LineString", coordinates: [[34.78, 32.07], [34.79, 32.08]] },
      }],
    };

    const { rerender } = render(<RouteJobShell status="completed" result={result} llmExplanation={null} />);
    expect(screen.queryByText(/shortest safe route/)).toBeNull();

    rerender(
      <RouteJobShell
        status="completed"
        result={result}
        llmExplanation="This is the shortest safe route given current conditions."
      />,
    );
    expect(screen.getByText("This is the shortest safe route given current conditions.")).toBeTruthy();
    // Never gates the rest of the result on the explanation being present.
    expect(screen.getByLabelText("Route result map")).toBeTruthy();
    expect(screen.getByText("Historical accident density")).toBeTruthy();
  });
});
