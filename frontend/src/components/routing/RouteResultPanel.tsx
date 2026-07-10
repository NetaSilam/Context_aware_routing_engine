import { useEffect, useState } from "react";
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
  const { result } = props;
  const [highlightedIndex, setHighlightedIndex] = useState<number | null>(null);

  // A new route request produces a new `result` object - clear any highlight from
  // a previous result rather than carrying a stale/out-of-range index forward.
  useEffect(() => {
    setHighlightedIndex(null);
  }, [result]);

  if (props.loading) {
    return <p className="loading-banner">Fetching candidate routes and scoring historical risk…</p>;
  }
  if (props.error) {
    return <p className="error-banner">{props.error}</p>;
  }
  if (!result) {
    return null;
  }

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
              .map((alt, index) => ({ alt, index }))
              .filter(({ index }) => index !== result.chosen_index)
              .map(({ alt, index }) => {
                const isHighlighted = index === highlightedIndex;
                return (
                  <Polyline
                    key={`alt-${index}`}
                    positions={toLatLngs(alt.geometry.coordinates)}
                    eventHandlers={{
                      click: () => setHighlightedIndex(isHighlighted ? null : index),
                    }}
                    pathOptions={
                      isHighlighted
                        ? { color: "#f28444", weight: 5, opacity: 0.95 }
                        : { color: "#a3333d", weight: 3, opacity: 0.45, dashArray: "6 8" }
                    }
                  />
                );
              })}
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

        {result.alternatives.length > 1 ? (
          <div className="visible-corridor-list">
            <div className="visible-corridor-list__header">
              <h3>Compare candidates</h3>
              <p>Click a row to highlight it on the map (orange). Teal is always the chosen route.</p>
            </div>
            <ul>
              {result.alternatives.map((alt, index) => {
                const isChosen = index === result.chosen_index;
                const isHighlighted = index === highlightedIndex;
                return (
                  <li key={index}>
                    <button
                      type="button"
                      className={
                        isChosen || isHighlighted
                          ? "corridor-row corridor-row--selected"
                          : "corridor-row"
                      }
                      disabled={isChosen}
                      onClick={() => setHighlightedIndex(isHighlighted ? null : index)}
                    >
                      <span>
                        {isChosen ? "✓ Chosen — " : ""}
                        {(alt.distance_m / 1000).toFixed(1)} km, {Math.round(alt.duration_s / 60)} min
                      </span>
                      <span className="accident-row__meta">
                        {alt.accident_count} accidents ({alt.risk_density.toFixed(1)}/km) · cost{" "}
                        {alt.cost.toFixed(2)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </aside>
    </section>
  );
}
