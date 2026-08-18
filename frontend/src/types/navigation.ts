import type { RerouteScoringContext, RouteCandidateResult } from "./routeJobs";

export interface NavigationHandoff {
  candidate: RouteCandidateResult;
  destinationLongitude: number;
  destinationLatitude: number;
  scoringContext: RerouteScoringContext;
}
