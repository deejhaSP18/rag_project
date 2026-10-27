import { useEffect } from "react";
import type { Source } from "../api/types";

export interface OpenSource {
  sources: Source[];
  index: number;
}

const ROLE_LABEL = { match: "Match", context: "Nearby text", related: "Related" } as const;

export const pageLabel = (s: Source) =>
  s.page ? (s.page_end && s.page_end !== s.page ? `pages ${s.page}–${s.page_end}` : `page ${s.page}`) : "";

/** Side panel with the full passage text, exactly as the model read it. */
export function SourcePanel({ open, onSelect, onClose }: { open: OpenSource; onSelect: (i: number) => void; onClose: () => void }) {
  const { sources, index } = open;
  const current = sources[index];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!current) return null;
  const where = [pageLabel(current), current.section].filter(Boolean).join(" · ");
  return (
    <aside className="source-panel" aria-label="Source passage">
      <header>
        <div>
          <strong title={current.source}>{current.source}</strong>
          {where && <span>{where}</span>}
        </div>
        <button className="icon-btn" type="button" aria-label="Close source panel" onClick={onClose}>✕</button>
      </header>

      {sources.length > 1 && (
        <nav className="source-tabs" aria-label="Passages used for this answer">
          {sources.map((s, i) => (
            <button key={s.id ?? i} type="button" className={i === index ? "on" : ""} onClick={() => onSelect(i)}
              title={`${s.source}${s.section ? ` · ${s.section}` : ""}`}>
              {s.n ?? i + 1}
            </button>
          ))}
        </nav>
      )}

      <div className="source-meta">
        {current.role && <b className={`badge role-${current.role}`}>{ROLE_LABEL[current.role]}</b>}
        {current.score != null && <span>{Math.round(current.score * 100)}% relevant</span>}
      </div>
      <div className="source-text">
        {(current.text ?? current.snippet).split(/\n+/).map((line, i) => <p key={i}>{line}</p>)}
        {!current.text && <p className="source-old">Full passage text was not saved for this older answer.</p>}
      </div>
    </aside>
  );
}
