import type { NavigationHandoff } from "../types/navigation";
import type { RouteCandidateResult } from "../types/routeJobs";

const STORAGE_KEY = "live-navigation-session";

export interface PersistedNavigationSession {
  handoff: NavigationHandoff;
  candidate: RouteCandidateResult;
  stepIndex: number;
}

export function saveNavigationSession(session: PersistedNavigationSession): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Best-effort; storage may be full or unavailable (e.g. private browsing).
  }
}

export function loadNavigationSession(): PersistedNavigationSession | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedNavigationSession) : null;
  } catch {
    return null;
  }
}

export function clearNavigationSession(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Best-effort.
  }
}
