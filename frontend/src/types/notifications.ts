export type NotificationKind = "new_dm" | "new_vote" | "new_comment";

export interface NotificationItem {
  id: string;
  kind: NotificationKind;
  payload: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
}

export interface NotificationPage {
  items: NotificationItem[];
  offset: number;
  limit: number;
  has_more: boolean;
  unread_count: number;
}
