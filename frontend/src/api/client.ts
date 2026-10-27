import type { Chat, ChatWithMessages, DocumentInfo, Health, Job, SettingItem, StreamEvent, UploadResult, User } from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** The backend's `detail` message when it sent one, else the HTTP status text. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
  } catch { /* not JSON */ }
  return res.statusText;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  listChats: () => request<Chat[]>("/chats"),
  getChat: (id: string) => request<ChatWithMessages>(`/chats/${id}`),
  createChat: () => request<Chat>("/chats", { method: "POST", body: "{}" }),
  renameChat: (id: string, title: string) =>
    request<{ id: string; title: string }>(`/chats/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteChat: (id: string) => request<void>(`/chats/${id}`, { method: "DELETE" }),

  me: () => request<{ user: User | null }>("/auth/me").then((r) => r.user),
  login: (username: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  register: (username: string, password: string) =>
    request<User>("/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),

  listDocuments: () => request<{ documents: DocumentInfo[]; jobs: Job[] }>("/admin/documents"),
  /** Sends the raw file as the body; the server starts indexing it right away. */
  uploadDocument: (file: File) =>
    request<UploadResult>(`/admin/documents/${encodeURIComponent(file.name)}`, {
      method: "PUT",
      body: file,
      headers: { "Content-Type": "application/octet-stream" },
    }),
  deleteDocument: (name: string) => request<void>(`/admin/documents/${encodeURIComponent(name)}`, { method: "DELETE" }),
  trainDocument: (name: string) => request<Job>(`/admin/documents/${encodeURIComponent(name)}/train`, { method: "POST" }),
  getSettings: () => request<{ settings: SettingItem[] }>("/admin/settings").then((r) => r.settings),
  saveSettings: (values: Record<string, number | string | boolean>) =>
    request<{ settings: SettingItem[] }>("/admin/settings", { method: "PUT", body: JSON.stringify({ values }) }).then((r) => r.settings),
  resetSettings: (keys?: string[]) =>
    request<{ settings: SettingItem[] }>("/admin/settings/reset", { method: "POST", body: JSON.stringify({ keys: keys ?? null }) }).then((r) => r.settings),
  reindexAll: () => request<Job>("/admin/reindex", { method: "POST" }),
};

/** Parse one SSE frame ("event: x\ndata: {...}") into a typed event. */
function parseFrame(raw: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  return { event, data: JSON.parse(data.join("\n")) } as StreamEvent;
}

/**
 * POST a question and yield the streamed answer events as they arrive.
 * fetch + ReadableStream (not EventSource) because EventSource cannot POST.
 * Aborting `signal` stops the stream; the server keeps what was generated so far.
 */
export async function* streamAnswer(
  chatId: string,
  content: string,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/chats/${chatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, res.statusText);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const frame = parseFrame(buffer.slice(0, idx));
        buffer = buffer.slice(idx + 2);
        if (frame) yield frame;
      }
    }
  } finally {
    reader.cancel().catch(() => undefined);
  }
}
