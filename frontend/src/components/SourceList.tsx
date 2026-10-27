import type { Source } from "../api/types";
import { pageLabel } from "./SourcePanel";

interface Props {
  sources: Source[];
  /** Passage numbers the answer relied on; the rest were retrieved but not needed. */
  used?: number[];
  onOpen: (index: number) => void;
}

const ROLE_NOTE = { match: "", context: "nearby text", related: "linked passage" } as const;

export function SourceList({ sources, used, onOpen }: Props) {
  if (!sources.length) return null;
  return (
    <details className="sources">
      <summary>Sources · {sources.length}</summary>
      <div className="source-list">
        {sources.map((s, i) => {
          const where = [pageLabel(s), s.section].filter(Boolean).join(" · ");
          const note = s.role ? ROLE_NOTE[s.role] : "";
          const isUsed = !!used?.length && s.n != null && used.includes(s.n);
          return (
            <button className={`ticket${isUsed ? " used" : ""}`} type="button" key={s.id ?? `${s.source}-${i}`} onClick={() => onOpen(i)}
              title="Open the full passage next to the chat">
              <div className="ticket-head">
                {s.n != null && <span className="ticket-n">{s.n}</span>}
                <span className="ticket-name">{s.source}</span>
                {isUsed && <span className="ticket-used">used</span>}
                {s.score != null && <span className="ticket-score">{Math.round(s.score * 100)}%</span>}
              </div>
              {(where || note) && <div className="ticket-where">{[where, note].filter(Boolean).join(" · ")}</div>}
              <p className="ticket-snip">{s.snippet}…</p>
            </button>
          );
        })}
      </div>
    </details>
  );
}
