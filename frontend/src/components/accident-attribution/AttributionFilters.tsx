interface AttributionFiltersProps {
  statusFilter: string;
  confidenceFilter: string;
  yearFilter: string;
  onStatusFilterChange: (value: string) => void;
  onConfidenceFilterChange: (value: string) => void;
  onYearFilterChange: (value: string) => void;
  onReset: () => void;
}

export default function AttributionFilters(
  props: AttributionFiltersProps,
): JSX.Element {
  return (
    <section className="filters-panel" aria-label="Accident attribution filters">
      <div className="filters-panel__heading">
        <p className="eyebrow">Attribution Filters</p>
        <h2>Inspection controls</h2>
        <p>
          Keep the surface narrow: status, confidence, and optional year only.
        </p>
      </div>

      <div className="filters-grid">
        <label className="filter-field">
          <span>Attribution status</span>
          <select
            value={props.statusFilter}
            onChange={(event) => props.onStatusFilterChange(event.target.value)}
          >
            <option value="all">All statuses</option>
            <option value="assigned">assigned</option>
            <option value="assigned_with_warnings">assigned_with_warnings</option>
            <option value="unresolved">unresolved</option>
          </select>
        </label>

        <label className="filter-field">
          <span>Confidence tier</span>
          <select
            value={props.confidenceFilter}
            onChange={(event) => props.onConfidenceFilterChange(event.target.value)}
          >
            <option value="all">All confidence tiers</option>
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
            <option value="unresolved">unresolved</option>
          </select>
        </label>

        <label className="filter-field">
          <span>Accident year</span>
          <input
            type="number"
            inputMode="numeric"
            min="2000"
            placeholder="Any year"
            value={props.yearFilter}
            onChange={(event) => props.onYearFilterChange(event.target.value)}
          />
        </label>
      </div>

      <div className="filters-actions">
        <button type="button" className="ghost-button" onClick={props.onReset}>
          Reset filters
        </button>
      </div>
    </section>
  );
}
