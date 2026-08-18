import { describe, expect, it } from "vitest";

import {
  bearingDegrees,
  createIntervalThrottle,
  createOffRouteDetector,
  createSeenIdTracker,
  distanceToPolylineMeters,
  formatManeuverText,
  haversineMeters,
  remainingRouteDistanceMeters,
} from "./navigation";
import type { RouteStep } from "../types/routeJobs";

describe("haversineMeters", () => {
  it("returns zero for identical points", () => {
    expect(haversineMeters({ lat: 32.08, lon: 34.78 }, { lat: 32.08, lon: 34.78 })).toBe(0);
  });

  it("returns roughly the right magnitude for a known short hop", () => {
    // Roughly 1.11km per 0.01 degree of latitude.
    const distance = haversineMeters({ lat: 32.0, lon: 34.78 }, { lat: 32.01, lon: 34.78 });
    expect(distance).toBeGreaterThan(1000);
    expect(distance).toBeLessThan(1200);
  });
});

describe("bearingDegrees", () => {
  it("is 0 (north) when moving straight up in latitude", () => {
    expect(bearingDegrees({ lat: 32.0, lon: 34.78 }, { lat: 32.01, lon: 34.78 })).toBeCloseTo(0, 0);
  });

  it("is 90 (east) when moving straight along the equator toward higher longitude", () => {
    expect(bearingDegrees({ lat: 0, lon: 34.78 }, { lat: 0, lon: 34.79 })).toBeCloseTo(90, 0);
  });

  it("is 180 (south) when moving straight down in latitude", () => {
    expect(bearingDegrees({ lat: 32.01, lon: 34.78 }, { lat: 32.0, lon: 34.78 })).toBeCloseTo(180, 0);
  });

  it("is 270 (west) when moving straight along the equator toward lower longitude", () => {
    expect(bearingDegrees({ lat: 0, lon: 34.79 }, { lat: 0, lon: 34.78 })).toBeCloseTo(270, 0);
  });

  it("stays within [0, 360)", () => {
    const bearing = bearingDegrees({ lat: 32.0, lon: 34.78 }, { lat: 31.99, lon: 34.77 });
    expect(bearing).toBeGreaterThanOrEqual(0);
    expect(bearing).toBeLessThan(360);
  });
});

describe("distanceToPolylineMeters", () => {
  const polyline = [
    { lat: 32.0, lon: 34.78 },
    { lat: 32.01, lon: 34.78 },
    { lat: 32.02, lon: 34.79 },
  ];

  it("is ~0 for a point on the polyline", () => {
    expect(distanceToPolylineMeters({ lat: 32.005, lon: 34.78 }, polyline)).toBeLessThan(1);
  });

  it("returns a large distance for a point far from every segment", () => {
    expect(distanceToPolylineMeters({ lat: 33.0, lon: 34.78 }, polyline)).toBeGreaterThan(50_000);
  });

  it("returns Infinity for an empty polyline", () => {
    expect(distanceToPolylineMeters({ lat: 32.0, lon: 34.78 }, [])).toBe(Infinity);
  });

  it("falls back to point distance for a single-point polyline", () => {
    const point = { lat: 32.0, lon: 34.78 };
    expect(distanceToPolylineMeters(point, [{ lat: 32.01, lon: 34.78 }])).toBeCloseTo(
      haversineMeters(point, { lat: 32.01, lon: 34.78 }),
      3,
    );
  });
});

describe("remainingRouteDistanceMeters", () => {
  // A straight line running due north, two ~1.11km segments (~2.22km total).
  const straightLine = [
    { lat: 32.0, lon: 34.78 },
    { lat: 32.01, lon: 34.78 },
    { lat: 32.02, lon: 34.78 },
  ];

  it("is ~ the full route length when at the very start", () => {
    const remaining = remainingRouteDistanceMeters(straightLine[0], straightLine);
    expect(remaining).toBeGreaterThan(2100);
    expect(remaining).toBeLessThan(2300);
  });

  it("is ~ half the route once past the first segment's midpoint", () => {
    const remaining = remainingRouteDistanceMeters({ lat: 32.015, lon: 34.78 }, straightLine);
    expect(remaining).toBeGreaterThan(500);
    expect(remaining).toBeLessThan(650);
  });

  it("is ~0 at the very end", () => {
    const remaining = remainingRouteDistanceMeters(straightLine[2], straightLine);
    expect(remaining).toBeLessThan(1);
  });

  it("counts remaining distance from the nearest point on the route, not the destination", () => {
    // Off to the side, but abeam the first segment's midpoint — the straight-line distance
    // to the destination is much larger than the *remaining route* distance should be.
    const remaining = remainingRouteDistanceMeters({ lat: 32.005, lon: 34.90 }, straightLine);
    const straightLineToEnd = haversineMeters({ lat: 32.005, lon: 34.90 }, straightLine[2]);
    expect(remaining).toBeLessThan(straightLineToEnd);
  });

  it("is 0 for a polyline with fewer than two points", () => {
    expect(remainingRouteDistanceMeters(straightLine[0], [])).toBe(0);
    expect(remainingRouteDistanceMeters(straightLine[0], [straightLine[0]])).toBe(0);
  });
});

