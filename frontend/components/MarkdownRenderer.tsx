"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import type { Components } from "react-markdown";

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    import("mermaid").then((m) => {
      if (cancelled || !ref.current) return;
      const mermaid = m.default;
      mermaid.initialize({
        startOnLoad: false,
        theme: "dark",
        themeVariables: {
          background: "#0d1117",
          primaryColor: "#1f6feb",
          primaryTextColor: "#c9d1d9",
          lineColor: "#8b949e",
          edgeLabelBackground: "#161b22",
          tertiaryColor: "#161b22",
        },
      });
      const id = `mermaid-${Math.random().toString(36).slice(2)}`;
      mermaid
        .render(id, code)
        .then(({ svg }) => {
          if (!cancelled && ref.current) ref.current.innerHTML = svg;
        })
        .catch(() => {
          if (!cancelled && ref.current) {
            ref.current.innerHTML = `<pre class="text-xs text-muted-foreground p-2">${code}</pre>`;
          }
        });
    });
    return () => { cancelled = true; };
  }, [code]);

  return (
    <div
      ref={ref}
      className="my-3 flex justify-center rounded-md border border-border bg-muted p-4 overflow-x-auto"
    />
  );
}

const components: Components = {
  // Headings
  h1: ({ children }) => (
    <h1 className="text-xl font-bold mt-4 mb-2 text-foreground border-b border-border pb-1">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-lg font-semibold mt-4 mb-2 text-foreground">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-base font-semibold mt-3 mb-1 text-foreground">{children}</h3>
  ),
  // Paragraphs
  p: ({ children }) => (
    <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
  ),
  // Lists — use ml-5 not list-inside to prevent number/bullet wrapping onto own line
  ul: ({ children }) => (
    <ul className="list-disc ml-5 space-y-1 mb-3">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal ml-5 space-y-1 mb-3">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-relaxed pl-1">{children}</li>,
  // Inline code
  code: ({ className, children, ...props }) => {
    const lang = (className ?? "").replace("language-", "");
    const isBlock = !!className;
    const code = String(children).replace(/\n$/, "");

    if (isBlock && lang === "mermaid") {
      return <MermaidBlock code={code} />;
    }
    if (isBlock) {
      return (
        <pre className="my-2 p-3 rounded-md bg-muted text-xs overflow-x-auto border border-border">
          <code className="text-foreground/90">{children}</code>
        </pre>
      );
    }
    return (
      <code
        className="px-1.5 py-0.5 rounded bg-muted text-xs font-mono text-foreground/90 border border-border"
        {...props}
      >
        {children}
      </code>
    );
  },
  // Blockquote
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-primary pl-3 my-2 text-muted-foreground italic">
      {children}
    </blockquote>
  ),
  // Table
  table: ({ children }) => (
    <div className="overflow-x-auto my-3">
      <table className="w-full text-xs border border-border rounded-md overflow-hidden">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-muted text-muted-foreground">{children}</thead>
  ),
  tbody: ({ children }) => (
    <tbody className="divide-y divide-border">{children}</tbody>
  ),
  tr: ({ children }) => (
    <tr className="hover:bg-accent/30 transition-colors">{children}</tr>
  ),
  th: ({ children }) => (
    <th className="px-3 py-2 text-left font-medium">{children}</th>
  ),
  td: ({ children }) => <td className="px-3 py-2">{children}</td>,
  // Horizontal rule
  hr: () => <hr className="border-border my-4" />,
  // Strong / em
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => <em className="italic text-foreground/80">{children}</em>,
  // Links
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline underline-offset-2 hover:text-primary/80"
    >
      {children}
    </a>
  ),
};

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose-sm max-w-none text-sm text-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
