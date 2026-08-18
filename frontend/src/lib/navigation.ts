import type { RouteStep } from "../types/routeJobs";

export interface LatLng {
  lat: number;
  lon: number;
}

const EARTH_RADIUS_METERS = 6_371_000;

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

export function haversineMeters(a: LatLng, b: LatLng): number {
  const dLat = toRadians(b.lat - a.lat);
  const dLon = toRadians(b.lon - a.lon);
  const sinLat = Math.sin(dLat / 2);
  const sinLon = Math.sin(dLon / 2);
  const h =
    sinLat * sinLat + Math.cos(toRadians(a.lat)) * Math.cos(toRadians(b.lat)) * sinLon * sinLon;
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.min(1, Math.sqrt(h)));
}

function projectOntoSegment(point: LatLng, start: LatLng, end: LatLng): { closest: LatLng; distance: number } {
  // Equirectangular local-plane projection: adequate at route/segment scale and far
  // cheaper than true great-circle projection, which off-route checks don't need.
  const refLat = toRadians(start.lat);
  const project = (p: LatLng) => ({ x: toRadians(p.lon) * Math.cos(refLat), y: toRadians(p.lat) });
  const p = project(point);
  const s = project(start);
  const e = project(end);
  const dx = e.x - s.x;
  const dy = e.y - s.y;
  const lengthSquared = dx * dx + dy * dy;
  const t =
    lengthSquared === 0
      ? 0
      : Math.max(0, Math.min(1, ((p.x - s.x) * dx + (p.y - s.y) * dy) / lengthSquared));
  const closest: LatLng = {
    lat: start.lat + t * (end.lat - start.lat),
    lon: start.lon + t * (end.lon - start.lon),
  };
  return { closest, distance: haversineMeters(point, closest) };
}

/** Compass bearing (0-360, 0 = north) from one point toward another, for pointing a
 * direction-of-travel arrow — not used for distance, so no need for haversine precision. */
export function bearingDegrees(from: LatLng, to: LatLng): number {
  const lat1 = toRadians(from.lat);
  const lat2 = toRadians(to.lat);
  const deltaLon = toRadians(to.lon - from.lon);
  const y = Math.sin(deltaLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(deltaLon);
  const degrees = (Math.atan2(y, x) * 180) / Math.PI;
  return (degrees + 360) % 360;
}

export function distanceToPolylineMeters(point: LatLng, polyline: LatLng[]): number {
  if (polyline.length === 0) return Infinity;
  if (polyline.length === 1) return haversineMeters(point, polyline[0]);
  let min = Infinity;
  for (let index = 0; index < polyline.length - 1; index += 1) {
    const { distance } = projectOntoSegment(point, polyline[index], polyline[index + 1]);
    if (distance < min) min = distance;
  }
  return min;
}

/** Distance remaining to the end of the route, following the road (polyline) rather than
 * a straight line to the destination — a straight line badly undercounts distance early
 * in a route with turns, which would make an ETA computed from it too optimistic. */
export function remainingRouteDistanceMeters(point: LatLng, polyline: LatLng[]): number {
  if (polyline.length < 2) return 0;

  let bestDistance = Infinity;
  let bestSegmentIndex = 0;
  let bestClosest: LatLng = polyline[0];
  for (let index = 0; index < polyline.length - 1; index += 1) {
    const { closest, distance } = projectOntoSegment(point, polyline[index], polyline[index + 1]);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestSegmentIndex = index;
      bestClosest = closest;
    }
  }

  let remaining = haversineMeters(bestClosest, polyline[bestSegmentIndex + 1]);
  for (let index = bestSegmentIndex + 1; index < polyline.length - 1; index += 1) {
    remaining += haversineMeters(polyline[index], polyline[index + 1]);
  }
  return remaining;
}

export interface OffRouteDetector {
  /** Returns true once `requiredConsecutiveTicks` readings in a row exceed the threshold. */
  check(distanceMeters: number): boolean;
  /** Call after a successful reroute so debouncing restarts against the new route. */
  reset(): void;
}

export function createOffRouteDetector(options: {
  thresholdMeters: number;
  requiredConsecutiveTicks: number;
}): OffRouteDetector {
  let consecutiveOverThreshold = 0;
  return {
    check(distanceMeters: number): boolean {
      consecutiveOverThreshold =
        distanceMeters > options.thresholdMeters ? consecutiveOverThreshold + 1 : 0;
      return consecutiveOverThreshold >= options.requiredConsecutiveTicks;
    },
    reset(): void {
      consecutiveOverThreshold = 0;
    },
  };
}

/** Client-side backstop so a stuck off-route reading can't spam the reroute endpoint,
 * independent of and in addition to the server-side rate limit. */
export function createIntervalThrottle(minIntervalMs: number): (nowMs: number) => boolean {
  let lastRunAt: number | null = null;
  return (nowMs: number): boolean => {
    if (lastRunAt !== null && nowMs - lastRunAt < minIntervalMs) return false;
    lastRunAt = nowMs;
    return true;
  };
}

export function createSeenIdTracker(): (id: string) => boolean {
  const seen = new Set<string>();
  return (id: string): boolean => {
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  };
}

const MODIFIER_TEXT: Record<string, string> = {
  left: "left",
  right: "right",
  "slight left": "slightly left",
  "slight right": "slightly right",
  "sharp left": "sharply left",
  "sharp right": "sharply right",
  uturn: "a U-turn",
  straight: "straight",
};

function formatDistance(distanceMeters: number): string {
  if (distanceMeters >= 1000) return `${(distanceMeters / 1000).toFixed(1)} km`;
  return `${Math.max(10, Math.round(distanceMeters / 10) * 10)}m`;
}

export function formatManeuverText(step: RouteStep, distanceToManeuverMeters: number): string {
  const distanceText = formatDistance(distanceToManeuverMeters);
  const streetSuffix = step.name ? ` onto ${step.name}` : "";
  switch (step.maneuver.type) {
    case "depart":
      return `Head out${streetSuffix}`;
    case "arrive":
      return "Arrive at your destination";
    case "roundabout":
    case "rotary":
      return `In ${distanceText}, take the roundabout${streetSuffix}`;
    case "turn":
    case "end of road":
    case "fork":
    case "merge":
    case "ramp": {
      const direction = step.maneuver.modifier
        ? MODIFIER_TEXT[step.maneuver.modifier] ?? step.maneuver.modifier
        : "ahead";
      return `In ${distanceText}, turn ${direction}${streetSuffix}`;
    }
    default:
      return `Continue${streetSuffix} for ${distanceText}`;
  }
}
