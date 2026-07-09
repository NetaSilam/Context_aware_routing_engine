import { useEffect, useState } from "react";
import {
  MapContainer,
  Polyline,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";

import type { BBoxQuery } from "../../api/canonicalNetwork";
import type { CorridorListItem } from "../../types/canonicalNetwork";

type BoundsTuple = [[number, number], [number, number]];

interface CorridorMapProps {
  corridors: CorridorListItem[];
  selectedCorridorId: string | null;
  activeBbox: BBoxQuery;
  onViewportCommit: (bbox: BBoxQuery) => void;
  onCorridorSelect: (corridorId: string) => void;
}

const NATIONWIDE_BOUNDS: BBoxQuery = {
  minLon: 34.0,
  minLat: 29.4,
  maxLon: 36.0,
  maxLat: 33.5,
};

const COASTAL_BOUNDS: BBoxQuery = {
  minLon: 34.65,
  minLat: 31.75,
  maxLon: 35.1,
  maxLat: 32.35,
};

function geoJsonToLatLngs(item: CorridorListItem): [number, number][][] {
  if (item.geometry.type === "LineString") {
    return [item.geometry.coordinates as [number, number][]].map((segment) =>
      segment.map(([lon, lat]) => [lat, lon]),
    );
  }
  return (item.geometry.coordinates as [number, number][][]).map((segment) =>
    segment.map(([lon, lat]) => [lat, lon]),
  );
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
    props.onBoundsChange(props.focusRequest);
  }, [map, props]);

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

function bboxToLeafletBounds(bbox: BBoxQuery): BoundsTuple {
  return [
    [bbox.minLat, bbox.minLon],
    [bbox.maxLat, bbox.maxLon],
  ];
}

export default function CorridorMap(props: CorridorMapProps): JSX.Element {
  const [visibleBounds, setVisibleBounds] = useState<BBoxQuery>(props.activeBbox);
  const [focusRequest, setFocusRequest] = useState<BBoxQuery | null>(null);

  return (
    <section className="map-panel" aria-label="Corridor map">
      <div className="map-panel__header">
        <div>
          <p className="eyebrow">Map Inspection</p>
          <h2>Corridor display geometry</h2>
          <p>
            Load only the current visible map window. Corridor geometry here uses the simplified
            display layer, not the analytical source geometry.
          </p>
        </div>
        <div className="map-actions">
          <button
            type="button"
            className="ghost-button"
            onClick={() => {
              setFocusRequest(NATIONWIDE_BOUNDS);
              props.onViewportCommit(NATIONWIDE_BOUNDS);
            }}
          >
            Nationwide view
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => {
              setFocusRequest(COASTAL_BOUNDS);
              props.onViewportCommit(COASTAL_BOUNDS);
            }}
          >
            Coastal focus
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={() => props.onViewportCommit(visibleBounds)}
          >
            Load visible area
          </button>
        </div>
      </div>

      <div className="map-shell">
        <MapContainer
          className="corridor-map"
          bounds={bboxToLeafletBounds(props.activeBbox)}
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MapViewportBridge
            focusRequest={focusRequest}
            onBoundsChange={(bbox) => {
              setVisibleBounds(bbox);
              if (focusRequest) {
                setFocusRequest(null);
              }
            }}
          />
          {props.corridors.map((corridor) =>
            geoJsonToLatLngs(corridor).map((segment, index) => (
              <Polyline
                key={`${corridor.corridor_id}-${index}`}
                eventHandlers={{
                  click: () => props.onCorridorSelect(corridor.corridor_id),
                }}
                pathOptions={{
                  color:
                    corridor.corridor_id === props.selectedCorridorId ? "#f28444" : "#0d7288",
                  weight: corridor.corridor_id === props.selectedCorridorId ? 5 : 3,
                  opacity: 0.86,
                }}
                positions={segment}
              />
            )),
          )}
        </MapContainer>
      </div>

      <div className="visible-corridor-list">
        <div className="visible-corridor-list__header">
          <h3>Visible corridors</h3>
          <p>{props.corridors.length.toLocaleString()} corridors in the current client-side view.</p>
        </div>
        <ul>
          {props.corridors.map((corridor) => (
            <li key={corridor.corridor_id}>
              <button
                type="button"
                className={
                  corridor.corridor_id === props.selectedCorridorId
                    ? "corridor-row corridor-row--selected"
                    : "corridor-row"
                }
                onClick={() => props.onCorridorSelect(corridor.corridor_id)}
              >
                <span>{corridor.primary_name ?? corridor.primary_ref ?? corridor.corridor_id}</span>
                <span>{corridor.corridor_family}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
