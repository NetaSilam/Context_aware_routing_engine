import type {
  LoginInput,
  PreferenceUpdate,
  SignupInput,
  UserProfile,
} from "../types/auth";

async function parseJsonOrThrow(response: Response): Promise<unknown> {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? String(body.detail) : null;
    throw new Error(detail ?? `Request failed with status ${response.status}.`);
  }
  return body;
}

async function sessionRequest(path: string, init?: RequestInit): Promise<Response> {
  return fetch(path, { ...init, credentials: "include" });
}

export async function signup(input: SignupInput): Promise<UserProfile> {
  const response = await sessionRequest("/api/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return (await parseJsonOrThrow(response)) as UserProfile;
}

export async function login(input: LoginInput): Promise<UserProfile> {
  const response = await sessionRequest("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return (await parseJsonOrThrow(response)) as UserProfile;
}

export async function getMe(): Promise<UserProfile> {
  const response = await sessionRequest("/api/auth/me");
  return (await parseJsonOrThrow(response)) as UserProfile;
}

export async function updatePreferences(input: PreferenceUpdate): Promise<UserProfile> {
  const response = await sessionRequest("/api/auth/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return (await parseJsonOrThrow(response)) as UserProfile;
}

export async function logout(): Promise<void> {
  const response = await sessionRequest("/api/auth/logout", { method: "POST" });
  if (!response.ok) {
    await parseJsonOrThrow(response);
  }
}
