import { afterEach, describe, expect, it, vi } from "vitest";

import { searchAddresses } from "./geocoding";

afterEach(() => vi.unstubAllGlobals());

describe("address search API", () => {
  it("sends one explicit authenticated search request", async () => {
    const body = { results: [], attribution: "© OpenStreetMap contributors" };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(searchAddresses("Tel Aviv center")).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/geocoding/search?q=Tel%20Aviv%20center",
      { credentials: "include" },
    );
  });

  it("returns controlled provider feedback", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "Use map or numeric coordinates." }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    )));
    await expect(searchAddresses("Tel Aviv")).rejects.toThrow(
      "Use map or numeric coordinates.",
    );
  });
});
