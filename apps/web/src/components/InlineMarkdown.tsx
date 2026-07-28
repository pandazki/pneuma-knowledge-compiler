import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Inline markdown renderer for cleaned claim prose. Internal links ([text](x.md))
 * are intercepted and routed through `onLink` with the raw href, so the reader can
 * resolve them to a document and jump. Paragraphs unwrap to fragments to stay inline.
 */
export function InlineMarkdown({
  text,
  onLink,
}: {
  text: string;
  onLink?: (href: string) => void;
}) {
  return (
    <span className="pneuma-prose">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <>{children}</>,
          a: ({ href, children }) => {
            const target = href ?? "";
            const internal = /\.md($|#)/.test(target);
            if (internal && onLink) {
              return (
                <a
                  onClick={(e) => {
                    e.preventDefault();
                    onLink(target);
                  }}
                  href={target}
                >
                  {children}
                </a>
              );
            }
            return (
              <a href={target} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </span>
  );
}
