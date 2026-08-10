import { useEffect, useState } from "react";

import {
  NOTIFICATIONS_STREAM_URL,
  listNotifications,
  markAllNotificationsRead,
} from "../../api/notifications";

export default function NotificationIndicator(): JSX.Element {
  const [unreadCount, setUnreadCount] = useState(0);

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

  async function handleClick() {
    setUnreadCount(0);
    try {
      await markAllNotificationsRead();
    } catch {
      // Best-effort: the next reconnect's refetch reconciles the count if this failed.
    }
  }

  return (
    <button
      type="button"
      className="ghost-button notification-indicator"
      aria-label="Notifications"
      onClick={() => void handleClick()}
    >
      Notifications
      {unreadCount > 0 ? (
        <span className="notification-indicator__badge">{unreadCount}</span>
      ) : null}
    </button>
  );
}
