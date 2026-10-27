import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";

/** Who is signed in. `user` is null for visitors, who still get their own private chats. */
export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setReady(true));
  }, []);

  const signIn = useCallback(async (username: string, password: string, register: boolean) => {
    setUser(await (register ? api.register(username, password) : api.login(username, password)));
  }, []);

  const signOut = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setUser(null);
  }, []);

  return { user, ready, signIn, signOut };
}
