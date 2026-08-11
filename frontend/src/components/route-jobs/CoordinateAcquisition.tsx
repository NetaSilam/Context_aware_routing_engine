import { useState } from "react";
import { MapContainer, Marker, TileLayer, useMapEvents } from "react-leaflet";

import { searchAddresses, type AddressSearchResult } from "../../api/geocoding";
import type { SubmitRouteJobRequest } from "../../api/routeJobs";

type Endpoint = "origin" | "destination";

interface CoordinateDraft {
  longitude: string;
  latitude: string;
  label: string;
}

interface CoordinateAcquisitionProps {
  disabled: boolean;
  onSubmit: (payload: SubmitRouteJobRequest) => Promise<void>;
  hideMap?: boolean;
}

const INITIAL_COORDINATES: Record<Endpoint, CoordinateDraft> = {
  origin: { longitude: "34.7800", latitude: "32.0700", label: "32.07000, 34.78000" },
  destination: { longitude: "34.7900", latitude: "32.0800", label: "32.08000, 34.79000" },
};

function formattedCoordinateLabel(longitude: string, latitude: string): string {
  const lon = Number(longitude);
  const lat = Number(latitude);
  return Number.isFinite(lon) && Number.isFinite(lat)
    ? `${lat.toFixed(5)}, ${lon.toFixed(5)}`
    : "";
}

function MapClickHandler({ onClick }: { onClick: (latitude: number, longitude: number) => void }): null {
  useMapEvents({ click: (event) => onClick(event.latlng.lat, event.latlng.lng) });
  return null;
}

