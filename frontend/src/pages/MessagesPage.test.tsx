import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import MessagesPage from "./MessagesPage";

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

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const me = { id: 1, email: "me@example.com", driving_experience: "experienced" as const, vehicle_type: "car" as const, avoid_tolls: false, avoid_highways: false, safety_preference: "balanced" as const };

const conversation = {
  other_user_id: 42,
  other_user_email: "bob@example.com",
  last_message_body: "Still there this morning.",
  last_message_at: "2026-01-01T00:00:00Z",
  unread_count: 1,
};

function baseFetchMock(): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/messages?")) {
      return Promise.resolve(jsonResponse({ items: [conversation], offset: 0, limit: 20, has_more: false }));
    }
    return Promise.resolve(jsonResponse({ detail: `unhandled ${url}` }, 404));
  });
}

describe("MessagesPage", () => {
  it("renders the conversation list, with no leftover way to message by raw user id", async () => {
    vi.stubGlobal("fetch", baseFetchMock());
    render(<MessagesPage user={me} />);

    expect(await screen.findByText("bob@example.com")).toBeTruthy();
    expect(screen.getByText(/Still there this morning\./)).toBeTruthy();
    expect(screen.getByText(/1 unread/)).toBeTruthy();
    expect(screen.queryByLabelText(/Message a user by ID/i)).toBeNull();
  });

  it("opens a conversation, marks it read, and sends a reply", async () => {
    const user = userEvent.setup();
    const fetchMock = baseFetchMock();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.startsWith("/api/messages?")) {
        return Promise.resolve(jsonResponse({ items: [conversation], offset: 0, limit: 20, has_more: false }));
      }
      if (url.startsWith("/api/messages/42?")) {
        return Promise.resolve(jsonResponse({
          items: [
            { id: "m1", sender_user_id: 42, sender_email: "bob@example.com", recipient_user_id: 1, recipient_email: "me@example.com", body: "Still there this morning.", media: null, created_at: "2026-01-01T00:00:00Z", read_at: "2026-01-01T00:05:00Z" },
          ],
          offset: 0, limit: 30, has_more: false,
        }));
      }
      if (url === "/api/messages/42" && method === "POST") {
        return Promise.resolve(jsonResponse({
          id: "m2", sender_user_id: 1, sender_email: "me@example.com", recipient_user_id: 42, recipient_email: "bob@example.com", body: "Thanks for confirming!", media: null, created_at: "2026-01-01T00:10:00Z", read_at: null,
        }, 201));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MessagesPage user={me} />);

    await user.click(await screen.findByRole("button", { name: "bob@example.com" }));
    expect(await screen.findByRole("heading", { name: "bob@example.com" })).toBeTruthy();
    expect(screen.getAllByText("Still there this morning.").length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText("Message"), "Thanks for confirming!");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Thanks for confirming!")).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/messages/42",
      expect.objectContaining({ method: "POST" }),
    ));
  });

  it("jumps straight into a conversation when handed an initialTarget (e.g. from a 'Message' click on a hazard report)", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/messages?")) {
        return Promise.resolve(jsonResponse({ items: [], offset: 0, limit: 20, has_more: false }));
      }
      if (url.startsWith("/api/messages/99?")) {
        return Promise.resolve(jsonResponse({ items: [], offset: 0, limit: 30, has_more: false }));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const onConsumed = vi.fn();
    render(
      <MessagesPage
        user={me}
        initialTarget={{ id: 99, email: "carol@example.com" }}
        onInitialTargetConsumed={onConsumed}
      />,
    );

    expect(await screen.findByRole("heading", { name: "carol@example.com" })).toBeTruthy();
    expect(onConsumed).toHaveBeenCalledTimes(1);
  });

  it("reopens the open conversation when a live new_dm event arrives from its sender", async () => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
    const fetchMock = baseFetchMock();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.startsWith("/api/messages?")) {
        return Promise.resolve(jsonResponse({ items: [conversation], offset: 0, limit: 20, has_more: false }));
      }
      if (url.startsWith("/api/messages/42?") && method === "GET") {
        return Promise.resolve(jsonResponse({ items: [], offset: 0, limit: 30, has_more: false }));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MessagesPage user={me} />);

    await user.click(await screen.findByRole("button", { name: "bob@example.com" }));
    expect(await screen.findByRole("heading", { name: "bob@example.com" })).toBeTruthy();

    const source = MockEventSource.instances[0];
    expect(source.url).toBe("/api/notifications/stream");
    const getConversationCallsBefore = fetchMock.mock.calls.filter(([url]) =>
      String(url).startsWith("/api/messages/42?"),
    ).length;

    source.onmessage?.({
      data: JSON.stringify({ kind: "new_dm", payload: { sender_user_id: 42 } }),
    });

    await waitFor(() => {
      const getConversationCallsAfter = fetchMock.mock.calls.filter(([url]) =>
        String(url).startsWith("/api/messages/42?"),
      ).length;
      expect(getConversationCallsAfter).toBeGreaterThan(getConversationCallsBefore);
    });
  });

  it("refreshes the conversation list, not the open thread, when a new_dm arrives from someone else", async () => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
    const fetchMock = baseFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    render(<MessagesPage user={me} />);

    await screen.findByText("bob@example.com");
    const source = MockEventSource.instances[0];
    const listCallsBefore = fetchMock.mock.calls.filter(([url]) =>
      String(url).startsWith("/api/messages?"),
    ).length;

    source.onmessage?.({
      data: JSON.stringify({ kind: "new_dm", payload: { sender_user_id: 99 } }),
    });

    await waitFor(() => {
      const listCallsAfter = fetchMock.mock.calls.filter(([url]) =>
        String(url).startsWith("/api/messages?"),
      ).length;
      expect(listCallsAfter).toBeGreaterThan(listCallsBefore);
    });
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).startsWith("/api/messages/42?")),
    ).toBe(false);
  });

  it("ignores live events that aren't new_dm", async () => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
    const fetchMock = baseFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    render(<MessagesPage user={me} />);

    await screen.findByText("bob@example.com");
    const source = MockEventSource.instances[0];
    const callsBefore = fetchMock.mock.calls.length;

    source.onmessage?.({ data: JSON.stringify({ kind: "new_vote", payload: {} }) });

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.length).toBe(callsBefore);
  });

  it("closes the notification stream connection on unmount", async () => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
    vi.stubGlobal("fetch", baseFetchMock());
    const view = render(<MessagesPage user={me} />);
    await screen.findByText("bob@example.com");

    const source = MockEventSource.instances[0];
    view.unmount();

    expect(source.closed).toBe(true);
  });
});
