interface CanonicalNetworkFiltersProps {
  availableFamilies: string[];
  availableBuildBases: string[];
  familyFilter: string;
  buildBasisFilter: string;
  roadIdentityFilter: "all" | "with-road" | "without-road";
  onFamilyFilterChange: (value: string) => void;
  onBuildBasisFilterChange: (value: string) => void;
  onRoadIdentityFilterChange: (value: "all" | "with-road" | "without-road") => void;
}

export default function CanonicalNetworkFilters(
  props: CanonicalNetworkFiltersProps,
): JSX.Element {
  return (
    <section className="filters-panel" aria-label="Canonical network filters">
      <div className="filters-panel__heading">
        <p className="eyebrow">Structural Filters</p>
        <h2>Corridor inspection controls</h2>
        <p>
          This slice stays structural on purpose: corridor family, build basis, and road
          identity only.
        </p>
      </div>

      <div className="filters-grid">
        <label className="filter-field">
          <span>Corridor family</span>
          <select
            value={props.familyFilter}
            onChange={(event) => props.onFamilyFilterChange(event.target.value)}
          >
            <option value="all">All families</option>
            {props.availableFamilies.map((family) => (
              <option key={family} value={family}>
                {family}
              </option>
            ))}
          </select>
        </label>

        <label className="filter-field">
          <span>Build basis</span>
          <select
            value={props.buildBasisFilter}
            onChange={(event) => props.onBuildBasisFilterChange(event.target.value)}
          >
            <option value="all">All build bases</option>
            {props.availableBuildBases.map((basis) => (
              <option key={basis} value={basis}>
                {basis}
              </option>
            ))}
          </select>
        </label>

        <label className="filter-field">
          <span>Road identity</span>
          <select
            value={props.roadIdentityFilter}
            onChange={(event) =>
              props.onRoadIdentityFilterChange(
                event.target.value as "all" | "with-road" | "without-road",
              )
            }
          >
            <option value="all">All corridors</option>
            <option value="with-road">With road identity</option>
            <option value="without-road">Without road identity</option>
          </select>
        </label>
      </div>
    </section>
  );
}
