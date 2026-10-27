import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

interface Props {
  busy: boolean;
  onSubmit: (text: string) => void;
  onStop: () => void;
}

export function Composer({ busy, onSubmit, onStop }: Props) {
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);

  // Grow with content, up to a cap.
  useLayoutEffect(() => {
    const node = area.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 200)}px`;
  }, [text]);

  useEffect(() => { if (!busy) area.current?.focus(); }, [busy]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!text.trim() || busy) return;
    onSubmit(text);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  };

  return (
    <footer className="composer-wrap">
      <form className="composer" onSubmit={submit}>
        <label className="sr-only" htmlFor="question">Your question</label>
        <textarea
          id="question" ref={area} rows={1} maxLength={4000} value={text}
          placeholder="Ask about your documents…  (Shift + Enter for a new line)"
          onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown}
        />
        {busy ? (
          <button className="stop" type="button" onClick={onStop} aria-label="Stop generating">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" /></svg>
          </button>
        ) : (
          <button className="send" type="submit" disabled={!text.trim()} aria-label="Send question">
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M4 12l16-8-6 16-3-7z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /></svg>
          </button>
        )}
      </form>
      <p className="fineprint">Answers come only from your indexed documents. SQL and code are never executed.</p>
    </footer>
  );
}
