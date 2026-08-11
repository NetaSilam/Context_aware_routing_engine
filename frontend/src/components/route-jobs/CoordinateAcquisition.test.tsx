import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mapState = vi.hoisted(() => ({
  click: null as null | ((event: { latlng: { lat: number; lng: number } }) => void),
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: ({ position, title }: { position: unknown; title: string }) => <span data-testid={title} data-position={JSON.stringify(position)} />,
  useMapEvents: (handlers: { click: typeof mapState.click }) => { mapState.click = handlers.click; },
}));

import CoordinateAcquisition from "./CoordinateAcquisition";

afterEach(() => {
  vi.unstubAllGlobals();
  mapState.click = null;
  cleanup();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("CoordinateAcquisition", () => {
  it("uses explicit address selection and keeps the selected label as bounded display text", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      results: [{ label: "Tel Aviv Center", longitude: 34.81, latitude: 32.09 }],
      attribution: "© OpenStreetMap contributors",
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CoordinateAcquisition disabled={false} onSubmit={onSubmit} />);

    const addressInputs = screen.getAllByLabelText("Address");
    await user.type(addressInputs[0], "Tel Aviv");
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Search origin" }));
    await user.click(await screen.findByRole("button", { name: "Tel Aviv Center" }));
    expect((screen.getByLabelText("Origin longitude") as HTMLInputElement).value).toBe("34.81");
    expect((screen.getByLabelText("Origin latitude") as HTMLInputElement).value).toBe("32.09");
    expect((screen.getByLabelText("Origin label") as HTMLInputElement).value).toBe("Tel Aviv Center");
    expect(screen.getByText(/© OpenStreetMap contributors/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Compare routes" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      origin_longitude: 34.81,
      origin_latitude: 32.09,
      origin_label: "Tel Aviv Center",
    })));
  });

  it("sets either marker from map clicks without reverse geocoding", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<CoordinateAcquisition disabled={false} onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    await act(async () => mapState.click?.({ latlng: { lat: 31.5, lng: 34.5 } }));
    expect((screen.getByLabelText("Origin latitude") as HTMLInputElement).value).toBe("31.500000");
    expect((screen.getByLabelText("Origin label") as HTMLInputElement).value).toBe("31.50000, 34.50000");
    expect(screen.getByTestId("Origin marker").getAttribute("data-position")).toBe("[31.5,34.5]");

    await user.click(screen.getByLabelText("Destination"));
    await act(async () => mapState.click?.({ latlng: { lat: 31.6, lng: 34.6 } }));
    expect((screen.getByLabelText("Destination latitude") as HTMLInputElement).value).toBe("31.600000");
    expect((screen.getByLabelText("Destination label") as HTMLInputElement).value).toBe("31.60000, 34.60000");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("numeric edits replace an address label with a coordinate fallback and validate points", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<CoordinateAcquisition disabled={false} onSubmit={onSubmit} />);

    const originLongitude = screen.getByLabelText("Origin longitude");
    await user.clear(originLongitude);
    await user.type(originLongitude, "34.7");
    expect((screen.getByLabelText("Origin label") as HTMLInputElement).value).toBe("32.07000, 34.70000");

    const destinationLongitude = screen.getByLabelText("Destination longitude");
    const destinationLatitude = screen.getByLabelText("Destination latitude");
    await user.clear(destinationLongitude);
    await user.type(destinationLongitude, "34.7");
    await user.clear(destinationLatitude);
    await user.type(destinationLatitude, "32.07");
    await user.click(screen.getByRole("button", { name: "Compare routes" }));
    expect(screen.getByRole("alert").textContent).toContain("must be different");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps map and numeric controls usable after provider failure", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: "Address search is temporarily unavailable. Use map or numeric coordinates.",
    }, 503)));
    render(<CoordinateAcquisition disabled={false} onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    await user.type(screen.getAllByLabelText("Address")[0], "Tel Aviv");
    await user.click(screen.getByRole("button", { name: "Search origin" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Use map or numeric coordinates");
    expect((screen.getByLabelText("Origin longitude") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Destination") as HTMLInputElement).disabled).toBe(false);
    expect(screen.getByLabelText("Coordinate selection map")).toBeTruthy();
  });

  it("shows empty results only after an explicit search", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      results: [],
      attribution: "© OpenStreetMap contributors",
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CoordinateAcquisition disabled={false} onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    await user.type(screen.getAllByLabelText("Address")[0], "Unknown place");
    expect(screen.queryByText("No addresses found.")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Search origin" }));
    expect(await screen.findByText("No addresses found.")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("searches on Enter without requiring a click on the search button", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      results: [{ label: "Tel Aviv Center", longitude: 34.81, latitude: 32.09 }],
      attribution: "© OpenStreetMap contributors",
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CoordinateAcquisition disabled={false} onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    await user.type(screen.getAllByLabelText("Address")[0], "Tel Aviv{Enter}");

    expect(await screen.findByRole("button", { name: "Tel Aviv Center" })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("does not show a stale 'no addresses found' message after an address has been selected", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      results: [{ label: "Tel Aviv Center", longitude: 34.81, latitude: 32.09 }],
      attribution: "© OpenStreetMap contributors",
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CoordinateAcquisition disabled={false} onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    await user.type(screen.getAllByLabelText("Address")[0], "Tel Aviv");
    await user.click(screen.getByRole("button", { name: "Search origin" }));
    await user.click(await screen.findByRole("button", { name: "Tel Aviv Center" }));

    expect((screen.getByLabelText("Origin label") as HTMLInputElement).value).toBe("Tel Aviv Center");
    expect(screen.queryByText("No addresses found.")).toBeNull();
  });

  it("hides the coordinate-picker map when hideMap is set", () => {
    render(<CoordinateAcquisition disabled={false} onSubmit={vi.fn().mockResolvedValue(undefined)} hideMap />);

    expect(screen.queryByLabelText("Coordinate selection map")).toBeNull();
    expect(screen.queryByLabelText("Map click target")).toBeNull();
  });
});
