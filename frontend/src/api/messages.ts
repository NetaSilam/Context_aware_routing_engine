import type { ConversationPage, MessageItem, MessagePage } from "../types/messages";

async function parseError(response: Response): Promise<string> {
  const body = (await response.json().catch(() => ({}))) as { detail?: string };
  return body.detail ?? `Messaging request failed (${response.status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: "include" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json() as Promise<T>;
}

export async function listConversations(offset = 0, limit = 20): Promise<ConversationPage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return request<ConversationPage>(`/api/messages?${params.toString()}`);
}

export async function getConversation(
  otherUserId: number,
  offset = 0,
  limit = 30,
): Promise<MessagePage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return request<MessagePage>(`/api/messages/${otherUserId}?${params.toString()}`);
}

export async function sendMessage(
  recipientId: number,
  body: string | null,
  file: File | null,
): Promise<MessageItem> {
  const formData = new FormData();
  if (body) formData.append("body", body);
  if (file) formData.append("file", file);
  const response = await fetch(`/api/messages/${recipientId}`, {
    method: "POST",
    credentials: "include",
    headers: { Origin: window.location.origin },
    body: formData,
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json() as Promise<MessageItem>;
}
