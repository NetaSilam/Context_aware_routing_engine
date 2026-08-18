import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let capturedInteractionStart: (() => void) | null = null;

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => <div {...props}>{children}</div>,
  TileLayer: () => null,
  Polyline: ({ positions }: { positions: unknown }) => <span data-route-line={JSON.stringify(positions)} />,
  Marker: ({ position }: { position: unknown }) => <span data-marker={JSON.stringify(position)} />,
  useMap: () => ({ setView: vi.fn(), getZoom: () => 16, invalidateSize: vi.fn() }),
  useMapEvents: (handlers: { dragstart?: () => void; zoomstart?: () => void }) => {
    capturedInteractionStart = handlers.dragstart ?? handlers.zoomstart ?? null;
  },
}));

vi.mock("../api/forum", () => ({
  listNearbyPosts: vi.fn().mockResolvedValue({ items: [], offset: 0, limit: 50, has_more: false }),
}));

const { rerouteMock, MockRerouteError } = vi.hoisted(() => {
  class MockRerouteError extends Error {
    retryable: boolean;
    constructor(message: string, retryable: boolean) {
      super(message);
      this.retryable = retryable;
    }
  }
  return { rerouteMock: vi.fn(), MockRerouteError };
});
vi.mock("../api/liveRouting", () => ({
  reroute: (...args: unknown[]) => rerouteMock(...args),
  RerouteError: MockRerouteError,
}));

import NavigatePage from "./NavigatePage";
import { listNearbyPosts } from "../api/forum";
import type { NavigationHandoff } from "../types/navigation";
import type { RouteCandidateResult } from "../types/routeJobs";

class StubEventSource {
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
}

let watchSuccess: ((position: { coords: { latitude: number; longitude: number } }) => void) | null = null;
let watchError: ((error: { code: number; PERMISSION_DENIED: number }) => void) | null = null;
const clearWatchMock = vi.fn();

function stubGeolocation(): void {
  Object.defineProperty(global.navigator, "geolocation", {
    configurable: true,
    value: {
      watchPosition: vi.fn((success, error) => {
        watchSuccess = success;
        watchError = error;
        return 1;
      }),
      clearWatch: clearWatchMock,
    },
  });
}

function candidateFixture(overrides: Partial<RouteCandidateResult> = {}): RouteCandidateResult {
  return {
    candidate_index: 0,
    distance_m: 1000,
    duration_seconds: 180,
    matched_route_length_m: 1000,
    accident_score: 1,
    historical_accident_density_per_km: 1,
    coverage: 1,
    warning: null,
    time_penalty: 0,
    normalized_risk: 0.5,
    time_contribution: 0,
    safety_contribution: 0.2,
    final_cost: 0.2,
    geometry: { type: "LineString", coordinates: [[34.78, 32.07], [34.79, 32.08]] },
    steps: [
      {
        distance: 200,
        duration: 30,
        name: "Test St",
        maneuver: { type: "turn", modifier: "left", location: [34.785, 32.075] },
      },
      { distance: 0, duration: 0, name: "", maneuver: { type: "arrive", modifier: null, location: null } },
    ],
    ...overrides,
  };
}

function handoffFixture(): NavigationHandoff {
  return {
    candidate: candidateFixture(),
    destinationLongitude: 34.79,
    destinationLatitude: 32.08,
    scoringContext: {
      driving_experience: "novice",
      vehicle_type: "car",
      avoid_tolls: false,
      avoid_highways: false,
      reference_risk_p95: 3,
      risk_data_version: "risk-v1",
    },
  };
}

beforeEach(() => {
  watchSuccess = null;
  watchError = null;
  capturedInteractionStart = null;
  clearWatchMock.mockClear();
  rerouteMock.mockReset();
  vi.mocked(listNearbyPosts).mockReset();
  vi.mocked(listNearbyPosts).mockResolvedValue({ items: [], offset: 0, limit: 50, has_more: false });
  vi.stubGlobal("EventSource", StubEventSource);
  stubGeolocation();
  // Each test should start with a fresh session, not resume progress a previous
  // test's NavigatePage instance persisted for session-resume-after-refresh support.
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  cleanup();
});

