import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => <div {...props}>{children}</div>,
  TileLayer: () => null,
  Polyline: ({ positions }: { positions: unknown }) => <span data-route-line={JSON.stringify(positions)} />,
}));

import PlanRoutePage from "./PlanRoutePage";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState({}, "", "/");
  cleanup();
});

const profile = { id: 1, email: "driver@example.com", driving_experience: "experienced" as const, vehicle_type: "car" as const, avoid_tolls: false, avoid_highways: false };

describe("PlanRoutePage", () => {
  it("renders the authenticated profile and asynchronous route shell", () => {
    render(<PlanRoutePage user={profile} onProfileUpdated={() => undefined} />);

    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getByText(/driver@example.com/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Route job" })).toBeTruthy();
  });

  it("updates the allowed route preferences through the authenticated API", async () => {
    const user = userEvent.setup();
    const updated = { ...profile, driving_experience: "novice" as const, vehicle_type: "truck" as const, avoid_tolls: true, avoid_highways: true };
    const onProfileUpdated = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(updated), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<PlanRoutePage user={profile} onProfileUpdated={onProfileUpdated} />);

    await user.click(screen.getByRole("button", { name: "Edit route preferences" }));
    await user.selectOptions(screen.getByLabelText("Driving experience"), "novice");
    await user.selectOptions(screen.getByLabelText("Vehicle type"), "truck");
    await user.click(screen.getByLabelText("Avoid highways"));
    await user.click(screen.getByLabelText("Avoid tolls"));
    await user.click(screen.getByRole("button", { name: "Save preferences" }));

    await waitFor(() => expect(onProfileUpdated).toHaveBeenCalledWith(updated));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({ method: "PATCH", credentials: "include" }),
    );
  });

  it("submits once, puts the job in the URL, and renders the persisted completion", async () => {
    const user = userEvent.setup();
    const completedJob = {
      id: "53ed1123-13ca-41d2-80b6-d5e5383ff12b", status: "completed",
      origin_longitude: 34.78, origin_latitude: 32.07,
      destination_longitude: 34.79, destination_latitude: 32.08,
      origin_label: null, destination_label: null, created_at: new Date().toISOString(),
      started_at: new Date().toISOString(), completed_at: new Date().toISOString(),
      error_code: null, error_message: null,
      result: {
        schema_version: "route-result-v1", chosen_index: 0, risk_choice_available: true,
        safety_weight: 0.4, time_weight: 0.6, safety_factor_contributions: { base: 0.4 },
        reference_risk_p95: 2, low_coverage_threshold: 0.8,
        risk_data_version: "risk-v1", formula_version: "formula-v1", matcher_version: "matcher-v1", graph_version: "graph-v1",
        included_year_start: 2020, included_year_end: 2023,
        risk_metric_name: "historical_accident_density_per_km", risk_metric_description: "Historical accident density is a historical risk proxy.",
        candidates: [{ candidate_index: 0, distance_m: 1000, duration_seconds: 120, matched_route_length_m: 1000, accident_score: 1, historical_accident_density_per_km: 1, coverage: 1, warning: null, time_penalty: 0, normalized_risk: 0.5, time_contribution: 0, safety_contribution: 0.2, final_cost: 0.2, geometry: { type: "LineString", coordinates: [[34.78, 32.07], [34.79, 32.08]] } }],
      },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: completedJob.id, status: "queued" }), { status: 202, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(completedJob), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<PlanRoutePage user={profile} onProfileUpdated={() => undefined} />);

    await user.click(screen.getByRole("button", { name: "Compare routes" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Route job completed" })).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/route-jobs");
    expect(window.location.search).toContain(`routeJob=${completedJob.id}`);
    expect(screen.getByText(/Route 1 — recommended/)).toBeTruthy();
  });

  it("uses bounded polling delays and stops polling when unmounted", async () => {
    vi.useFakeTimers();
    const jobId = "53ed1123-13ca-41d2-80b6-d5e5383ff12b";
    window.history.replaceState({}, "", `/?routeJob=${jobId}`);
    const runningJob = {
      id: jobId, status: "running", origin_longitude: 34.78, origin_latitude: 32.07,
      destination_longitude: 34.79, destination_latitude: 32.08,
      origin_label: null, destination_label: null, created_at: new Date().toISOString(),
      started_at: new Date().toISOString(), completed_at: null,
      error_code: null, error_message: null, result: null,
    };
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify(runningJob), { status: 200, headers: { "Content-Type": "application/json" } }),
    ));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<PlanRoutePage user={profile} onProfileUpdated={() => undefined} />);

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(fetchMock).toHaveBeenCalledTimes(4);

    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});
