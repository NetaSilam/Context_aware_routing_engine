import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import InboxPage from "./InboxPage";

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const me = { id: 1, email: "me@example.com", driving_experience: "experienced" as const, vehicle_type: "car" as const, avoid_tolls: false, avoid_highways: false };

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

describe("InboxPage", () => {
  it("renders the conversation list", async () => {
    vi.stubGlobal("fetch", baseFetchMock());
    render(<InboxPage user={me} />);

    expect(await screen.findByText("bob@example.com")).toBeTruthy();
    expect(screen.getByText(/Still there this morning\./)).toBeTruthy();
    expect(screen.getByText(/1 unread/)).toBeTruthy();
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
    render(<InboxPage user={me} />);

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

  it("starts a new conversation by recipient user id", async () => {
    const user = userEvent.setup();
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
    render(<InboxPage user={me} />);
    await screen.findByText("No conversations yet.");

    await user.type(screen.getByLabelText("Message a user by ID"), "99");
    await user.click(screen.getByRole("button", { name: "Start conversation" }));

    expect(await screen.findByRole("heading", { name: "User 99" })).toBeTruthy();
  });
});
