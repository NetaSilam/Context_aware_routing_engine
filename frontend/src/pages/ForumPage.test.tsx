import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ForumPage from "./ForumPage";

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const dashboard = { post_count: 1, comment_count: 0, net_votes_received: 2 };

const post = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "Deep pothole on Route 4",
  hazard_type: "pothole" as const,
  longitude: null,
  latitude: null,
  author_id: 5,
  author_email: "reporter@example.com",
  is_anonymous: false,
  is_own: false,
  upvote_count: 2,
  downvote_count: 0,
  comment_count: 1,
  my_vote: "none" as const,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function baseFetchMock(): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.startsWith("/api/forum/posts?") && method === "GET") {
      return Promise.resolve(jsonResponse({ items: [post], offset: 0, limit: 20, has_more: false }));
    }
    if (url === "/api/forum/me/dashboard") {
      return Promise.resolve(jsonResponse(dashboard));
    }
    return Promise.resolve(jsonResponse({ detail: `unhandled ${method} ${url}` }, 404));
  });
}

describe("ForumPage", () => {
  it("renders the hazard feed and dashboard summary", async () => {
    vi.stubGlobal("fetch", baseFetchMock());
    render(<ForumPage />);

    expect(await screen.findByText("Deep pothole on Route 4")).toBeTruthy();
    expect(await screen.findByText(/Net votes received: 2/)).toBeTruthy();
    expect(screen.getByText(/reporter@example.com/)).toBeTruthy();
  });

  it("blocks submission until title and description are filled in", async () => {
    const user = userEvent.setup();
    const fetchMock = baseFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    render(<ForumPage />);
    await screen.findByText("Deep pothole on Route 4");

    await user.click(screen.getByRole("button", { name: "Report hazard" }));

    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/forum/posts",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("creates a new report and prepends it to the feed", async () => {
    const user = userEvent.setup();
    const fetchMock = baseFetchMock();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.startsWith("/api/forum/posts?") && method === "GET") {
        return Promise.resolve(jsonResponse({ items: [post], offset: 0, limit: 20, has_more: false }));
      }
      if (url === "/api/forum/me/dashboard") return Promise.resolve(jsonResponse(dashboard));
      if (url === "/api/forum/posts" && method === "POST") {
        return Promise.resolve(jsonResponse(
          { ...post, id: "22222222-2222-2222-2222-222222222222", title: "Flooded underpass", body: "Deep water.", media: [], upvote_count: 0, comment_count: 0 },
          201,
        ));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ForumPage />);
    await screen.findByText("Deep pothole on Route 4");

    await user.type(screen.getByLabelText("Title"), "Flooded underpass");
    await user.type(screen.getByLabelText("Description"), "Deep water.");
    await user.click(screen.getByRole("button", { name: "Report hazard" }));

    expect(await screen.findByText("Flooded underpass")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/forum/posts",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("uploads a selected photo to the newly created report", async () => {
    const user = userEvent.setup();
    const createdId = "22222222-2222-2222-2222-222222222222";
    const fetchMock = baseFetchMock();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.startsWith("/api/forum/posts?") && method === "GET") {
        return Promise.resolve(jsonResponse({ items: [post], offset: 0, limit: 20, has_more: false }));
      }
      if (url === "/api/forum/me/dashboard") return Promise.resolve(jsonResponse(dashboard));
      if (url === "/api/forum/posts" && method === "POST") {
        return Promise.resolve(jsonResponse(
          { ...post, id: createdId, title: "Flooded underpass", body: "Deep water.", media: [], upvote_count: 0, comment_count: 0 },
          201,
        ));
      }
      if (url === `/api/forum/posts/${createdId}/media` && method === "POST") {
        return Promise.resolve(jsonResponse(
          { id: "55555555-5555-5555-5555-555555555555", media_type: "image", content_type: "image/png", byte_size: 4 },
          201,
        ));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ForumPage />);
    await screen.findByText("Deep pothole on Route 4");

    await user.type(screen.getByLabelText("Title"), "Flooded underpass");
    await user.type(screen.getByLabelText("Description"), "Deep water.");
    const file = new File(["fake"], "hazard.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Photos or videos (optional)"), file);
    await user.click(screen.getByRole("button", { name: "Report hazard" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/forum/posts/${createdId}/media`,
      expect.objectContaining({ method: "POST" }),
    ));
    const mediaCall = fetchMock.mock.calls.find(([url]) => String(url) === `/api/forum/posts/${createdId}/media`);
    expect(mediaCall?.[1]?.body).toBeInstanceOf(FormData);
  });

  it("optimistically applies a vote and calls the vote endpoint", async () => {
    const user = userEvent.setup();
    const fetchMock = baseFetchMock();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.startsWith("/api/forum/posts?") && method === "GET") {
        return Promise.resolve(jsonResponse({ items: [post], offset: 0, limit: 20, has_more: false }));
      }
      if (url === "/api/forum/me/dashboard") return Promise.resolve(jsonResponse(dashboard));
      if (url === `/api/forum/posts/${post.id}/vote` && method === "PUT") {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ForumPage />);
    await screen.findByText("Deep pothole on Route 4");

    const voteGroup = screen.getByRole("group", { name: "Vote" });
    const [upButton] = within(voteGroup).getAllByRole("button");
    await user.click(upButton);

    await waitFor(() => expect(upButton.getAttribute("aria-pressed")).toBe("true"));
    expect(upButton.textContent).toContain("3");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/forum/posts/${post.id}/vote`,
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ value: "up" }) }),
    ));
  });

  it("captures an optional location and submits it with the report", async () => {
    const user = userEvent.setup();
    const fetchMock = baseFetchMock();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.startsWith("/api/forum/posts?") && method === "GET") {
        return Promise.resolve(jsonResponse({ items: [post], offset: 0, limit: 20, has_more: false }));
      }
      if (url === "/api/forum/me/dashboard") return Promise.resolve(jsonResponse(dashboard));
      if (url === "/api/forum/posts" && method === "POST") {
        return Promise.resolve(jsonResponse(
          { ...post, id: "22222222-2222-2222-2222-222222222222", title: "Flooded underpass", body: "Deep water.", media: [], longitude: 34.78, latitude: 32.07 },
          201,
        ));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ForumPage />);
    await screen.findByText("Deep pothole on Route 4");

    await user.type(screen.getByLabelText("Title"), "Flooded underpass");
    await user.type(screen.getByLabelText("Description"), "Deep water.");
    await user.type(screen.getByLabelText("Longitude (optional)"), "34.78");
    await user.type(screen.getByLabelText("Latitude (optional)"), "32.07");
    await user.click(screen.getByRole("button", { name: "Report hazard" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/forum/posts",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          title: "Flooded underpass",
          body: "Deep water.",
          hazard_type: "pothole",
          is_anonymous: false,
          longitude: 34.78,
          latitude: 32.07,
        }),
      }),
    ));
  });

  it("refetches the feed with the selected hazard type filter", async () => {
    const user = userEvent.setup();
    const floodPost = { ...post, id: "66666666-6666-6666-6666-666666666666", title: "Flooded underpass", hazard_type: "flooding" as const };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/forum/me/dashboard") return Promise.resolve(jsonResponse(dashboard));
      if (url.includes("hazard_type=flooding")) {
        return Promise.resolve(jsonResponse({ items: [floodPost], offset: 0, limit: 20, has_more: false }));
      }
      if (url.startsWith("/api/forum/posts?")) {
        return Promise.resolve(jsonResponse({ items: [post], offset: 0, limit: 20, has_more: false }));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ForumPage />);
    await screen.findByText("Deep pothole on Route 4");

    await user.selectOptions(screen.getByLabelText("Filter by hazard type"), "flooding");

    expect(await screen.findByText("Flooded underpass")).toBeTruthy();
    expect(screen.queryByText("Deep pothole on Route 4")).toBeNull();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("hazard_type=flooding"),
      expect.anything(),
    ));
  });

  it("loads more posts when Load more is clicked", async () => {
    const user = userEvent.setup();
    const secondPost = { ...post, id: "77777777-7777-7777-7777-777777777777", title: "Broken traffic light" };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/forum/me/dashboard") return Promise.resolve(jsonResponse(dashboard));
      if (url.includes("offset=1")) {
        return Promise.resolve(jsonResponse({ items: [secondPost], offset: 1, limit: 20, has_more: false }));
      }
      if (url.startsWith("/api/forum/posts?")) {
        return Promise.resolve(jsonResponse({ items: [post], offset: 0, limit: 20, has_more: true }));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ForumPage />);
    await screen.findByText("Deep pothole on Route 4");

    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Broken traffic light")).toBeTruthy();
    expect(screen.getByText("Deep pothole on Route 4")).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("offset=1"),
      expect.anything(),
    ));
  });

  it("opens a report, shows comments, and posts a new comment", async () => {
    const user = userEvent.setup();
    const detail = { ...post, body: "Wide and deep, watch out.", media: [] };
    const comment = {
      id: "33333333-3333-3333-3333-333333333333",
      post_id: post.id,
      body: "Still there today.",
      author_id: 9,
      author_email: "commenter@example.com",
      is_anonymous: false,
      is_own: false,
      upvote_count: 0,
      downvote_count: 0,
      my_vote: "none" as const,
      media: [],
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const fetchMock = baseFetchMock();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.startsWith("/api/forum/posts?") && method === "GET") {
        return Promise.resolve(jsonResponse({ items: [post], offset: 0, limit: 20, has_more: false }));
      }
      if (url === "/api/forum/me/dashboard") return Promise.resolve(jsonResponse(dashboard));
      if (url === `/api/forum/posts/${post.id}`) return Promise.resolve(jsonResponse(detail));
      if (url.startsWith(`/api/forum/posts/${post.id}/comments`) && method === "GET") {
        return Promise.resolve(jsonResponse({ items: [comment], offset: 0, limit: 30, has_more: false }));
      }
      if (url === `/api/forum/posts/${post.id}/comments` && method === "POST") {
        return Promise.resolve(jsonResponse(
          { ...comment, id: "44444444-4444-4444-4444-444444444444", body: "Confirmed, cleared now." },
          201,
        ));
      }
      return Promise.resolve(jsonResponse({ detail: "unhandled" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ForumPage />);

    await user.click(await screen.findByRole("button", { name: "Deep pothole on Route 4" }));

    expect(await screen.findByText("Wide and deep, watch out.")).toBeTruthy();
    expect(screen.getByText("Still there today.")).toBeTruthy();

    await user.type(screen.getByLabelText("Add a comment"), "Confirmed, cleared now.");
    await user.click(screen.getByRole("button", { name: "Post comment" }));

    expect(await screen.findByText("Confirmed, cleared now.")).toBeTruthy();
  });
});
