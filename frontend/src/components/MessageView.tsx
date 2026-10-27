import { memo } from "react";
import type { UiMessage } from "../hooks/useConversation";
import { Markdown } from "./Markdown";
import { SourceList } from "./SourceList";

interface Props {
  message: UiMessage;
  /** Open the source panel on passage `index` of this message's sources. */
  onOpenSource: (sources: UiMessage["sources"], index: number) => void;
}

function MessageViewBase({ message, onOpenSource }: Props) {
  const { role, content, sources, checks, status, error } = message;

  if (role === "user") {
    return (
      <article className="msg user">
        <div className="who">You</div>
        <div className="body">{content}</div>
      </article>
    );
  }

  const streaming = status === "streaming";
  return (
    <article className="msg assistant">
      <div className="who">Notes</div>
      <div className={`body${streaming && content ? " cursor" : ""}`}>
        {streaming && !content ? (
          <span className="thinking" role="status" aria-label="Thinking"><i /><i /><i /></span>
        ) : (
          <Markdown text={content} />
        )}
        {status === "stopped" && <div className="stopped-note">Stopped.</div>}
        {status === "error" && <div className="error-note">{error}</div>}
        {!streaming && checks && !checks.ok && checks.unsupported.length > 0 && (
          <div className="check-note" role="note">
            Check these against the sources: {checks.unsupported.join(", ")}. They were not found in the passages used for this answer.
          </div>
        )}
        {!streaming && <SourceList sources={sources} used={checks?.used} onOpen={(i) => onOpenSource(sources, i)} />}
      </div>
    </article>
  );
}

export const MessageView = memo(MessageViewBase);