export default function CoordinateAcquisition({ disabled, onSubmit, hideMap = false }: CoordinateAcquisitionProps): JSX.Element {
  const [coordinates, setCoordinates] = useState(INITIAL_COORDINATES);
  const [mapTarget, setMapTarget] = useState<Endpoint>("origin");
  const [searchQueries, setSearchQueries] = useState<Record<Endpoint, string>>({ origin: "", destination: "" });
  const [searchResults, setSearchResults] = useState<Record<Endpoint, AddressSearchResult[]>>({ origin: [], destination: [] });
  const [searchCompleted, setSearchCompleted] = useState<Record<Endpoint, boolean>>({ origin: false, destination: false });
  const [searching, setSearching] = useState<Endpoint | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  function updateNumeric(endpoint: Endpoint, field: "longitude" | "latitude", value: string) {
    setCoordinates((current) => {
      const next = { ...current[endpoint], [field]: value };
      return { ...current, [endpoint]: { ...next, label: formattedCoordinateLabel(next.longitude, next.latitude) } };
    });
  }

  function selectAddress(endpoint: Endpoint, match: AddressSearchResult) {
    setCoordinates((current) => ({
      ...current,
      [endpoint]: {
        longitude: String(match.longitude),
        latitude: String(match.latitude),
        label: match.label.slice(0, 200),
      },
    }));
    setSearchResults((current) => ({ ...current, [endpoint]: [] }));
    setSearchCompleted((current) => ({ ...current, [endpoint]: false }));
    setSearchError(null);
  }

  async function runSearch(endpoint: Endpoint) {
    setSearching(endpoint);
    setSearchError(null);
    try {
      const response = await searchAddresses(searchQueries[endpoint]);
      setSearchResults((current) => ({ ...current, [endpoint]: response.results }));
      setSearchCompleted((current) => ({ ...current, [endpoint]: true }));
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "Address search failed. Use map or numeric coordinates.");
    } finally {
      setSearching(null);
    }
  }

  function selectMapCoordinate(latitude: number, longitude: number) {
    const next = { longitude: longitude.toFixed(6), latitude: latitude.toFixed(6), label: "" };
    next.label = formattedCoordinateLabel(next.longitude, next.latitude);
    setCoordinates((current) => ({ ...current, [mapTarget]: next }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const originLongitude = Number(coordinates.origin.longitude);
    const originLatitude = Number(coordinates.origin.latitude);
    const destinationLongitude = Number(coordinates.destination.longitude);
    const destinationLatitude = Number(coordinates.destination.latitude);
    const values = [originLongitude, originLatitude, destinationLongitude, destinationLatitude];
    if (values.some((value) => !Number.isFinite(value))) {
      setValidationError("Enter valid finite numeric coordinates.");
      return;
    }
    if (
      originLongitude < 34 || originLongitude > 35.9 || destinationLongitude < 34 || destinationLongitude > 35.9
      || originLatitude < 29.4 || originLatitude > 33.4 || destinationLatitude < 29.4 || destinationLatitude > 33.4
    ) {
      setValidationError("Coordinates must be inside the supported Israel region.");
      return;
    }
    if (originLongitude === destinationLongitude && originLatitude === destinationLatitude) {
      setValidationError("Origin and destination must be different.");
      return;
    }
    setValidationError(null);
    await onSubmit({
      origin_longitude: originLongitude,
      origin_latitude: originLatitude,
      destination_longitude: destinationLongitude,
      destination_latitude: destinationLatitude,
      origin_label: coordinates.origin.label || formattedCoordinateLabel(coordinates.origin.longitude, coordinates.origin.latitude),
      destination_label: coordinates.destination.label || formattedCoordinateLabel(coordinates.destination.longitude, coordinates.destination.latitude),
    });
  }

  const markerPosition = (endpoint: Endpoint): [number, number] | null => {
    const longitude = Number(coordinates[endpoint].longitude);
    const latitude = Number(coordinates[endpoint].latitude);
    return Number.isFinite(longitude) && Number.isFinite(latitude) ? [latitude, longitude] : null;
  };

  return (
    <section className="filters-panel" aria-label="Route coordinates">
      <h2>Choose origin and destination</h2>
      <p>Search only when you press a search button. Map clicks and numeric fields remain available if search fails.</p>
      <div className="coordinate-search-grid">
        {(["origin", "destination"] as Endpoint[]).map((endpoint) => (
          <section key={endpoint} aria-label={`${endpoint} address search`}>
            <h3>{endpoint === "origin" ? "Origin" : "Destination"} address</h3>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void runSearch(endpoint);
              }}
            >
              <label className="filter-field">
                Address
                <input
                  maxLength={200}
                  value={searchQueries[endpoint]}
                  onChange={(event) => setSearchQueries((current) => ({ ...current, [endpoint]: event.target.value }))}
                />
              </label>
              <button type="submit" className="ghost-button" disabled={searching !== null}>
                {searching === endpoint ? "Searching…" : `Search ${endpoint}`}
              </button>
            </form>
            {searchCompleted[endpoint] && searchResults[endpoint].length === 0 ? <p>No addresses found.</p> : null}
            <ul className="address-results">
              {searchResults[endpoint].map((match) => (
                <li key={`${match.longitude}-${match.latitude}-${match.label}`}>
                  <button type="button" className="ghost-button" onClick={() => selectAddress(endpoint, match)}>{match.label}</button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      {searchError ? <p role="alert" className="error-banner">{searchError}</p> : null}
      <p className="geocoding-attribution">Address search data © OpenStreetMap contributors.</p>

      {hideMap ? null : (
        <>
          <div className="map-target-controls" aria-label="Map click target">
            <span>Next map click sets:</span>
            <label><input type="radio" name="map-target" checked={mapTarget === "origin"} onChange={() => setMapTarget("origin")} /> Origin</label>
            <label><input type="radio" name="map-target" checked={mapTarget === "destination"} onChange={() => setMapTarget("destination")} /> Destination</label>
          </div>
          <div className="map-shell" aria-label="Coordinate selection map">
            <MapContainer center={[32.0, 34.9]} zoom={8} className="corridor-map">
              <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              <MapClickHandler onClick={selectMapCoordinate} />
              {markerPosition("origin") ? <Marker position={markerPosition("origin") as [number, number]} title="Origin marker" /> : null}
              {markerPosition("destination") ? <Marker position={markerPosition("destination") as [number, number]} title="Destination marker" /> : null}
            </MapContainer>
          </div>
        </>
      )}

      <form onSubmit={submit} className="filters-grid" aria-label="Route coordinate form">
        <label className="filter-field">Origin longitude<input required type="number" step="any" value={coordinates.origin.longitude} onChange={(event) => updateNumeric("origin", "longitude", event.target.value)} /></label>
        <label className="filter-field">Origin latitude<input required type="number" step="any" value={coordinates.origin.latitude} onChange={(event) => updateNumeric("origin", "latitude", event.target.value)} /></label>
        <label className="filter-field">Origin label<input readOnly value={coordinates.origin.label} /></label>
        <label className="filter-field">Destination longitude<input required type="number" step="any" value={coordinates.destination.longitude} onChange={(event) => updateNumeric("destination", "longitude", event.target.value)} /></label>
        <label className="filter-field">Destination latitude<input required type="number" step="any" value={coordinates.destination.latitude} onChange={(event) => updateNumeric("destination", "latitude", event.target.value)} /></label>
        <label className="filter-field">Destination label<input readOnly value={coordinates.destination.label} /></label>
        {validationError ? <p role="alert" className="error-banner">{validationError}</p> : null}
        <button className="primary-button" type="submit" disabled={disabled}>Compare routes</button>
      </form>
    </section>
  );
}
