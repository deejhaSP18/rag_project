import ReactMarkdown from "react-markdown";

const ALLOWED = ["p", "br", "strong", "em", "code", "pre", "ul", "ol", "li", "h1", "h2", "h3", "h4"];

/** Renders model output as markdown. react-markdown never injects raw HTML, and links/images are dropped. */
export function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown allowedElements={ALLOWED} unwrapDisallowed components={{ h1: "h3", h2: "h3", h4: "h3" }}>
      {text}
    </ReactMarkdown>
  );
}
