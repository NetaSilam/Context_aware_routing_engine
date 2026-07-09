import { MapContainer, Polyline, TileLayer } from "react-leaflet";

import type { RouteResponse } from "../../types/routing";

interface RouteResultPanelProps {
  result: RouteResponse | null;
  error: string | null;
  loading: boolean;
}

function toLatLngs(coordinates: [number, number][]): [number, number][] {
  return coordinates.map(([lon, lat]) => [lat, lon]);
}

export default function RouteResultPanel(props: RouteResultPanelProps): JSX.Element | null {
  if (props.loading) {
    return <p className="loading-banner">Fetching candidate routes and scoring historical risk…</p>;
  }
  if (props.error) {
    return <p className="error-banner">{props.error}</p>;
  }
  if (!props.result) {
    return null;
  }

  const { result } = props;
  const chosenLatLngs = toLatLngs(result.chosen_route.geometry.coordinates);
  const bounds = chosenLatLngs;

  return (
    <section className="workspace-grid" aria-label="Route result">
      <div className="map-panel">
        <div className="map-panel__header">
          <div>
            <p className="eyebrow">Recommended Route</p>
            <h2>{result.explanation}</h2>
          </div>
        </div>
        <div className="map-shell">
          <MapContainer className="corridor-map" bounds={bounds}>
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {result.alternatives
              .filter((alt) => alt !== result.chosen_route)
              .map((alt, index) => (
                <Polyline
                  key={`alt-${index}`}
                  positions={toLatLngs(alt.geometry.coordinates)}
                  pathOptions={{ color: "#a3333d", weight: 3, opacity: 0.45, dashArray: "6 8" }}
                />
              ))}
            <Polyline
              positions={chosenLatLngs}
              pathOptions={{ color: "#0d7288", weight: 5, opacity: 0.9 }}
            />
          </MapContainer>
        </div>
      </div>

      <aside className="detail-panel" aria-label="Route stats">
        <p className="eyebrow">Chosen Route</p>
        <dl className="detail-grid">
          <div>
            <dt>Distance</dt>
            <dd>{(result.chosen_route.distance_m / 1000).toFixed(1)} km</dd>
          </div>
          <div>
            <dt>Travel time</dt>
            <dd>{Math.round(result.chosen_route.duration_s / 60)} min</dd>
          </div>
          <div>
            <dt>Historical accidents nearby</dt>
            <dd>{result.chosen_route.accident_count.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Risk density</dt>
            <dd>{result.chosen_route.risk_density.toFixed(2)} accidents/km</dd>
          </div>
          <div>
            <dt>Time of day used</dt>
            <dd>{result.time_of_day}</dd>
          </div>
          <div>
            <dt>Safety vs. time weight</dt>
            <dd>
              W_safe {result.weights.w_safe.toFixed(2)} / W_time {result.weights.w_time.toFixed(2)}
            </dd>
          </div>
          <div>
            <dt>Alternatives considered</dt>
            <dd>{result.alternatives.length}</dd>
          </div>
        </dl>
      </aside>
    </section>
  );
}
