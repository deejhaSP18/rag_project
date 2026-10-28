import { useCallback, useEffect, useRef, useState } from "react";
import { AdminPage } from "./components/AdminPage";
import { AuthDialog } from "./components/AuthDialog";
import { Composer } from "./components/Composer";
import { Sidebar } from "./components/Sidebar";
import { SourcePanel, type OpenSource } from "./components/SourcePanel";
import { Transcript } from "./components/Transcript";
import { useAuth } from "./hooks/useAuth";
import { useChats } from "./hooks/useChats";
import { useConversation } from "./hooks/useConversation";
import { useHealth } from "./hooks/useHealth";
import { useTheme } from "./hooks/useTheme";
import { safeStorage } from "./lib/storage";
import type { Chat } from "./api/types";

const DEFAULT_TITLE = "New conversation";

export default function App() {
  const auth = useAuth();
  const { user } = auth;
  // Chats belong to whoever is signed in (or to the guest cookie), so reload them when that changes.
  const scope = auth.ready ? String(user?.id ?? "guest") : null;
  const { chats, loaded, create, patch, touch, rename, remove } = useChats(scope);
  const [view, setView] = useState<"chat" | "admin">(() => (window.location.hash === "#/admin" ? "admin" : "chat"));
  const [signingIn, setSigningIn] = useState(false);
  const { health, online } = useHealth();
  const { theme, toggle } = useTheme();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  const [source, setSource] = useState<OpenSource | null>(null);
  const activeRef = useRef<string | null>(null);

  const select = useCallback((id: string | null) => {
    activeRef.current = id;
    setActiveId(id);
    setSource(null);
    safeStorage.set("activeChat", id ?? "");
  }, []);

  const conversation = useConversation({
    // Chats are created on the first question, so there are never empty chats.
    ensureChat: async () => {
      if (activeRef.current) return activeRef.current;
      const chat = await create();
      select(chat.id);
      return chat.id;
    },
    onTitle: (id, title) => patch(id, { title }),
    onActivity: touch,
  });
  const { messages, busy, load, reset, send, stop } = conversation;

  const open = useCallback(async (id: string) => {
    select(id);
    setRailOpen(false);
    try { await load(id); } catch { select(null); reset(); }
  }, [select, load, reset]);

  const startNew = useCallback(() => { select(null); reset(); setRailOpen(false); }, [select, reset]);

  const showView = useCallback((next: "chat" | "admin") => {
    setView(next);
    setSource(null);
    setRailOpen(false);
    window.history.replaceState(null, "", next === "admin" ? "#/admin" : window.location.pathname);
  }, []);

  // Restore the last open chat once the list has loaded.
  const restored = useRef(false);
  const lastScope = useRef<string | null>(null);
  useEffect(() => {
    if (scope === null) return;
    if (lastScope.current !== null && lastScope.current !== scope) {
      restored.current = true; // a different person: never reopen the previous person's chat
      select(null);
      reset();
      if (view === "admin") showView("chat");
    }
    lastScope.current = scope;
  }, [scope, select, reset, view, showView]);
  useEffect(() => {
    if (!loaded || restored.current) return;
    restored.current = true;
    const last = safeStorage.get("activeChat");
    if (last && chats.some((c) => c.id === last)) void open(last);
  }, [loaded, chats, open]);

  const onDelete = async (chat: Chat) => {
    if (!window.confirm(`Delete “${chat.title}”? This can't be undone.`)) return;
    await remove(chat.id);
    if (chat.id === activeId) startNew();
  };

  const isAdmin = !!user?.is_admin;
  const activeTitle = view === "admin" ? "Admin" : chats.find((c) => c.id === activeId)?.title ?? DEFAULT_TITLE;

  return (
    <div className={`shell${source && view === "chat" ? " with-source" : ""}`}>
      <Sidebar
        chats={chats} activeId={activeId} open={railOpen} online={online} theme={theme}
        user={user} view={view} onSignIn={() => setSigningIn(true)} onSignOut={() => void auth.signOut()} onView={showView}
        onNew={() => { showView("chat"); startNew(); }} onOpen={(id) => { showView("chat"); return open(id); }} onRename={(id, t) => void rename(id, t)} onDelete={onDelete} onToggleTheme={toggle}
      />
      {railOpen && <div className="scrim" onClick={() => setRailOpen(false)} />}

      <main className="stage">
        <header className="topbar">
          <button className="icon-btn only-mobile" type="button" aria-label="Open conversations" onClick={() => setRailOpen(true)}>☰</button>
          <h1 className="chat-title">{activeTitle}</h1>
          {health && view === "chat" && <span className="model-chip">{health.model}</span>}
        </header>
        {view === "admin" ? (
          !auth.ready ? null : isAdmin ? (
            <div className="admin-scroll"><AdminPage /></div>
          ) : (
            <div className="admin-scroll">
              <div className="gate">
                <h2>Admins only</h2>
                <p>{user ? "Your account doesn't have admin access." : "Sign in with an admin account to manage documents."}</p>
                {!user && <button className="btn-primary" type="button" onClick={() => setSigningIn(true)}>Sign in</button>}
              </div>
            </div>
          )
        ) : (
          <>
            <Transcript messages={messages} onPick={(q) => void send(q)} onOpenSource={(sources, index) => setSource({ sources, index })} />
            <Composer busy={busy} onSubmit={(q) => void send(q)} onStop={stop} />
          </>
        )}
      </main>
      {source && view === "chat" && (
        <SourcePanel open={source} onSelect={(index) => setSource({ ...source, index })} onClose={() => setSource(null)} />
      )}
      {signingIn && <AuthDialog onSubmit={auth.signIn} onClose={() => setSigningIn(false)} />}
    </div>
  );
}
