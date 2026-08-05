export type HazardType =
  | "pothole"
  | "flooding"
  | "broken_signal"
  | "poor_lighting"
  | "illegal_speed_bump"
  | "crash"
  | "other";

export type VoteValue = "up" | "down" | "none";

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
}

export interface PostDetail extends PostSummary {
  body: string;
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

