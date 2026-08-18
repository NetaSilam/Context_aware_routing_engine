export type DrivingExperience = "novice" | "experienced";
export type VehicleType = "car" | "motorcycle" | "truck";
export type SafetyPreference = "low" | "balanced" | "high";

export interface UserProfile {
  id: number;
  email: string;
  driving_experience: DrivingExperience;
  vehicle_type: VehicleType;
  avoid_tolls: boolean;
  avoid_highways: boolean;
  safety_preference: SafetyPreference;
}

export interface SignupInput {
  email: string;
  password: string;
  driving_experience: DrivingExperience;
  vehicle_type: VehicleType;
  avoid_tolls: boolean;
  avoid_highways: boolean;
  safety_preference: SafetyPreference;
}

export interface LoginInput {
  email: string;
  password: string;
}

export type PreferenceUpdate = Pick<
  UserProfile,
  "driving_experience" | "vehicle_type" | "avoid_tolls" | "avoid_highways" | "safety_preference"
>;

export const SAFETY_PREFERENCE_LABELS: Record<SafetyPreference, string> = {
  low: "Low — I mostly care about time",
  balanced: "Balanced",
  high: "High — safety matters most to me",
};