describe("createOffRouteDetector", () => {
  it("does not trigger on a single noisy reading", () => {
    const detector = createOffRouteDetector({ thresholdMeters: 40, requiredConsecutiveTicks: 3 });
    expect(detector.check(100)).toBe(false);
    expect(detector.check(5)).toBe(false);
  });

  it("triggers only after the required number of consecutive over-threshold readings", () => {
    const detector = createOffRouteDetector({ thresholdMeters: 40, requiredConsecutiveTicks: 3 });
    expect(detector.check(100)).toBe(false);
    expect(detector.check(100)).toBe(false);
    expect(detector.check(100)).toBe(true);
  });

  it("resets the streak when a reading comes back under threshold", () => {
    const detector = createOffRouteDetector({ thresholdMeters: 40, requiredConsecutiveTicks: 3 });
    detector.check(100);
    detector.check(100);
    detector.check(5); // back on route, resets the streak
    expect(detector.check(100)).toBe(false);
    expect(detector.check(100)).toBe(false);
    expect(detector.check(100)).toBe(true);
  });

  it("reset() clears the streak on demand (e.g. after a successful reroute)", () => {
    const detector = createOffRouteDetector({ thresholdMeters: 40, requiredConsecutiveTicks: 2 });
    detector.check(100);
    detector.reset();
    expect(detector.check(100)).toBe(false);
  });
});

describe("createIntervalThrottle", () => {
  it("allows the first call and blocks calls within the interval", () => {
    const attempt = createIntervalThrottle(15_000);
    expect(attempt(0)).toBe(true);
    expect(attempt(5_000)).toBe(false);
    expect(attempt(14_999)).toBe(false);
  });

  it("allows a call once the interval has elapsed", () => {
    const attempt = createIntervalThrottle(15_000);
    attempt(0);
    expect(attempt(15_000)).toBe(true);
  });
});

describe("createSeenIdTracker", () => {
  it("returns true only the first time an id is seen", () => {
    const markIfNew = createSeenIdTracker();
    expect(markIfNew("post-1")).toBe(true);
    expect(markIfNew("post-1")).toBe(false);
    expect(markIfNew("post-2")).toBe(true);
  });
});

describe("formatManeuverText", () => {
  function step(overrides: Partial<RouteStep>): RouteStep {
    return {
      distance: 200,
      duration: 30,
      name: "Herzl St",
      maneuver: { type: "turn", modifier: "left", location: null },
      ...overrides,
    };
  }

  it("formats a turn with distance, direction, and street name", () => {
    expect(formatManeuverText(step({}), 200)).toBe("In 200m, turn left onto Herzl St");
  });

  it("formats distances a kilometer or more in km", () => {
    expect(formatManeuverText(step({}), 1500)).toBe("In 1.5 km, turn left onto Herzl St");
  });

  it("formats arrival without a distance", () => {
    expect(formatManeuverText(step({ maneuver: { type: "arrive", modifier: null, location: null } }), 20)).toBe(
      "Arrive at your destination",
    );
  });

  it("omits the street name when it is empty", () => {
    expect(formatManeuverText(step({ name: "" }), 200)).toBe("In 200m, turn left");
  });

  it("falls back to a generic direction when no modifier is present", () => {
    expect(formatManeuverText(step({ maneuver: { type: "turn", modifier: null, location: null } }), 200)).toBe(
      "In 200m, turn ahead onto Herzl St",
    );
  });
});