describe("NavigatePage", () => {
  it("renders the first turn-by-turn instruction from the handoff before any GPS fix", () => {
    render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);
    expect(screen.getByText("In 200m, turn left onto Test St")).toBeTruthy();
  });

  it("greets the driver and reads the first step aloud on start", () => {
    const speak = vi.fn();
    vi.stubGlobal("speechSynthesis", { cancel: vi.fn(), speak });
    vi.stubGlobal(
      "SpeechSynthesisUtterance",
      vi.fn().mockImplementation((text: string) => ({ text })),
    );

    render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);

    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0][0].text).toBe(
      "Ready? Let's go. In 200m, turn left onto Test St",
    );
  });

  it("shows a fixed center arrow once a GPS fix is available, not before", () => {
    const { container } = render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);
    expect(container.querySelector(".nav-page__center-arrow")).toBeNull();

    act(() => watchSuccess!({ coords: { latitude: 32.07, longitude: 34.78 } }));

    expect(container.querySelector(".nav-page__center-arrow")).toBeTruthy();
  });

  it("drops into free-look (recenter button, hidden arrow) when the map is dragged or zoomed, and returns to follow mode on recenter", async () => {
    const user = userEvent.setup();
    const { container } = render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);
    act(() => watchSuccess!({ coords: { latitude: 32.07, longitude: 34.78 } }));

    expect(container.querySelector(".nav-page__center-arrow")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Recenter on my location" })).toBeNull();

    expect(capturedInteractionStart).toBeTruthy();
    act(() => capturedInteractionStart!());

    expect(container.querySelector(".nav-page__center-arrow")).toBeNull();
    const recenterButton = screen.getByRole("button", { name: "Recenter on my location" });

    await user.click(recenterButton);

    expect(screen.queryByRole("button", { name: "Recenter on my location" })).toBeNull();
    expect(container.querySelector(".nav-page__center-arrow")).toBeTruthy();
  });

  it("calls onExit when End navigation is clicked", async () => {
    const user = userEvent.setup();
    const onExit = vi.fn();
    render(<NavigatePage handoff={handoffFixture()} onExit={onExit} />);

    await user.click(screen.getByRole("button", { name: "End navigation" }));
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it("shows a denied-permission banner instead of crashing when geolocation is denied", () => {
    render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);

    expect(watchError).toBeTruthy();
    act(() => watchError!({ code: 1, PERMISSION_DENIED: 1 }));

    expect(screen.getByRole("alert").textContent).toMatch(/Location access was denied/);
  });

  it("shows an unsupported banner when the browser has no geolocation API", () => {
    Object.defineProperty(global.navigator, "geolocation", { configurable: true, value: undefined });
    render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);

    expect(screen.getByRole("alert").textContent).toMatch(/does not support live location/);
  });

  it("triggers a reroute after enough consecutive off-route readings and updates the active route on success", async () => {
    const rerouted = candidateFixture({
      candidate_index: 1,
      geometry: { type: "LineString", coordinates: [[34.90, 32.20], [34.91, 32.21]] },
      steps: [
        { distance: 50, duration: 10, name: "New Rd", maneuver: { type: "turn", modifier: "right", location: [34.905, 32.205] } },
      ],
    });
    rerouteMock.mockResolvedValue({
      schema_version: "reroute-result-v1",
      chosen_index: 1,
      risk_choice_available: true,
      candidates: [rerouted],
      safety_weight: 0.4,
      time_weight: 0.6,
      formula_version: "route-scoring-v1",
      risk_data_version: "risk-v2",
    });

    render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);

    const offRoutePosition = { coords: { latitude: 32.20, longitude: 34.90 } };
    act(() => {
      watchSuccess!(offRoutePosition);
      watchSuccess!(offRoutePosition);
      watchSuccess!(offRoutePosition); // third consecutive off-route tick trips the debounce
    });

    await waitFor(() => expect(rerouteMock).toHaveBeenCalledTimes(1));
    expect(rerouteMock).toHaveBeenCalledWith(
      expect.objectContaining({
        current_longitude: 34.90,
        current_latitude: 32.20,
        destination_longitude: 34.79,
        destination_latitude: 32.08,
        scoring_context: handoffFixture().scoringContext,
      }),
    );
    // Distance in the instruction is computed live from GPS position to the maneuver
    // location, not the raw OSRM `step.distance` field, so match on the maneuver itself.
    await waitFor(() => expect(screen.getByText(/turn right onto New Rd/)).toBeTruthy());
  });

  it("keeps the last known route visible and shows a banner when a reroute fails", async () => {
    rerouteMock.mockRejectedValue(new MockRerouteError("The routing service is unavailable.", true));

    render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);
    // Original instruction must still be showing before we drive off-route.
    expect(screen.getByText(/turn left onto Test St/)).toBeTruthy();

    const offRoutePosition = { coords: { latitude: 32.20, longitude: 34.90 } };
    watchSuccess!(offRoutePosition);
    watchSuccess!(offRoutePosition);
    watchSuccess!(offRoutePosition);

    await waitFor(() => expect(rerouteMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByText("The routing service is unavailable.")).toBeTruthy(),
    );
    // The pre-failure route/instruction (same maneuver/street) is still displayed, not
    // cleared — only its live distance-to-maneuver updates as position changes.
    expect(screen.getByText(/turn left onto Test St/)).toBeTruthy();
  });

  it("does not reroute on a single noisy off-route reading", async () => {
    render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);

    watchSuccess!({ coords: { latitude: 32.20, longitude: 34.90 } });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(rerouteMock).not.toHaveBeenCalled();
  });

  it("shows arrival text and exits automatically once within range of the destination", () => {
    vi.useFakeTimers();
    const onExit = vi.fn();
    render(<NavigatePage handoff={handoffFixture()} onExit={onExit} />);

    act(() => watchSuccess!({ coords: { latitude: 32.08, longitude: 34.79 } })); // == destination

    expect(screen.getByText("Arrived at your destination")).toBeTruthy();
    expect(onExit).not.toHaveBeenCalled();

    vi.advanceTimersByTime(3000);
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it("toggles the mute button label", async () => {
    const user = userEvent.setup();
    render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);

    const button = screen.getByRole("button", { name: "Mute" });
    await user.click(button);
    expect(screen.getByRole("button", { name: "Unmute" })).toBeTruthy();
  });

  it("stops watching geolocation on unmount", () => {
    const { unmount } = render(<NavigatePage handoff={handoffFixture()} onExit={vi.fn()} />);
    unmount();
    expect(clearWatchMock).toHaveBeenCalledWith(1);
  });
});
