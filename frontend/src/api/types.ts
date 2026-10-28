export interface Chat {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

/** One numbered passage the model read. Older saved chats only have source, score and snippet. */
export interface Source {
  n?: number;
  id?: string;
  source: string;
  section?: string;
  role?: "match" | "context" | "related";
  page?: number | null;
  page_end?: number | null;
  score: number | null;
  snippet: string;
  text?: string;
}

/** Result of the check that an answer's figures and names appear in its sources. */
export interface Grounding {
  ok: boolean;
  unsupported: string[];
  /** Numbers of the passages the answer actually draws on. */
  used: number[];
}

export interface StoredMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  checks?: Grounding | null;
  created_at: string;
}

export interface ChatWithMessages extends Chat {
  messages: StoredMessage[];
}

export interface Health {
  status: string;
  model: string;
  embed_model: string;
}

/** Events the backend streams over SSE for one answer. */
export type StreamEvent =
  | { event: "meta"; data: { title: string } }
  | { event: "sources"; data: { sources: Source[] } }
  | { event: "token"; data: { text: string } }
  | { event: "grounding"; data: Grounding }
  | { event: "error"; data: { message: string } }
  | { event: "done"; data: Record<string, never> };

export interface User {
  id: number;
  username: string;
  is_admin: boolean;
}

export interface DocumentInfo {
  name: string;
  size: number;
  chunks: number;
  pages: number;
  status: "indexed" | "indexing" | "not indexed" | "outdated";
  modified: string;
}

export interface Job {
  id: string;
  kind: "index" | "reindex";
  target: string;
  state: "queued" | "running" | "done" | "error";
  message: string;
  done: number;
  total: number;
  created_at: string;
  finished_at?: string;
}

export interface SettingItem {
  key: string;
  label: string;
  help: string;
  kind: "float" | "int" | "bool" | "model";
  value: number | string | boolean;
  default: number | string | boolean;
  changed: boolean;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
}

export interface UploadResult {
  name: string;
  status: "new" | "replaced" | "unchanged";
  job: Job | null;
}
