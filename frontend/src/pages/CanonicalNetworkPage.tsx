import { useEffect, useState } from "react";

import {
  createCanonicalNetworkClient,
  type BBoxQuery,
} from "../api/canonicalNetwork";
import CanonicalNetworkFilters from "../components/canonical-network/CanonicalNetworkFilters";
import CorridorDetailPanel from "../components/canonical-network/CorridorDetailPanel";
import CorridorMap from "../components/canonical-network/CorridorMap";
import SummaryCards from "../components/canonical-network/SummaryCards";
import type {
  CanonicalNetworkSummary,
  CorridorDetail,
  CorridorListItem,
} from "../types/canonicalNetwork";

const DEFAULT_BBOX: BBoxQuery = {
  minLon: 34.0,
  minLat: 29.4,
  maxLon: 36.0,
  maxLat: 33.5,
};

const DEFAULT_CORRIDOR_LIMIT = 250;

export interface CanonicalNetworkPageProps {
  client?: ReturnType<typeof createCanonicalNetworkClient>;
}

export default function CanonicalNetworkPage(
  props: CanonicalNetworkPageProps,
): JSX.Element {
  const [client] = useState(() => props.client ?? createCanonicalNetworkClient());
  const [summary, setSummary] = useState<CanonicalNetworkSummary | null>(null);
  const [activeBbox, setActiveBbox] = useState<BBoxQuery>(DEFAULT_BBOX);
  const [corridors, setCorridors] = useState<CorridorListItem[]>([]);
  const [selectedCorridorId, setSelectedCorridorId] = useState<string | null>(null);
  const [selectedCorridor, setSelectedCorridor] = useState<CorridorDetail | null>(null);
  const [familyFilter, setFamilyFilter] = useState("all");
  const [buildBasisFilter, setBuildBasisFilter] = useState("all");
  const [roadIdentityFilter, setRoadIdentityFilter] = useState<
    "all" | "with-road" | "without-road"
  >("all");
  const [isLoadingSummary, setIsLoadingSummary] = useState(true);
  const [isLoadingCorridors, setIsLoadingCorridors] = useState(true);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [corridorError, setCorridorError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoadingSummary(true);
    setSummaryError(null);
    void client
      .getSummary()
      .then((response) => {
        if (!cancelled) {
          setSummary(response);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSummaryError(error instanceof Error ? error.message : "Failed to load summary.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingSummary(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    setIsLoadingCorridors(true);
    setCorridorError(null);
    void client
      .getCorridors(activeBbox, DEFAULT_CORRIDOR_LIMIT)
      .then((response) => {
        if (!cancelled) {
          setCorridors(response.corridors);
          setSelectedCorridorId(null);
          setSelectedCorridor(null);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setCorridorError(error instanceof Error ? error.message : "Failed to load corridors.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingCorridors(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeBbox, client]);

  useEffect(() => {
    if (!selectedCorridorId) {
      return;
    }
    let cancelled = false;
    setIsLoadingDetail(true);
    setDetailError(null);
    void client
      .getCorridorDetail(selectedCorridorId)
      .then((response) => {
        if (!cancelled) {
          setSelectedCorridor(response);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setDetailError(error instanceof Error ? error.message : "Failed to load corridor detail.");
          setSelectedCorridor(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingDetail(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, selectedCorridorId]);

  const filteredCorridors = corridors.filter((corridor) => {
    if (familyFilter !== "all" && corridor.corridor_family !== familyFilter) {
      return false;
    }
    if (buildBasisFilter !== "all" && corridor.build_basis !== buildBasisFilter) {
      return false;
    }
    if (roadIdentityFilter === "with-road" && corridor.road_id == null) {
      return false;
    }
    if (roadIdentityFilter === "without-road" && corridor.road_id != null) {
      return false;
    }
    return true;
  });

  const families = Array.from(new Set(corridors.map((corridor) => corridor.corridor_family))).sort();
  const buildBases = Array.from(new Set(corridors.map((corridor) => corridor.build_basis))).sort();

  return (
    <main className="page-shell">
      <section className="hero-panel">
        <p className="eyebrow">Canonical Network Backbone</p>
        <h1>Validation surface for the first authoritative spatial layer</h1>
        <p className="hero-panel__copy">
          This page exists to inspect how the national corridor layer was built before accident,
          route, and hotspot features are allowed to depend on it.
        </p>
      </section>

      {summaryError ? <p className="error-banner">{summaryError}</p> : null}
      {isLoadingSummary && !summary ? <p className="loading-banner">Loading summary…</p> : null}
      {summary ? <SummaryCards summary={summary} /> : null}

      <CanonicalNetworkFilters
        availableBuildBases={buildBases}
        availableFamilies={families}
        buildBasisFilter={buildBasisFilter}
        familyFilter={familyFilter}
        roadIdentityFilter={roadIdentityFilter}
        onBuildBasisFilterChange={setBuildBasisFilter}
        onFamilyFilterChange={setFamilyFilter}
        onRoadIdentityFilterChange={setRoadIdentityFilter}
      />

      <section className="workspace-grid">
        <div>
          {corridorError ? <p className="error-banner">{corridorError}</p> : null}
          {isLoadingCorridors ? <p className="loading-banner">Loading visible corridors…</p> : null}
          <CorridorMap
            activeBbox={activeBbox}
            corridors={filteredCorridors}
            onCorridorSelect={setSelectedCorridorId}
            onViewportCommit={setActiveBbox}
            selectedCorridorId={selectedCorridorId}
          />
        </div>
        <CorridorDetailPanel
          detail={selectedCorridor}
          error={detailError}
          loading={isLoadingDetail}
        />
      </section>
    </main>
  );
}
