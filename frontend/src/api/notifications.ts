import type { NotificationPage } from "../types/notifications";

async function parseError(response: Response): Promise<string> {
  const body = (await response.json().catch(() => ({}))) as { detail?: string };
  return body.detail ?? `Notifications request failed (${response.status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: "include" });
  if (!response.ok) throw new Error(await parseError(response));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function mutationHeaders(): Record<string, string> {
  return { Origin: window.location.origin };
}

export async function listNotifications(offset = 0, limit = 30): Promise<NotificationPage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return request<NotificationPage>(`/api/notifications?${params.toString()}`);
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await request<void>(`/api/notifications/${encodeURIComponent(notificationId)}/read`, {
    method: "POST",
    headers: mutationHeaders(),
  });
}

export async function markAllNotificationsRead(): Promise<void> {
  await request<void>("/api/notifications/read-all", {
    method: "POST",
    headers: mutationHeaders(),
  });
}

export const NOTIFICATIONS_STREAM_URL = "/api/notifications/stream";
