import { useEffect, useRef, useState } from "react";
import { MapContainer, Polyline, TileLayer, useMap, useMapEvents } from "react-leaflet";

import { listNearbyPosts } from "../api/forum";
import { RerouteError, reroute } from "../api/liveRouting";
import { NOTIFICATIONS_STREAM_URL } from "../api/notifications";
import {
  type LatLng,
  bearingDegrees,
  createIntervalThrottle,
  createOffRouteDetector,
  createSeenIdTracker,
  distanceToPolylineMeters,
  formatManeuverText,
  haversineMeters,
  remainingRouteDistanceMeters,
} from "../lib/navigation";
import { loadNavigationSession, saveNavigationSession } from "../lib/navigationSession";
import type { NavigationHandoff } from "../types/navigation";
import type { PostSummary } from "../types/forum";
import type { RouteCandidateResult } from "../types/routeJobs";

interface NavigatePageProps {
  handoff: NavigationHandoff;
  onExit: () => void;
}

const OFF_ROUTE_THRESHOLD_METERS = 45;
const OFF_ROUTE_CONSECUTIVE_TICKS = 3;
const REROUTE_MIN_INTERVAL_MS = 15_000;
const MANEUVER_ADVANCE_METERS = 25;
const ARRIVAL_THRESHOLD_METERS = 30;
const HAZARD_ALERT_RADIUS_METERS = 150;
const HAZARD_REFRESH_INTERVAL_MS = 90_000;
const HAZARD_BBOX_PADDING_DEGREES = 0.02;
const ANNOUNCE_DISTANCES_METERS = [300, 100];
const NAV_ZOOM_LEVEL = 18;
// Below this, GPS noise makes bearing meaningless (e.g. stopped at a light) — keep the
// last known heading instead of letting the map spin randomly.
const MIN_MOVEMENT_FOR_HEADING_METERS = 3;

interface WakeLockSentinelLike {
  release: () => Promise<void>;
}
interface WakeLockLike {
  request: (type: "screen") => Promise<WakeLockSentinelLike>;
}

function getWakeLock(): WakeLockLike | null {
  // Cast through `unknown` rather than `interface extends Navigator`: this API is still
  // experimental, and this sidesteps any conflict with however the current TS lib.dom
  // version happens to type (or not type) `navigator.wakeLock`.
  const candidate = (navigator as unknown as { wakeLock?: WakeLockLike }).wakeLock;
  return candidate ?? null;
}

function toLatLngPath(candidate: RouteCandidateResult): LatLng[] {
  return candidate.geometry.coordinates.map(([longitude, latitude]) => ({ lat: latitude, lon: longitude }));
}

function speak(text: string): void {
  if (typeof window === "undefined" || typeof window.speechSynthesis === "undefined") return;
  try {
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  } catch {
    // Voice is an enhancement; a synthesis failure must never interrupt navigation.
  }
}

function bboxAround(candidate: RouteCandidateResult): { minLongitude: number; minLatitude: number; maxLongitude: number; maxLatitude: number } {
  const longitudes = candidate.geometry.coordinates.map(([lon]) => lon);
  const latitudes = candidate.geometry.coordinates.map(([, lat]) => lat);
  return {
    minLongitude: Math.min(...longitudes) - HAZARD_BBOX_PADDING_DEGREES,
    maxLongitude: Math.max(...longitudes) + HAZARD_BBOX_PADDING_DEGREES,
    minLatitude: Math.min(...latitudes) - HAZARD_BBOX_PADDING_DEGREES,
    maxLatitude: Math.max(...latitudes) + HAZARD_BBOX_PADDING_DEGREES,
  };
}

function FollowPosition({ position, enabled }: { position: LatLng | null; enabled: boolean }): null {
  const map = useMap();
  useEffect(() => {
    // Always target the fixed nav zoom, not map.getZoom() — otherwise returning to follow
    // mode after zooming out in free-look leaves the view stuck at that zoomed-out level.
    if (position && enabled) map.setView([position.lat, position.lon], NAV_ZOOM_LEVEL);
  }, [position, enabled, map]);
  return null;
}

