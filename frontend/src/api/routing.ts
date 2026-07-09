import type { Coordinate, GeocodeResult, RouteResponse } from "../types/routing";

async function parseJsonOrThrow(response: Response): Promise<unknown> {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? String(body.detail) : null;
    throw new Error(detail ?? `Request failed with status ${response.status}.`);
  }
  return body;
}

export async function geocode(query: string): Promise<GeocodeResult[]> {
  const search = new URLSearchParams({ q: query });
  const response = await fetch(`/api/geocode?${search.toString()}`);
  const body = (await parseJsonOrThrow(response)) as { results: GeocodeResult[] };
  return body.results;
}

export async function planRoute(
  token: string,
  origin: Coordinate,
  destination: Coordinate,
  timeOfDay?: "day" | "night",
): Promise<RouteResponse> {
  const response = await fetch("/api/route", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      origin,
      destination,
      time_of_day: timeOfDay ?? null,
    }),
  });
  return (await parseJsonOrThrow(response)) as RouteResponse;
}
