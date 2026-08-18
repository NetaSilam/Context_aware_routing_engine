import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const profile = {
  id: 1,
  email: "driver@example.com",
  driving_experience: "experienced",
  vehicle_type: "car",
  avoid_tolls: false,
  avoid_highways: false,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

class StubEventSource {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close(): void {
    // no-op; the notification indicator only needs a connection to open and close cleanly
  }
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(profile)));
  vi.stubGlobal("EventSource", StubEventSource);
  // Each test should start with no in-progress navigation session persisted by a
  // previous test's App instance.
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("App", () => {
  it("requires login before rendering any application page", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "Authentication required." }, 401));
    render(<App initialPage="canonical-network" pages={{ "canonical-network": <div>Private explorer</div> }} />);

    expect(await screen.findByRole("region", { name: "Sign in or create an account" })).toBeTruthy();
    expect(screen.queryByText("Private explorer")).toBeNull();
  });

  it("switches between pages after cookie authentication is loaded", async () => {
    const user = userEvent.setup();
    render(
      <App
        initialPage="canonical-network"
        pages={{
          "canonical-network": <div>Canonical network page</div>,
          "accident-attribution": <div>Accident attribution page</div>,
        }}
      />,
    );

    expect(await screen.findByText("Canonical network page")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Accident Attribution" }));
    expect(screen.getByText("Accident attribution page")).toBeTruthy();
  });

  it("logs out through the server and returns to the login gate", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(profile))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<App pages={{ "plan-route": <div>Plan a route page</div> }} />);

    await screen.findByText("Plan a route page");
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "Sign in or create an account" })).toBeTruthy());
    expect(vi.mocked(fetch)).toHaveBeenLastCalledWith(
      "/api/auth/logout",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });
});
