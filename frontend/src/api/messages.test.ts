import { afterEach, describe, expect, it, vi } from "vitest";

import { getConversation, listConversations, sendMessage } from "./messages";

afterEach(() => vi.unstubAllGlobals());

describe("messages API client", () => {
  it("lists conversations with offset/limit query params", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], offset: 0, limit: 20, has_more: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listConversations(5, 10);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/messages?offset=5&limit=10",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("fetches a conversation by other user id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], offset: 0, limit: 30, has_more: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getConversation(42);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/messages/42?offset=0&limit=30",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("sends a message as multipart form data with only the provided fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "msg-1",
          sender_user_id: 1,
          sender_email: "me@example.com",
          recipient_user_id: 42,
          recipient_email: "them@example.com",
          body: "hi",
          media: null,
          created_at: "2026-01-01T00:00:00Z",
          read_at: null,
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await sendMessage(42, "hi", null);

    expect(result.body).toBe("hi");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/messages/42");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("body")).toBe("hi");
    expect((init?.body as FormData).get("file")).toBeNull();
  });

  it("throws the server-provided detail message on failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Cannot send a message to yourself." }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(sendMessage(1, "hi", null)).rejects.toThrow(
      "Cannot send a message to yourself.",
    );
  });
});
