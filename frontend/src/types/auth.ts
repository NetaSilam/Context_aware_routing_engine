export type DrivingExperience = "novice" | "experienced";
export type VehicleType = "car" | "motorcycle" | "truck";

export interface UserProfile {
  id: number;
  email: string;
  driving_experience: DrivingExperience;
  vehicle_type: VehicleType;
  avoid_tolls: boolean;
  avoid_highways: boolean;
}

export interface SignupInput {
  email: string;
  password: string;
  driving_experience: DrivingExperience;
  vehicle_type: VehicleType;
  avoid_tolls: boolean;
  avoid_highways: boolean;
}

export interface LoginInput {
  email: string;
  password: string;
}
