import { useEffect, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";

import type { BBoxQuery } from "../../api/accidentAttribution";
import type { AttributedAccidentListItem } from "../../types/accidentAttribution";

type BoundsTuple = [[number, number], [number, number]];

interface AttributionMapProps {
  accidents: AttributedAccidentListItem[];
  selectedAccidentId: string | null;
  activeBbox: BBoxQuery;
  onViewportCommit: (bbox: BBoxQuery) => void;
  onAccidentSelect: (accidentId: string) => void;
}

const NATIONWIDE_BOUNDS: BBoxQuery = {
  minLon: 34.0,
  minLat: 29.4,
  maxLon: 36.0,
  maxLat: 33.5,
};

const CENTRAL_BOUNDS: BBoxQuery = {
  minLon: 34.7,
  minLat: 31.7,
  maxLon: 35.3,
  maxLat: 32.3,
};

function bboxToLeafletBounds(bbox: BBoxQuery): BoundsTuple {
  return [
    [bbox.minLat, bbox.minLon],
    [bbox.maxLat, bbox.maxLon],
  ];
}

function MapViewportBridge(props: {
  onBoundsChange: (bbox: BBoxQuery) => void;
  focusRequest: BBoxQuery | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (!props.focusRequest) {
      return;
    }
    map.fitBounds(bboxToLeafletBounds(props.focusRequest), { padding: [18, 18] });
  }, [map, props.focusRequest, props.onBoundsChange]);

  useMapEvents({
    moveend() {
      const bounds = map.getBounds();
      props.onBoundsChange({
        minLon: bounds.getWest(),
        minLat: bounds.getSouth(),
        maxLon: bounds.getEast(),
        maxLat: bounds.getNorth(),
      });
    },
  });

  return null;
}

function confidenceColor(confidenceTier: string): string {
  if (confidenceTier === "high") {
    return "#0f8b6d";
  }
  if (confidenceTier === "medium") {
    return "#c78b1f";
  }
  if (confidenceTier === "low") {
    return "#d1603d";
  }
  return "#a3333d";
}

function statusStrokeColor(status: string): string {
  if (status === "assigned") {
    return "#16444e";
  }
  if (status === "assigned_with_warnings") {
    return "#7d4a14";
  }
  return "#6c1f1f";
}

function accidentLabel(accident: AttributedAccidentListItem): string {
  return accident.corridor_label ?? accident.road_number ?? accident.accident_id;
}

export default function AttributionMap(props: AttributionMapProps): JSX.Element {
  const [focusRequest, setFocusRequest] = useState<BBoxQuery | null>(null);

  return (
    <section className="map-panel" aria-label="Attributed accident map">
      <div className="map-panel__header">
        <div>
          <p className="eyebrow">Map Inspection</p>
          <h2>Visible attributed accidents</h2>
          <p>
            Pan, zoom, or jump to a preset view to refresh the visible accident window and inspect
            how confidence changes across the network.
          </p>
        </div>
        <div className="map-actions">
          <button
            type="button"
            className="ghost-button"
            onClick={() => setFocusRequest(NATIONWIDE_BOUNDS)}
          >
            Nationwide view
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => setFocusRequest(CENTRAL_BOUNDS)}
          >
            Central focus
          </button>
        </div>
      </div>

      <div className="map-shell">
        <MapContainer className="corridor-map" bounds={bboxToLeafletBounds(props.activeBbox)}>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <MapViewportBridge
            focusRequest={focusRequest}
            onBoundsChange={(bbox) => {
              props.onViewportCommit(bbox);
              if (focusRequest) {
                setFocusRequest(null);
              }
            }}
          />
          {props.accidents.map((accident) => {
            const [lon, lat] = accident.geometry.coordinates;
            return (
              <CircleMarker
                key={accident.accident_id}
                center={[lat, lon]}
                eventHandlers={{
                  click: () => props.onAccidentSelect(accident.accident_id),
                }}
                pathOptions={{
                  color: statusStrokeColor(accident.attribution_status),
                  fillColor: confidenceColor(accident.confidence_tier),
                  fillOpacity: accident.accident_id === props.selectedAccidentId ? 0.95 : 0.72,
                  weight: accident.accident_id === props.selectedAccidentId ? 3 : 2,
                }}
                radius={accident.accident_id === props.selectedAccidentId ? 8 : 6}
              />
            );
          })}
        </MapContainer>
      </div>

      <div className="visible-corridor-list">
        <div className="visible-corridor-list__header">
          <h3>Visible accidents</h3>
          <p>{props.accidents.length.toLocaleString()} accidents in the current response.</p>
        </div>
        <ul>
          {props.accidents.map((accident) => (
            <li key={accident.accident_id}>
              <button
                type="button"
                className={
                  accident.accident_id === props.selectedAccidentId
                    ? "corridor-row corridor-row--selected"
                    : "corridor-row"
                }
                onClick={() => props.onAccidentSelect(accident.accident_id)}
              >
                <span>
                  {accidentLabel(accident)}
                  <span
                    className={`confidence-pill confidence-pill--${accident.confidence_tier}`}
                  >
                    {accident.confidence_tier}
                  </span>
                </span>
                <span className="accident-row__meta">
                  {accident.attribution_status}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
