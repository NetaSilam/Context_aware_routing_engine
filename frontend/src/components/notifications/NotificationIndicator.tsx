import { useEffect, useState } from "react";

import {
  NOTIFICATIONS_STREAM_URL,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "../../api/notifications";
import type { NotificationItem } from "../../types/notifications";

function describeNotification(item: NotificationItem): string {
  const payload = item.payload;
  switch (item.kind) {
    case "new_dm":
      return `New message from ${String(payload.sender_email ?? "a user")}`;
    case "new_comment":
      return payload.actor_label
        ? `${String(payload.actor_label)} commented on your report`
        : "Someone commented on your report";
    case "new_vote": {
      const target = payload.target_type === "comment" ? "comment" : "report";
      const direction =
        payload.value === "up" ? "upvoted" : payload.value === "down" ? "downvoted" : "voted on";
      return `Someone ${direction} your ${target}`;
    }
    default:
      return "New notification";
  }
}

export default function NotificationIndicator(): JSX.Element {
  const [unreadCount, setUnreadCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const source = new EventSource(NOTIFICATIONS_STREAM_URL, { withCredentials: true });

    async function refetchUnreadCount() {
      try {
        const page = await listNotifications(0, 1);
        setUnreadCount(page.unread_count);
      } catch {
        // Leave the last known count; the next successful (re)connect corrects it.
      }
    }

    // A dropped connection reconnects on its own (native EventSource retry), firing
    // onopen again on this same instance — refetch every time so a count that changed
    // while disconnected is never silently missed.
    source.onopen = () => void refetchUnreadCount();
    source.onmessage = () => setUnreadCount((count) => count + 1);

    return () => source.close();
  }, []);

  async function togglePanel() {
    const next = !open;
    setOpen(next);
    if (!next) return;
    setLoading(true);
    try {
      const page = await listNotifications(0, 10);
      setItems(page.items);
    } catch {
      // Leave the panel open empty; the badge count on the toggle still reflects reality.
    } finally {
      setLoading(false);
    }
  }

  async function handleMarkAllRead() {
    setUnreadCount(0);
    const now = new Date().toISOString();
    setItems((current) => current.map((item) => ({ ...item, read_at: item.read_at ?? now })));
    try {
      await markAllNotificationsRead();
    } catch {
      // Best-effort: the next reconnect's refetch reconciles the count if this failed.
    }
  }

  async function handleItemClick(item: NotificationItem) {
    if (item.read_at) return;
    const now = new Date().toISOString();
    setItems((current) =>
      current.map((existing) => (existing.id === item.id ? { ...existing, read_at: now } : existing)),
    );
    setUnreadCount((count) => Math.max(0, count - 1));
    try {
      await markNotificationRead(item.id);
    } catch {
      // Best-effort; a stale read state self-corrects the next time the panel is opened.
    }
  }

  return (
    <div className="notification-indicator">
      <button
        type="button"
        className="ghost-button notification-indicator__toggle"
        aria-label="Notifications"
        aria-expanded={open}
        onClick={() => void togglePanel()}
      >
        Notifications
        {unreadCount > 0 ? <span className="notification-indicator__badge">{unreadCount}</span> : null}
      </button>
      {open ? (
        <div className="notification-panel" role="region" aria-label="Recent notifications">
          <div className="notification-panel__header">
            <p className="notification-panel__title">Notifications</p>
            <button
              type="button"
              className="ghost-button"
              onClick={() => void handleMarkAllRead()}
              disabled={unreadCount === 0}
            >
              Mark all as read
            </button>
          </div>
          {loading ? <p className="notification-panel__empty">Loading…</p> : null}
          {!loading && items.length === 0 ? (
            <p className="notification-panel__empty">No notifications yet.</p>
          ) : null}
          <ul className="notification-panel__list">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={
                    item.read_at
                      ? "notification-panel__item"
                      : "notification-panel__item notification-panel__item--unread"
                  }
                  onClick={() => void handleItemClick(item)}
                >
                  <span>{describeNotification(item)}</span>
                  <span className="notification-panel__time">
                    {new Date(item.created_at).toLocaleString()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
