import type {
  CommentItem,
  CommentPage,
  DashboardSummary,
  HazardType,
  PostDetail,
  PostPage,
  VoteValue,
} from "../types/forum";

export interface CreatePostRequest {
  title: string;
  body: string;
  hazard_type: HazardType;
  is_anonymous: boolean;
  longitude?: number;
  latitude?: number;
}

export interface UpdatePostRequest {
  title?: string;
  body?: string;
  hazard_type?: HazardType;
}

export interface CreateCommentRequest {
  body: string;
  is_anonymous: boolean;
}

async function parseError(response: Response): Promise<string> {
  const body = (await response.json().catch(() => ({}))) as { detail?: string };
  return body.detail ?? `Forum request failed (${response.status}).`;
}

function mutationHeaders(extra?: Record<string, string>): Record<string, string> {
  return { "Content-Type": "application/json", Origin: window.location.origin, ...extra };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: "include" });
  if (!response.ok) throw new Error(await parseError(response));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function listPosts(
  offset = 0,
  limit = 20,
  hazardType?: HazardType,
): Promise<PostPage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (hazardType) params.set("hazard_type", hazardType);
  return request<PostPage>(`/api/forum/posts?${params.toString()}`);
}

export async function getPost(postId: string): Promise<PostDetail> {
  return request<PostDetail>(`/api/forum/posts/${encodeURIComponent(postId)}`);
}

export async function createPost(payload: CreatePostRequest): Promise<PostDetail> {
  return request<PostDetail>("/api/forum/posts", {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function updatePost(postId: string, payload: UpdatePostRequest): Promise<PostDetail> {
  return request<PostDetail>(`/api/forum/posts/${encodeURIComponent(postId)}`, {
    method: "PATCH",
    headers: mutationHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function deletePost(postId: string): Promise<void> {
  await request<void>(`/api/forum/posts/${encodeURIComponent(postId)}`, {
    method: "DELETE",
    headers: mutationHeaders(),
  });
}

export async function listComments(postId: string, offset = 0, limit = 30): Promise<CommentPage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return request<CommentPage>(
    `/api/forum/posts/${encodeURIComponent(postId)}/comments?${params.toString()}`,
  );
}

export async function createComment(
  postId: string,
  payload: CreateCommentRequest,
): Promise<CommentItem> {
  return request<CommentItem>(`/api/forum/posts/${encodeURIComponent(postId)}/comments`, {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function updateComment(commentId: string, body: string): Promise<CommentItem> {
  return request<CommentItem>(`/api/forum/comments/${encodeURIComponent(commentId)}`, {
    method: "PATCH",
    headers: mutationHeaders(),
    body: JSON.stringify({ body }),
  });
}

export async function deleteComment(commentId: string): Promise<void> {
  await request<void>(`/api/forum/comments/${encodeURIComponent(commentId)}`, {
    method: "DELETE",
    headers: mutationHeaders(),
  });
}

export async function voteOnPost(postId: string, value: VoteValue): Promise<void> {
  await request<void>(`/api/forum/posts/${encodeURIComponent(postId)}/vote`, {
    method: "PUT",
    headers: mutationHeaders(),
    body: JSON.stringify({ value }),
  });
}

export async function voteOnComment(commentId: string, value: VoteValue): Promise<void> {
  await request<void>(`/api/forum/comments/${encodeURIComponent(commentId)}/vote`, {
    method: "PUT",
    headers: mutationHeaders(),
    body: JSON.stringify({ value }),
  });
}

export async function getMyForumDashboard(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/api/forum/me/dashboard");
}