// Detects the user manually dragging or zooming the map, so we can drop out of locked
// follow+rotate mode into free-look — matches how Waze/Google Maps switch out of "follow
// me" the moment you touch the map, showing a button to snap back. Both events only fire
// for genuine user interaction, not for this app's own programmatic setView/zoom calls
// (FollowPosition never changes zoom, so zoomstart is safe to use here too).
function FreeLookOnInteraction({ onInteraction }: { onInteraction: () => void }): null {
  useMapEvents({ dragstart: onInteraction, zoomstart: onInteraction });
  return null;
}

// Leaflet doesn't notice its container was resized via JS/CSS on its own — it needs an
// explicit nudge to recompute its viewport and load tiles for the newly-visible area,
// otherwise the enlarged (diagonal-sized) region beyond its original size stays untiled.
function InvalidateSizeOnResize({ watch }: { watch: number }): null {
  const map = useMap();
  useEffect(() => {
    map.invalidateSize();
  }, [watch, map]);
  return null;
}

export default function NavigatePage({ handoff, onExit }: NavigatePageProps): JSX.Element {
  // Resumes mid-route after a refresh/crash instead of always restarting at the
  // handoff's original candidate and step 0.
  const [candidate, setCandidate] = useState<RouteCandidateResult>(
    () => loadNavigationSession()?.candidate ?? handoff.candidate,
  );
  const [position, setPosition] = useState<LatLng | null>(null);
  const [heading, setHeading] = useState(0);
  const [rotatorSize, setRotatorSize] = useState(0);
  const [followMode, setFollowMode] = useState(true);
  const mapAreaRef = useRef<HTMLDivElement | null>(null);
  const [positionStatus, setPositionStatus] = useState<"waiting" | "active" | "denied" | "unsupported">(
    typeof navigator !== "undefined" && navigator.geolocation ? "waiting" : "unsupported",
  );
  const [stepIndex, setStepIndex] = useState(() => loadNavigationSession()?.stepIndex ?? 0);
  const [muted, setMuted] = useState(false);
  const [stepsExpanded, setStepsExpanded] = useState(false);
  const [connectivityMessage, setConnectivityMessage] = useState<string | null>(null);
  const [hazardBanner, setHazardBanner] = useState<string | null>(null);
  const [forumBanner, setForumBanner] = useState<string | null>(null);
  const [arrived, setArrived] = useState(false);
  const [nearbyHazards, setNearbyHazards] = useState<PostSummary[]>([]);

  const offRouteDetectorRef = useRef(
    createOffRouteDetector({
      thresholdMeters: OFF_ROUTE_THRESHOLD_METERS,
      requiredConsecutiveTicks: OFF_ROUTE_CONSECUTIVE_TICKS,
    }),
  );
  const rerouteThrottleRef = useRef(createIntervalThrottle(REROUTE_MIN_INTERVAL_MS));
  const hazardSeenRef = useRef(createSeenIdTracker());
  const rerouteInFlightRef = useRef(false);
  const announcedRef = useRef<Set<string>>(new Set());
  const headingAnchorRef = useRef<LatLng | null>(null);
  const candidateRef = useRef(candidate);
  const stepIndexRef = useRef(stepIndex);
  const mutedRef = useRef(muted);
  const nearbyHazardsRef = useRef(nearbyHazards);
  candidateRef.current = candidate;
  stepIndexRef.current = stepIndex;
  mutedRef.current = muted;
  nearbyHazardsRef.current = nearbyHazards;

  // Keeps sessionStorage in sync with live route progress so a refresh/crash mid-drive
  // resumes here instead of forcing the driver back to route planning. Deliberately
  // excludes `position` — re-acquiring a fresh GPS fix on resume is correct; only the
  // route itself (post-reroute) and how far along it the driver got need to survive.
  useEffect(() => {
    saveNavigationSession({ handoff, candidate, stepIndex });
  }, [handoff, candidate, stepIndex]);

  // Screen-on: best-effort, feature-detected. Released automatically by the browser on
  // tab-hide, so it is re-requested on visibility change rather than only once at mount.
  useEffect(() => {
    const wakeLock = getWakeLock();
    if (!wakeLock) return;
    const lock = wakeLock;
    let sentinel: WakeLockSentinelLike | null = null;
    async function acquire() {
      try {
        sentinel = await lock.request("screen");
      } catch {
        // Denied or unsupported in this context; navigation still works without it.
      }
    }
    void acquire();
    function onVisibilityChange() {
      if (document.visibilityState === "visible") void acquire();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      void sentinel?.release();
    };
  }, []);

  // Greet once at start and read out the first step immediately, rather than waiting for
  // the driver to get within the normal 300m/100m announcement distance of it.
  useEffect(() => {
    const firstStep = handoff.candidate.steps[0];
    if (!mutedRef.current) {
      speak(
        firstStep
          ? `Ready? Let's go. ${formatManeuverText(firstStep, firstStep.distance)}`
          : "Ready? Let's go.",
      );
    }
    if (firstStep) announcedRef.current.add(`0:${ANNOUNCE_DISTANCES_METERS[0]}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The rotated map layer must fully cover the visible area at *any* rotation angle, not
  // just be "bigger" — for a wide (non-square) viewport, a fixed percentage oversize covers
  // some angles but not others (this is what caused visible gaps at the sides). The only
  // size that's safe at every angle is the viewport's own diagonal, which requires the
  // actual pixel dimensions — hence measuring via ResizeObserver instead of a CSS percentage.
  useEffect(() => {
    const element = mapAreaRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setRotatorSize(Math.ceil(Math.sqrt(width * width + height * height)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Forum notifications: reuses the same SSE stream as the notification indicator, so a
  // dropped connection just pauses alerts — core navigation never depends on it.
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(NOTIFICATIONS_STREAM_URL, { withCredentials: true });
    source.onmessage = () => {
      setForumBanner("New forum notification");
      if (!mutedRef.current) speak("You have a new forum notification.");
    };
    return () => source.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Nearby hazard reports: fetched around the route, refreshed periodically. Never
  // stores or sends the driver's live position to the server for this.
  useEffect(() => {
    let cancelled = false;
    async function loadNearby() {
      try {
        const page = await listNearbyPosts(bboxAround(candidateRef.current));
        if (!cancelled) setNearbyHazards(page.items);
      } catch {
        // Best-effort; the next interval tick retries. Navigation is unaffected.
      }
    }
    void loadNearby();
    const interval = window.setInterval(() => void loadNearby(), HAZARD_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) return;

    async function handlePosition(next: LatLng) {
      setPosition(next);
      setPositionStatus("active");

      const previousForHeading = headingAnchorRef.current;
      if (
        previousForHeading &&
        haversineMeters(previousForHeading, next) >= MIN_MOVEMENT_FOR_HEADING_METERS
      ) {
        setHeading(bearingDegrees(previousForHeading, next));
        headingAnchorRef.current = next;
      } else if (!previousForHeading) {
        headingAnchorRef.current = next;
      }

      const activeCandidate = candidateRef.current;
      const path = toLatLngPath(activeCandidate);

      const destination: LatLng = { lat: handoff.destinationLatitude, lon: handoff.destinationLongitude };
      if (haversineMeters(next, destination) <= ARRIVAL_THRESHOLD_METERS) {
        setArrived(true);
        window.setTimeout(onExit, 3000);
        return;
      }

      for (const hazard of nearbyHazardsRef.current) {
        if (hazard.longitude === null || hazard.latitude === null) continue;
        const distance = haversineMeters(next, { lat: hazard.latitude, lon: hazard.longitude });
        if (distance <= HAZARD_ALERT_RADIUS_METERS && hazardSeenRef.current(hazard.id)) {
          const message = `${hazard.hazard_type.replace(/_/g, " ")} reported ahead`;
          setHazardBanner(message);
          if (!mutedRef.current) speak(message);
        }
      }

      const steps = activeCandidate.steps;
      let activeStepIndex = stepIndexRef.current;
      while (
        activeStepIndex < steps.length - 1 &&
        steps[activeStepIndex].maneuver.location &&
        haversineMeters(next, {
          lon: steps[activeStepIndex].maneuver.location![0],
          lat: steps[activeStepIndex].maneuver.location![1],
        }) <= MANEUVER_ADVANCE_METERS
      ) {
        activeStepIndex += 1;
      }
      if (activeStepIndex !== stepIndexRef.current) {
        stepIndexRef.current = activeStepIndex;
        setStepIndex(activeStepIndex);
        announcedRef.current.clear();
      }
      const currentStep = steps[activeStepIndex];
      if (currentStep?.maneuver.location) {
        const distanceToManeuver = haversineMeters(next, {
          lon: currentStep.maneuver.location[0],
          lat: currentStep.maneuver.location[1],
        });
        for (const bucket of ANNOUNCE_DISTANCES_METERS) {
          const key = `${activeStepIndex}:${bucket}`;
          if (distanceToManeuver <= bucket && !announcedRef.current.has(key)) {
            announcedRef.current.add(key);
            if (!mutedRef.current) speak(formatManeuverText(currentStep, distanceToManeuver));
          }
        }
      }

      const offRoute = offRouteDetectorRef.current.check(distanceToPolylineMeters(next, path));
      if (offRoute && !rerouteInFlightRef.current && rerouteThrottleRef.current(Date.now())) {
        rerouteInFlightRef.current = true;
        try {
          const result = await reroute({
            current_longitude: next.lon,
            current_latitude: next.lat,
            destination_longitude: handoff.destinationLongitude,
            destination_latitude: handoff.destinationLatitude,
            scoring_context: handoff.scoringContext,
          });
          const chosen =
            result.candidates.find((item) => item.candidate_index === result.chosen_index) ??
            result.candidates[0];
          setCandidate(chosen);
          setStepIndex(0);
          stepIndexRef.current = 0;
          announcedRef.current.clear();
          offRouteDetectorRef.current.reset();
          setConnectivityMessage(null);
        } catch (error) {
          setConnectivityMessage(
            error instanceof RerouteError
              ? error.message
              : "Couldn't recalculate — continuing on the current route.",
          );
        } finally {
          rerouteInFlightRef.current = false;
        }
      }
    }

    const watchId = navigator.geolocation.watchPosition(
      (geolocationPosition) =>
        void handlePosition({
          lat: geolocationPosition.coords.latitude,
          lon: geolocationPosition.coords.longitude,
        }),
      (error) => {
        setPositionStatus(error.code === error.PERMISSION_DENIED ? "denied" : "waiting");
      },
      { enableHighAccuracy: true },
    );
    return () => navigator.geolocation.clearWatch(watchId);
    // handoff is stable for the lifetime of one navigation session; live-updating values
    // (candidate, step index, mute, nearby hazards) are read via refs above so this
    // effect subscribes to geolocation exactly once instead of re-subscribing on every
    // reroute, mute toggle, or hazard refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoff, onExit]);

  const path = toLatLngPath(candidate);
  const currentStep = candidate.steps[stepIndex] ?? null;
  const upcomingSteps = candidate.steps.slice(stepIndex + 1);
  const mapCenter: [number, number] = position
    ? [position.lat, position.lon]
    : path.length > 0
      ? [path[0].lat, path[0].lon]
      : [31.7, 34.9];

  const averageSpeedMetersPerSecond = candidate.distance_m / candidate.duration_seconds;
  const remainingSeconds = position
    ? remainingRouteDistanceMeters(position, path) / averageSpeedMetersPerSecond
    : candidate.duration_seconds;
  const etaText = new Date(Date.now() + remainingSeconds * 1000).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  const remainingMinutesText = `${Math.max(1, Math.round(remainingSeconds / 60))} min`;

  return (
    <div className="nav-page" data-nav-status={positionStatus}>
      <div className="nav-page__banners">
        {positionStatus === "denied" ? (
          <p className="nav-page__banner" role="alert">
            Location access was denied. Enable location permissions to continue navigation.
          </p>
        ) : null}
        {positionStatus === "unsupported" ? (
          <p className="nav-page__banner" role="alert">
            This browser does not support live location.
          </p>
        ) : null}
        {connectivityMessage ? (
          <p className="nav-page__banner" role="status">{connectivityMessage}</p>
        ) : null}
        {hazardBanner ? (
          <p className="nav-page__banner nav-page__banner--hazard" role="alert">{hazardBanner}</p>
        ) : null}
        {forumBanner ? <p className="nav-page__banner" role="status">{forumBanner}</p> : null}
      </div>
      <div className="nav-page__map" aria-label="Live navigation map" ref={mapAreaRef}>
        <div
          className="nav-page__map-rotator"
          style={{
            width: rotatorSize || "200%",
            height: rotatorSize || "200%",
            transform: `translate(-50%, -50%) rotate(${followMode ? -heading : 0}deg)`,
          }}
        >
          <MapContainer
            center={mapCenter}
            zoom={NAV_ZOOM_LEVEL}
            className="corridor-map"
            dragging
            scrollWheelZoom
            doubleClickZoom
            touchZoom
            boxZoom
            keyboard
          >
            <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <Polyline positions={path.map((point) => [point.lat, point.lon] as [number, number])} pathOptions={{ color: "#0d7288", weight: 7 }} />
            <FollowPosition position={position} enabled={followMode} />
            <FreeLookOnInteraction onInteraction={() => setFollowMode(false)} />
            <InvalidateSizeOnResize watch={rotatorSize} />
          </MapContainer>
        </div>
        {/* Fixed over the map, never rotates: while following, the map turns beneath it so
            the driver's current heading always points up. Hidden during free-look, since
            the map is no longer centered on the driver's position at that point. */}
        {position && followMode ? <div className="nav-page__center-arrow" aria-hidden="true" /> : null}
        {!followMode ? (
          <button
            type="button"
            className="nav-page__recenter"
            onClick={() => setFollowMode(true)}
            aria-label="Recenter on my location"
          >
            My location
          </button>
        ) : null}
      </div>
      <div className="nav-page__bottom-bar">
        {stepsExpanded && upcomingSteps.length > 0 ? (
          <div className="nav-page__steps-panel">
            <ul className="nav-page__steps-list">
              {upcomingSteps.map((step, index) => (
                <li key={`${step.name}-${step.maneuver.type}-${index}`} className="nav-page__steps-item">
                  {formatManeuverText(step, step.distance)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <button
          type="button"
          className="ghost-button nav-page__mute-button"
          onClick={() => setMuted((value) => !value)}
        >
          {muted ? "Unmute" : "Mute"}
        </button>
        <p className="nav-page__instruction-text">
          {arrived
            ? "Arrived at your destination"
            : currentStep
              ? formatManeuverText(
                  currentStep,
                  position && currentStep.maneuver.location
                    ? haversineMeters(position, { lon: currentStep.maneuver.location[0], lat: currentStep.maneuver.location[1] })
                    : currentStep.distance,
                )
              : "Continue on the current route"}
        </p>
        {!arrived ? (
          <p className="nav-page__eta">
            Estimated time of arrival {etaText} · {remainingMinutesText}
          </p>
        ) : null}
        {!arrived && upcomingSteps.length > 0 ? (
          <button
            type="button"
            className="nav-page__steps-toggle"
            onClick={() => setStepsExpanded((value) => !value)}
            aria-expanded={stepsExpanded}
          >
            {stepsExpanded ? "Hide" : "Show"} upcoming steps ({upcomingSteps.length})
          </button>
        ) : null}
      </div>
      <div className="nav-page__controls">
        <button type="button" className="ghost-button" onClick={onExit}>
          End navigation
        </button>
      </div>
    </div>
  );
}
