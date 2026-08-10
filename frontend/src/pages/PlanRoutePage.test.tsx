import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => <div {...props}>{children}</div>,
  TileLayer: () => null,
  Polyline: ({ positions }: { positions: unknown }) => <span data-route-line={JSON.stringify(positions)} />,
  Marker: () => null,
  useMapEvents: () => undefined,
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
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      new Response(JSON.stringify(String(input).startsWith("/api/route-history?")
        ? { items: [], offset: 0, limit: 10, has_more: false }
        : updated), { status: 200, headers: { "Content-Type": "application/json" } }),
    ));
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
      error_code: null, error_message: null, failure: null,
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
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/route-history?")) return Promise.resolve(new Response(JSON.stringify({ items: [], offset: 0, limit: 10, has_more: false }), { status: 200, headers: { "Content-Type": "application/json" } }));
      if (url === "/api/route-jobs" && init?.method === "POST") return Promise.resolve(new Response(JSON.stringify({ id: completedJob.id, status: "queued" }), { status: 202, headers: { "Content-Type": "application/json" } }));
      return Promise.resolve(new Response(JSON.stringify(completedJob), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PlanRoutePage user={profile} onProfileUpdated={() => undefined} />);

    await user.click(screen.getByRole("button", { name: "Compare routes" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Route job completed" })).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledWith("/api/route-jobs", expect.objectContaining({ headers: expect.objectContaining({
      "Idempotency-Key": expect.any(String),
    }) }));
    expect(window.location.search).toContain(`routeJob=${completedJob.id}`);
    expect(screen.getByText(/Route 1 — recommended/)).toBeTruthy();
    expect(screen.queryByText(/shortest safe route/)).toBeNull();
  });

  it("shows the LLM route explanation once it is present on the completed job", async () => {
    const user = userEvent.setup();
    const completedJob = {
      id: "53ed1123-13ca-41d2-80b6-d5e5383ff12b", status: "completed",
      origin_longitude: 34.78, origin_latitude: 32.07,
      destination_longitude: 34.79, destination_latitude: 32.08,
      origin_label: null, destination_label: null, created_at: new Date().toISOString(),
      started_at: new Date().toISOString(), completed_at: new Date().toISOString(),
      error_code: null, error_message: null, failure: null,
      llm_explanation: "This route avoids the corridor with the highest historical accident density.",
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
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/route-history?")) return Promise.resolve(new Response(JSON.stringify({ items: [], offset: 0, limit: 10, has_more: false }), { status: 200, headers: { "Content-Type": "application/json" } }));
      if (url === "/api/route-jobs" && init?.method === "POST") return Promise.resolve(new Response(JSON.stringify({ id: completedJob.id, status: "queued" }), { status: 202, headers: { "Content-Type": "application/json" } }));
      return Promise.resolve(new Response(JSON.stringify(completedJob), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PlanRoutePage user={profile} onProfileUpdated={() => undefined} />);

    await user.click(screen.getByRole("button", { name: "Compare routes" }));

    expect(await screen.findByText(
      "This route avoids the corridor with the highest historical accident density.",
    )).toBeTruthy();
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
      error_code: null, error_message: null, failure: null, result: null,
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      new Response(JSON.stringify(String(input).startsWith("/api/route-history?")
        ? { items: [], offset: 0, limit: 10, has_more: false }
        : runningJob), { status: 200, headers: { "Content-Type": "application/json" } }),
    ));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<PlanRoutePage user={profile} onProfileUpdated={() => undefined} />);

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const routeJobCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).startsWith("/api/route-jobs/"));
    expect(routeJobCalls()).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(routeJobCalls()).toHaveLength(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(routeJobCalls()).toHaveLength(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(routeJobCalls()).toHaveLength(4);

    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(routeJobCalls()).toHaveLength(4);
  });

  it("opens an exact history snapshot without submitting and reruns with a new key", async () => {
    const user = userEvent.setup();
    const savedId = "53ed1123-13ca-41d2-80b6-d5e5383ff12b";
    const rerunId = "63ed1123-13ca-41d2-80b6-d5e5383ff12b";
    const result = {
      schema_version: "route-result-v1", chosen_index: 0, risk_choice_available: false,
      safety_weight: 0.4, time_weight: 0.6, safety_factor_contributions: { base: 0.4 }, reference_risk_p95: 2,
      low_coverage_threshold: 0.8, risk_data_version: "old-risk", formula_version: "old-formula", matcher_version: "old-matcher", graph_version: "old-graph",
      included_year_start: 2020, included_year_end: 2023, risk_metric_name: "historical_accident_density_per_km", risk_metric_description: "Historical risk proxy.",
      candidates: [{ candidate_index: 0, distance_m: 1000, duration_seconds: 120, matched_route_length_m: 1000, accident_score: 1, historical_accident_density_per_km: 1, coverage: 1, warning: null, time_penalty: 0, normalized_risk: 0.5, time_contribution: 0, safety_contribution: 0.2, final_cost: 0.2, geometry: { type: "LineString", coordinates: [[34.78, 32.07], [34.79, 32.08]] } }],
    };
    const savedJob = { id: savedId, status: "completed", origin_longitude: 34.78, origin_latitude: 32.07, destination_longitude: 34.79, destination_latitude: 32.08, origin_label: "Saved origin", destination_label: "Saved destination", created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:01Z", completed_at: "2026-01-01T00:00:02Z", error_code: null, error_message: null, failure: null, result };
    const summary = { id: savedId, origin_label: "Saved origin", destination_label: "Saved destination", origin_longitude: 34.78, origin_latitude: 32.07, destination_longitude: 34.79, destination_latitude: 32.08, completed_at: "2026-01-01T00:00:02Z", chosen_index: 0, route_count: 1, distance_m: 1000, duration_seconds: 120, historical_accident_density_per_km: 1, coverage: 1, final_cost: 0.2, risk_choice_available: false };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/route-history?")) return Promise.resolve(new Response(JSON.stringify({ items: [summary], offset: 0, limit: 10, has_more: false }), { status: 200, headers: { "Content-Type": "application/json" } }));
      if (url.endsWith("/run-again") && init?.method === "POST") return Promise.resolve(new Response(JSON.stringify({ id: rerunId, status: "queued" }), { status: 202, headers: { "Content-Type": "application/json" } }));
      if (url === `/api/route-history/${savedId}`) return Promise.resolve(new Response(JSON.stringify(savedJob), { status: 200, headers: { "Content-Type": "application/json" } }));
      return Promise.resolve(new Response(JSON.stringify({ ...savedJob, id: rerunId, status: "running", result: null }), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PlanRoutePage user={profile} onProfileUpdated={() => undefined} />);

    await user.click(await screen.findByRole("button", { name: "Open saved result" }));
    expect(await screen.findByText(/old-formula \/ old-risk \/ old-matcher \/ old-graph/)).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url) === "/api/route-jobs" && init?.method === "POST")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/route-history/${savedId}/run-again`,
      expect.objectContaining({ headers: expect.objectContaining({ "Idempotency-Key": expect.any(String) }) }),
    ));
    expect(window.location.search).toContain(`routeJob=${rerunId}`);
  });
});
