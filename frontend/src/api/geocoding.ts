export interface AddressSearchResult {
  label: string;
  longitude: number;
  latitude: number;
}

export interface AddressSearchResponse {
  results: AddressSearchResult[];
  attribution: string;
}

export async function searchAddresses(query: string): Promise<AddressSearchResponse> {
  const response = await fetch(`/api/geocoding/search?q=${encodeURIComponent(query)}`, {
    credentials: "include",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Address search failed (${response.status}).`);
  }
  return response.json() as Promise<AddressSearchResponse>;
}
