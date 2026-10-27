import { useEffect, useRef } from "react";
import type { UiMessage } from "../hooks/useConversation";
import { MessageView } from "./MessageView";
import { Welcome } from "./Welcome";

interface Props {
  messages: UiMessage[];
  onPick: (question: string) => void;
  onOpenSource: (sources: UiMessage["sources"], index: number) => void;
}

const NEAR_BOTTOM_PX = 90;

/** Scrolls with the stream, unless the reader has scrolled up to re-read. */
export function Transcript({ messages, onPick, onOpenSource }: Props) {
  const ref = useRef<HTMLElement>(null);
  const stick = useRef(true);
  const count = useRef(0);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (messages.length !== count.current) { stick.current = true; count.current = messages.length; }
    if (stick.current) node.scrollTop = node.scrollHeight;
  }, [messages]);

  return (
    <section
      className="transcript"
      ref={ref}
      aria-label="Conversation"
      onScroll={(e) => {
        const t = e.currentTarget;
        stick.current = t.scrollHeight - t.scrollTop - t.clientHeight < NEAR_BOTTOM_PX;
      }}
    >
      <div className="column">
        {messages.length === 0 ? <Welcome onPick={onPick} /> : messages.map((m) => <MessageView key={m.key} message={m} onOpenSource={onOpenSource} />)}
      </div>
    </section>
  );
}
