import type { LoginInput, SignupInput, UserProfile } from "../types/auth";

const TOKEN_STORAGE_KEY = "routing_engine_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

async function parseJsonOrThrow(response: Response): Promise<unknown> {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? String(body.detail) : null;
    throw new Error(detail ?? `Request failed with status ${response.status}.`);
  }
  return body;
}

export async function signup(input: SignupInput): Promise<string> {
  const response = await fetch("/api/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = (await parseJsonOrThrow(response)) as { access_token: string };
  return body.access_token;
}

export async function login(input: LoginInput): Promise<string> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = (await parseJsonOrThrow(response)) as { access_token: string };
  return body.access_token;
}

export async function getMe(token: string): Promise<UserProfile> {
  const response = await fetch("/api/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return (await parseJsonOrThrow(response)) as UserProfile;
}
