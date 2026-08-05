import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import RouteHistoryPanel from "./RouteHistoryPanel";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  cleanup();
});

const unsafeLabel = '<img src=x onerror="alert(1)">';
const item = {
  id: "53ed1123-13ca-41d2-80b6-d5e5383ff12b",
  origin_label: unsafeLabel,
  destination_label: "Saved destination",
  origin_longitude: 34.78,
  origin_latitude: 32.07,
  destination_longitude: 34.79,
  destination_latitude: 32.08,
  completed_at: "2026-01-01T00:00:00Z",
  chosen_index: 0,
  route_count: 3,
  distance_m: 1000,
  duration_seconds: 120,
  historical_accident_density_per_km: 1.5,
  coverage: 0.9,
  final_cost: 0.2,
  risk_choice_available: true,
};

describe("RouteHistoryPanel", () => {
  it("renders labels as text, pages, and opens or reruns the selected snapshot", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn().mockResolvedValue(undefined);
    const onRunAgain = vi.fn().mockResolvedValue(undefined);
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const page = url.includes("offset=10")
        ? { items: [{ ...item, id: "63ed1123-13ca-41d2-80b6-d5e5383ff12b", origin_label: "Page two" }], offset: 10, limit: 10, has_more: false }
        : { items: [item], offset: 0, limit: 10, has_more: true };
      return Promise.resolve(new Response(JSON.stringify(page), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<RouteHistoryPanel refreshKey={null} onOpen={onOpen} onRunAgain={onRunAgain} />);

    expect(await screen.findByText(new RegExp(unsafeLabel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open saved result" }));
    await user.click(screen.getByRole("button", { name: "Run again" }));
    expect(onOpen).toHaveBeenCalledWith(item.id);
    expect(onRunAgain).toHaveBeenCalledWith(item.id);

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText(/Page two/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/route-history?offset=10&limit=10", { credentials: "include" });
  });

  it("requires confirmation for individual and clear deletion", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.fn().mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.resolve(new Response(JSON.stringify({ items: [item], offset: 0, limit: 10, has_more: false }), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<RouteHistoryPanel refreshKey={null} onOpen={async () => undefined} onRunAgain={async () => undefined} />);

    await screen.findByRole("button", { name: "Delete" });
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/route-history/${item.id}`,
      expect.objectContaining({ method: "DELETE" }),
    ));

    cleanup();
    render(<RouteHistoryPanel refreshKey="refresh" onOpen={async () => undefined} onRunAgain={async () => undefined} />);
    await screen.findByRole("button", { name: "Clear history" });
    await user.click(screen.getByRole("button", { name: "Clear history" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/route-history",
      expect.objectContaining({ method: "DELETE" }),
    ));
  });
});
