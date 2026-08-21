export type HazardType =
  | "pothole"
  | "flooding"
  | "broken_signal"
  | "poor_lighting"
  | "illegal_speed_bump"
  | "crash"
  | "other";

export type VoteValue = "up" | "down" | "none";

export type Severity = "low" | "medium" | "high";

export type MediaType = "image" | "video";

export interface MediaItem {
  id: string;
  media_type: MediaType;
  content_type: string;
  byte_size: number;
}

export interface PostSummary {
  id: string;
  title: string;
  hazard_type: HazardType;
  longitude: number | null;
  latitude: number | null;
  author_id: number | null;
  author_email: string | null;
  is_anonymous: boolean;
  is_own: boolean;
  upvote_count: number;
  downvote_count: number;
  comment_count: number;
  my_vote: VoteValue;
  created_at: string;
  updated_at: string;
  llm_hazard_type_suggested: HazardType | null;
  llm_severity: Severity | null;
  duplicate_of_post_id: string | null;
  duplicate_of_post_title: string | null;
  thumbnail_media_id: string | null;
}

export interface PostDetail extends PostSummary {
  body: string;
  media: MediaItem[];
}

export interface CommentItem {
  id: string;
  post_id: string;
  body: string;
  author_id: number | null;
  author_email: string | null;
  is_anonymous: boolean;
  is_own: boolean;
  upvote_count: number;
  downvote_count: number;
  my_vote: VoteValue;
  media: MediaItem[];
  created_at: string;
  updated_at: string;
}

export interface PostPage {
  items: PostSummary[];
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface CommentPage {
  items: CommentItem[];
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface DashboardSummary {
  post_count: number;
  comment_count: number;
  total_upvotes_received: number;
  total_downvotes_received: number;
  net_votes_received: number;
}

export const HAZARD_TYPE_LABELS: Record<HazardType, string> = {
  pothole: "Pothole",
  flooding: "Flooding",
  broken_signal: "Broken traffic signal",
  poor_lighting: "Poor lighting",
  illegal_speed_bump: "Illegal speed bump",
  crash: "Recent crash",
  other: "Other hazard",
};

export const HAZARD_TYPES = Object.keys(HAZARD_TYPE_LABELS) as HazardType[];

export const SEVERITY_LABELS: Record<Severity, string> = {
  low: "Low severity",
  medium: "Medium severity",
  high: "High severity",
};

