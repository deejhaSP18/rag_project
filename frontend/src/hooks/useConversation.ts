import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamAnswer } from "../api/client";
import type { Grounding, Source } from "../api/types";

export interface UiMessage {
  key: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  checks?: Grounding | null;
  status: "streaming" | "done" | "stopped" | "error";
  error?: string;
}

interface Options {
  /** Returns the id of the chat to send to, creating one if none is open yet. */
  ensureChat: () => Promise<string>;
  onTitle: (chatId: string, title: string) => void;
  onActivity: (chatId: string) => void;
}

let keyCounter = 0;
const nextKey = () => `m${++keyCounter}`;

/** Messages of the open chat plus the streaming lifecycle of the current answer. */
export function useConversation({ ensureChat, onTitle, onActivity }: Options) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);

  // Keep the latest callbacks without re-creating `send`.
  const cb = useRef({ ensureChat, onTitle, onActivity });
  cb.current = { ensureChat, onTitle, onActivity };

  const stop = useCallback(() => controller.current?.abort(), []);
  useEffect(() => () => controller.current?.abort(), []);

  const load = useCallback(async (chatId: string) => {
    controller.current?.abort();
    const chat = await api.getChat(chatId);
    setMessages(
      chat.messages.map((m) => ({
        key: `s${m.id}`, role: m.role, content: m.content, sources: m.sources, checks: m.checks, status: "done" as const,
      })),
    );
  }, []);

  const reset = useCallback(() => {
    controller.current?.abort();
    setMessages([]);
  }, []);

  const send = useCallback(async (question: string) => {
    const text = question.trim();
    if (!text || controller.current) return;

    let chatId: string;
    try {
      chatId = await cb.current.ensureChat();
    } catch {
      setMessages((m) => [...m, { key: nextKey(), role: "assistant", content: "", sources: [], status: "error", error: "Can't reach the server." }]);
      return;
    }

    const replyKey = nextKey();
    setMessages((m) => [
      ...m,
      { key: nextKey(), role: "user", content: text, sources: [], status: "done" },
      { key: replyKey, role: "assistant", content: "", sources: [], status: "streaming" },
    ]);
    const update = (changes: Partial<UiMessage>) =>
      setMessages((m) => m.map((x) => (x.key === replyKey ? { ...x, ...changes } : x)));

    const ctrl = new AbortController();
    controller.current = ctrl;
    setBusy(true);

    // Batch token updates to one render per animation frame.
    let answer = "";
    let frame = 0;
    const flush = () => { frame = 0; update({ content: answer }); };

    try {
      for await (const ev of streamAnswer(chatId, text, ctrl.signal)) {
        if (ev.event === "meta") cb.current.onTitle(chatId, ev.data.title);
        else if (ev.event === "sources") update({ sources: ev.data.sources });
        else if (ev.event === "grounding") update({ checks: ev.data });
        else if (ev.event === "token") {
          answer += ev.data.text;
          if (!frame) frame = requestAnimationFrame(flush);
        } else if (ev.event === "error") {
          if (frame) cancelAnimationFrame(frame);
          update({ content: answer, status: "error", error: ev.data.message });
          return;
        }
      }
      if (frame) cancelAnimationFrame(frame);
      update({ content: answer, status: "done" });
    } catch (err) {
      if (frame) cancelAnimationFrame(frame);
      const aborted = err instanceof DOMException && err.name === "AbortError";
      update(aborted
        ? { content: answer, status: "stopped" }
        : { content: answer, status: "error", error: "Connection lost. Please try again." });
    } finally {
      controller.current = null;
      setBusy(false);
      cb.current.onActivity(chatId);
    }
  }, []);

  return { messages, busy, load, reset, send, stop };
}
