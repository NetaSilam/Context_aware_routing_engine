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

function notificationPage(unreadCount: number, items: unknown[] = []) {
  return { items, offset: 0, limit: 30, has_more: false, unread_count: unreadCount };
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

  it("opens a panel listing notifications when the toggle is clicked", async () => {
    const user = userEvent.setup();
    const items = [
      { id: "n1", kind: "new_dm", payload: { sender_email: "driver@example.com" }, created_at: "2026-01-01T00:00:00Z", read_at: null },
      { id: "n2", kind: "new_comment", payload: { actor_label: "reporter@example.com" }, created_at: "2026-01-01T00:00:00Z", read_at: null },
      { id: "n3", kind: "new_vote", payload: { target_type: "post", value: "up" }, created_at: "2026-01-01T00:00:00Z", read_at: "2026-01-01T00:00:00Z" },
    ];
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/notifications?")) return Promise.resolve(jsonResponse(notificationPage(2, items)));
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationIndicator />);

    MockEventSource.instances[0].onopen?.();
    await screen.findByText("2");

    await user.click(screen.getByRole("button", { name: /notifications/i }));

    expect(await screen.findByText("New message from driver@example.com")).toBeTruthy();
    expect(screen.getByText("reporter@example.com commented on your report")).toBeTruthy();
    expect(screen.getByText("Someone upvoted your report")).toBeTruthy();
  });

  it("marks an individual unread notification as read when clicked", async () => {
    const user = userEvent.setup();
    const items = [
      { id: "n1", kind: "new_dm", payload: { sender_email: "driver@example.com" }, created_at: "2026-01-01T00:00:00Z", read_at: null },
    ];
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/notifications?")) return Promise.resolve(jsonResponse(notificationPage(1, items)));
      if (url === "/api/notifications/n1/read" && init?.method === "POST") return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationIndicator />);

    MockEventSource.instances[0].onopen?.();
    await screen.findByText("1");
    await user.click(screen.getByRole("button", { name: /notifications/i }));
    await user.click(await screen.findByText("New message from driver@example.com"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/notifications/n1/read",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(screen.queryByText("1")).toBeNull();
  });

  it("opens the conversation with the sender when a new-message notification is clicked", async () => {
    const user = userEvent.setup();
    const items = [
      { id: "n1", kind: "new_dm", payload: { sender_user_id: 7, sender_email: "driver@example.com" }, created_at: "2026-01-01T00:00:00Z", read_at: null },
    ];
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/notifications?")) return Promise.resolve(jsonResponse(notificationPage(1, items)));
      if (url === "/api/notifications/n1/read" && init?.method === "POST") return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const onOpenMessage = vi.fn();
    render(<NotificationIndicator onOpenMessage={onOpenMessage} />);

    MockEventSource.instances[0].onopen?.();
    await screen.findByText("1");
    await user.click(screen.getByRole("button", { name: /notifications/i }));
    await user.click(await screen.findByText("New message from driver@example.com"));

    expect(onOpenMessage).toHaveBeenCalledWith(7, "driver@example.com");
  });

  it("marks all notifications read and resets the badge when 'Mark all as read' is clicked", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
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
    await screen.findByText("No notifications yet.");

    await user.click(screen.getByRole("button", { name: "Mark all as read" }));

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
