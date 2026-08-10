import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NotificationIndicator from "./NotificationIndicator";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function notificationPage(unreadCount: number) {
  return { items: [], offset: 0, limit: 30, has_more: false, unread_count: unreadCount };
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("NotificationIndicator", () => {
  it("fetches the unread count once the stream connection opens", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(notificationPage(3)));
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationIndicator />);

    const source = MockEventSource.instances[0];
    source.onopen?.();

    expect(await screen.findByText("3")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/notifications?"),
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("increments the unread count on each live event", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(notificationPage(1)));
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationIndicator />);

    const source = MockEventSource.instances[0];
    source.onopen?.();
    await screen.findByText("1");

    source.onmessage?.({ data: JSON.stringify({ kind: "new_dm" }) });
    expect(await screen.findByText("2")).toBeTruthy();

    source.onmessage?.({ data: JSON.stringify({ kind: "new_vote" }) });
    expect(await screen.findByText("3")).toBeTruthy();
  });

  it("re-fetches the unread count on every reconnect instead of trusting stale state", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(notificationPage(1)));
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationIndicator />);

    const source = MockEventSource.instances[0];
    source.onopen?.();
    await screen.findByText("1");

    // A dropped connection reconnects (the browser fires onopen again on the same
    // EventSource instance); a stale unread count must not survive a reconnect.
    fetchMock.mockResolvedValueOnce(jsonResponse(notificationPage(7)));
    source.onopen?.();

    expect(await screen.findByText("7")).toBeTruthy();
  });

  it("marks all notifications read and resets the badge when clicked", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/notifications?")) return Promise.resolve(jsonResponse(notificationPage(4)));
      if (url === "/api/notifications/read-all") return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationIndicator />);

    MockEventSource.instances[0].onopen?.();
    await screen.findByText("4");

    await user.click(screen.getByRole("button", { name: /notifications/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/notifications/read-all",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(screen.queryByText("4")).toBeNull();
  });

  it("closes the EventSource connection on unmount", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(notificationPage(0))));
    const view = render(<NotificationIndicator />);
    const source = MockEventSource.instances[0];

    view.unmount();

    expect(source.closed).toBe(true);
  });
});
