import { useEffect, useState } from "react";

import {
  createAccidentAttributionClient,
  type BBoxQuery,
} from "../api/accidentAttribution";
import AttributionDetailPanel from "../components/accident-attribution/AttributionDetailPanel";
import AttributionFilters from "../components/accident-attribution/AttributionFilters";
import AttributionMap from "../components/accident-attribution/AttributionMap";
import type {
  AccidentAttributionSummary,
  AttributedAccidentDetail,
  AttributedAccidentListItem,
} from "../types/accidentAttribution";

const DEFAULT_BBOX: BBoxQuery = {
  minLon: 34.0,
  minLat: 29.4,
  maxLon: 36.0,
  maxLat: 33.5,
};

const DEFAULT_ACCIDENT_LIMIT = 400;

export interface AccidentAttributionPageProps {
  client?: ReturnType<typeof createAccidentAttributionClient>;
}

function countLabel(value: Record<string, number>, key: string): string {
  return (value[key] ?? 0).toLocaleString();
}

export default function AccidentAttributionPage(
  props: AccidentAttributionPageProps,
): JSX.Element {
  const [client] = useState(() => props.client ?? createAccidentAttributionClient());
  const [summary, setSummary] = useState<AccidentAttributionSummary | null>(null);
  const [activeBbox, setActiveBbox] = useState<BBoxQuery>(DEFAULT_BBOX);
  const [accidents, setAccidents] = useState<AttributedAccidentListItem[]>([]);
  const [selectedAccidentId, setSelectedAccidentId] = useState<string | null>(null);
  const [selectedAccident, setSelectedAccident] = useState<AttributedAccidentDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [confidenceFilter, setConfidenceFilter] = useState("all");
  const [yearFilter, setYearFilter] = useState("");
  const [isLoadingSummary, setIsLoadingSummary] = useState(true);
  const [isLoadingAccidents, setIsLoadingAccidents] = useState(true);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [accidentError, setAccidentError] = useState<string | null>(null);
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
          setSummaryError(
            error instanceof Error ? error.message : "Failed to load attribution summary.",
          );
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
    setIsLoadingAccidents(true);
    setAccidentError(null);
    const yearValue = yearFilter.trim() ? Number(yearFilter.trim()) : undefined;
    void client
      .getAccidents(
        activeBbox,
        {
          status: statusFilter === "all" ? undefined : statusFilter,
          confidence: confidenceFilter === "all" ? undefined : confidenceFilter,
          year: Number.isFinite(yearValue) ? yearValue : undefined,
        },
        DEFAULT_ACCIDENT_LIMIT,
      )
      .then((response) => {
        if (cancelled) {
          return;
        }
        setAccidents(response.accidents);
        const visibleIds = new Set(response.accidents.map((accident) => accident.accident_id));
        setSelectedAccidentId((currentId) =>
          currentId !== null && visibleIds.has(currentId) ? currentId : null,
        );
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setAccidentError(
            error instanceof Error ? error.message : "Failed to load visible accidents.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingAccidents(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeBbox, client, confidenceFilter, statusFilter, yearFilter]);

  useEffect(() => {
    if (selectedAccidentId !== null) {
      return;
    }
    setSelectedAccident(null);
    setDetailError(null);
    setIsLoadingDetail(false);
  }, [selectedAccidentId]);

  useEffect(() => {
    if (!selectedAccidentId) {
      return;
    }
    let cancelled = false;
    setIsLoadingDetail(true);
    setDetailError(null);
    void client
      .getAccidentDetail(selectedAccidentId)
      .then((response) => {
        if (!cancelled) {
          setSelectedAccident(response);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setDetailError(
            error instanceof Error ? error.message : "Failed to load accident detail.",
          );
          setSelectedAccident(null);
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
  }, [client, selectedAccidentId]);

  const summaryCards = summary
    ? [
        {
          label: "Total Accidents",
          value: summary.total_accident_count.toLocaleString(),
          note: `${summary.review_needed_count.toLocaleString()} rows are flagged for review`,
        },
        {
          label: "Assigned",
          value: countLabel(summary.status_breakdown, "assigned"),
          note: `${Math.round(summary.assigned_rate * 100)}% of all persisted accidents`,
        },
        {
          label: "Warnings",
          value: countLabel(summary.status_breakdown, "assigned_with_warnings"),
          note: `${countLabel(summary.confidence_breakdown, "low")} low-confidence rows`,
        },
        {
          label: "Unresolved",
          value: countLabel(summary.status_breakdown, "unresolved"),
          note: `${countLabel(summary.unresolved_reason_breakdown, "missing_geometry")} missing-geometry cases`,
        },
      ]
    : [];

  return (
    <main className="page-shell">
      <section className="hero-panel">
        <p className="eyebrow">Accident-to-Corridor Attribution</p>
        <h1>Deterministic historical accident assignment on top of the canonical corridor layer</h1>
        <p className="hero-panel__copy">
          This MVP slice persists every accident, exposes confidence and unresolved reasons, and
          keeps the result inspectable through a bbox-driven map and detail panel.
        </p>
      </section>

      {summaryError ? <p className="error-banner">{summaryError}</p> : null}
      {isLoadingSummary && !summary ? <p className="loading-banner">Loading summary...</p> : null}
      {summary ? (
        <section className="summary-cards" aria-label="Accident attribution summary">
          {summaryCards.map((card) => (
            <article key={card.label} className="summary-card">
              <p className="summary-card__label">{card.label}</p>
              <p className="summary-card__value">{card.value}</p>
              <p className="summary-card__note">{card.note}</p>
            </article>
          ))}
        </section>
      ) : null}

      <AttributionFilters
        statusFilter={statusFilter}
        confidenceFilter={confidenceFilter}
        yearFilter={yearFilter}
        onStatusFilterChange={setStatusFilter}
        onConfidenceFilterChange={setConfidenceFilter}
        onYearFilterChange={setYearFilter}
        onReset={() => {
          setStatusFilter("all");
          setConfidenceFilter("all");
          setYearFilter("");
        }}
      />

      <section className="workspace-grid">
        <div>
          {accidentError ? <p className="error-banner">{accidentError}</p> : null}
          {isLoadingAccidents ? <p className="loading-banner">Loading visible accidents...</p> : null}
          <AttributionMap
            activeBbox={activeBbox}
            accidents={accidents}
            onAccidentSelect={setSelectedAccidentId}
            onViewportCommit={setActiveBbox}
            selectedAccidentId={selectedAccidentId}
          />
        </div>
        <AttributionDetailPanel
          detail={selectedAccident}
          error={detailError}
          loading={isLoadingDetail}
        />
      </section>
    </main>
  );
}
