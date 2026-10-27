import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Health } from "../api/types";

/** Polls the backend so the sidebar can show whether it is reachable. */
export function useHealth(intervalMs = 20000) {
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    const check = () =>
      api.health().then(
        (h) => alive && (setHealth(h), setOnline(true)),
        () => alive && setOnline(false),
      );
    check();
    const id = setInterval(check, intervalMs);
    return () => { alive = false; clearInterval(id); };
  }, [intervalMs]);

  return { health, online };
}
