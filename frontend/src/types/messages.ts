import type { MediaItem } from "./forum";

export interface MessageItem {
  id: string;
  sender_user_id: number;
  sender_email: string;
  recipient_user_id: number;
  recipient_email: string;
  body: string | null;
  media: MediaItem | null;
  created_at: string;
  read_at: string | null;
}

export interface MessagePage {
  items: MessageItem[];
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface ConversationSummary {
  other_user_id: number;
  other_user_email: string;
  last_message_body: string | null;
  last_message_at: string;
  unread_count: number;
}

export interface ConversationPage {
  items: ConversationSummary[];
  offset: number;
  limit: number;
  has_more: boolean;
}
