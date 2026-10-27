import { useState, type KeyboardEvent } from "react";
import type { Chat } from "../api/types";
import { timeAgo } from "../lib/time";

interface Props {
  chat: Chat;
  active: boolean;
  onOpen: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}

export function ThreadItem({ chat, active, onOpen, onRename, onDelete }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(chat.title);

  const finish = (save: boolean) => {
    setEditing(false);
    const title = draft.trim();
    if (save && title && title !== chat.title) onRename(title);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  };

  if (editing) {
    return (
      <div className="thread">
        <input
          className="rename-input" autoFocus maxLength={80} value={draft} aria-label="Conversation name"
          onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} onBlur={() => finish(true)}
          onFocus={(e) => e.currentTarget.select()}
        />
      </div>
    );
  }

  return (
    <div className={`thread${active ? " active" : ""}`}>
      <button className="thread-open" type="button" onClick={onOpen} aria-current={active ? "true" : undefined}>
        <span className="thread-title">{chat.title}</span>
        <span className="thread-when">{timeAgo(chat.updated_at)}</span>
      </button>
      <div className="thread-actions">
        <button className="mini" type="button" title="Rename" aria-label={`Rename ${chat.title}`}
          onClick={() => { setDraft(chat.title); setEditing(true); }}>✎</button>
        <button className="mini danger" type="button" title="Delete" aria-label={`Delete ${chat.title}`}
          onClick={onDelete}>✕</button>
      </div>
    </div>
  );
}
