import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Chat } from "../api/types";

/** The sidebar's list of saved conversations. `scope` identifies whose chats; the list reloads when it changes. */
export function useChats(scope: string | null) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (scope === null) return;
    let current = true;
    setLoaded(false);
    api
      .listChats()
      .then((list) => current && setChats(list))
      .catch(() => current && setChats([]))
      .finally(() => current && setLoaded(true));
    return () => { current = false; };
  }, [scope]);

  const create = useCallback(async () => {
    const chat = await api.createChat();
    setChats((prev) => [chat, ...prev]);
    return chat;
  }, []);

  const patch = useCallback((id: string, changes: Partial<Chat>) => {
    setChats((prev) => prev.map((c) => (c.id === id ? { ...c, ...changes } : c)));
  }, []);

  /** Move a chat to the top after new activity. */
  const touch = useCallback((id: string) => {
    setChats((prev) => {
      const target = prev.find((c) => c.id === id);
      if (!target) return prev;
      return [{ ...target, updated_at: new Date().toISOString() }, ...prev.filter((c) => c.id !== id)];
    });
  }, []);

  const rename = useCallback(
    async (id: string, title: string) => {
      await api.renameChat(id, title);
      patch(id, { title });
    },
    [patch],
  );

  const remove = useCallback(async (id: string) => {
    await api.deleteChat(id);
    setChats((prev) => prev.filter((c) => c.id !== id));
  }, []);

  return { chats, loaded, create, patch, touch, rename, remove };
}
