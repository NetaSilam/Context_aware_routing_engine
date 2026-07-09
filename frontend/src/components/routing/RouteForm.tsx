import { useState } from "react";

import { geocode } from "../../api/routing";
import type { Coordinate, GeocodeResult } from "../../types/routing";

interface RouteFormProps {
  onSubmit: (origin: Coordinate, destination: Coordinate) => void;
  submitting: boolean;
}

interface AddressFieldState {
  query: string;
  candidates: GeocodeResult[] | null;
  selected: GeocodeResult | null;
  error: string | null;
  loading: boolean;
}

const EMPTY_FIELD: AddressFieldState = {
  query: "",
  candidates: null,
  selected: null,
  error: null,
  loading: false,
};

function AddressField(props: {
  label: string;
  state: AddressFieldState;
  onChange: (state: AddressFieldState) => void;
}) {
  const { label, state, onChange } = props;

  async function handleSearch() {
    if (!state.query.trim()) {
      return;
    }
    onChange({ ...state, loading: true, error: null, candidates: null, selected: null });
    try {
      const results = await geocode(state.query.trim());
      if (results.length === 0) {
        onChange({ ...state, loading: false, error: "No matches found for this address." });
        return;
      }
      onChange({
        ...state,
        loading: false,
        candidates: results,
        selected: results.length === 1 ? results[0] : null,
      });
    } catch (err) {
      onChange({
        ...state,
        loading: false,
        error: err instanceof Error ? err.message : "Geocoding failed.",
      });
    }
  }

  return (
    <label className="filter-field">
      <span>{label}</span>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          placeholder="e.g. Dizengoff 100, Tel Aviv"
          value={state.query}
          onChange={(event) => onChange({ ...state, query: event.target.value, selected: null })}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void handleSearch();
            }
          }}
        />
        <button type="button" className="ghost-button" onClick={() => void handleSearch()}>
          {state.loading ? "Searching…" : "Search"}
        </button>
      </div>
      {state.error ? <p className="error-banner">{state.error}</p> : null}
      {state.candidates && state.candidates.length > 1 ? (
        <select
          value={state.selected ? state.candidates.indexOf(state.selected) : ""}
          onChange={(event) => onChange({ ...state, selected: state.candidates![Number(event.target.value)] })}
        >
          <option value="" disabled>
            {state.candidates.length} matches - pick one
          </option>
          {state.candidates.map((candidate, index) => (
            <option key={`${candidate.lat}-${candidate.lon}`} value={index}>
              {candidate.label}
            </option>
          ))}
        </select>
      ) : null}
      {state.selected ? <p className="detail-panel__description">✓ {state.selected.label}</p> : null}
    </label>
  );
}

export default function RouteForm(props: RouteFormProps): JSX.Element {
  const [origin, setOrigin] = useState<AddressFieldState>(EMPTY_FIELD);
  const [destination, setDestination] = useState<AddressFieldState>(EMPTY_FIELD);

  const canSubmit = origin.selected !== null && destination.selected !== null && !props.submitting;

  return (
    <section className="filters-panel" aria-label="Plan a route">
      <div className="filters-panel__heading">
        <p className="eyebrow">Plan A Route</p>
        <h2>Enter an origin and destination</h2>
        <p>Search each address, confirm the match, then get a risk-aware route recommendation.</p>
      </div>

      <div className="filters-grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
        <AddressField label="Origin" state={origin} onChange={setOrigin} />
        <AddressField label="Destination" state={destination} onChange={setDestination} />
      </div>

      <div className="filters-actions">
        <button
          type="button"
          className="primary-button"
          disabled={!canSubmit}
          onClick={() =>
            origin.selected &&
            destination.selected &&
            props.onSubmit(
              { lat: origin.selected.lat, lon: origin.selected.lon },
              { lat: destination.selected.lat, lon: destination.selected.lon },
            )
          }
        >
          {props.submitting ? "Calculating route…" : "Get recommended route"}
        </button>
      </div>
    </section>
  );
}
