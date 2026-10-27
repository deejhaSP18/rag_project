import type { Chat, User } from "../api/types";
import { ThreadItem } from "./ThreadItem";

interface Props {
  chats: Chat[];
  activeId: string | null;
  open: boolean;
  online: boolean | null;
  theme: "light" | "dark";
  user: User | null;
  view: "chat" | "admin";
  onSignIn: () => void;
  onSignOut: () => void;
  onView: (view: "chat" | "admin") => void;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (chat: Chat) => void;
  onToggleTheme: () => void;
}

export function Sidebar({ chats, activeId, open, online, theme, user, view, onSignIn, onSignOut, onView, onNew, onOpen, onRename, onDelete, onToggleTheme }: Props) {
  const status = online === null ? "connecting…" : online ? "online" : "server unreachable";
  return (
    <aside className={`rail${open ? " open" : ""}`} aria-label="Conversations">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">F</span>
        <div>
          <div className="brand-name">Field Notes</div>
          <div className="brand-sub">ask your documents</div>
        </div>
      </div>

      <button className="btn-new" type="button" onClick={onNew}><span aria-hidden="true">+</span> New conversation</button>

      <div className="rail-label">Threads</div>
      <nav className="threads" aria-label="Saved conversations">
        {chats.length === 0 && <div className="threads-empty">No conversations yet. Ask something.</div>}
        {chats.map((chat) => (
          <ThreadItem
            key={chat.id} chat={chat} active={chat.id === activeId}
            onOpen={() => onOpen(chat.id)} onRename={(t) => onRename(chat.id, t)} onDelete={() => onDelete(chat)}
          />
        ))}
      </nav>

      <div className="account">
        {user ? (
          <>
            <span className="avatar" aria-hidden="true">{user.username[0].toUpperCase()}</span>
            <div className="account-name">
              <strong>{user.username}</strong>
              <small>{user.is_admin ? "admin" : "member"}</small>
            </div>
            {user.is_admin && (
              <button className="btn-ghost sm" type="button" onClick={() => onView(view === "admin" ? "chat" : "admin")}>
                {view === "admin" ? "Chat" : "Admin"}
              </button>
            )}
            <button className="btn-ghost sm" type="button" onClick={onSignOut}>Sign out</button>
          </>
        ) : (
          <>
            <div className="account-name">
              <strong>Guest</strong>
              <small>chats stay in this browser</small>
            </div>
            <button className="btn-ghost sm" type="button" onClick={onSignIn}>Sign in</button>
          </>
        )}
      </div>

      <div className="rail-foot">
        <span className={`pulse${online === true ? " ok" : online === false ? " bad" : ""}`} aria-hidden="true" />
        <span role="status">{status}</span>
        <button className="icon-btn" type="button" onClick={onToggleTheme} title="Toggle theme"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>◐</button>
      </div>
    </aside>
  );
}
