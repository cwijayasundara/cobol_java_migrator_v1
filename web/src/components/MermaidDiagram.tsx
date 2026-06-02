"use client";

import { useEffect, useId, useRef, useState } from "react";

// Renders a Mermaid diagram string to SVG. Mermaid is lazy-imported so it stays out of the
// initial bundle, and render failures degrade to an error line + the source (never crash the
// page). A "show source" toggle keeps the raw text available for copying into docs.
export function MermaidDiagram({ chart, caption }: { chart: string; caption?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSrc, setShowSrc] = useState(false);
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        // securityLevel "strict" makes mermaid run its built-in DOMPurify pass over the
        // generated SVG, so the string we inject below is already sanitized (no inline
        // scripts/handlers) — this is the documented, safe way to mount mermaid output.
        mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
        const { svg } = await mermaid.render(`mmd-${uid}`, chart);
        if (alive && ref.current) ref.current.innerHTML = svg;  // sanitized SVG (strict mode)
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { alive = false; };
  }, [chart, uid]);

  return (
    <div className="rounded-md border border-zinc-800 p-3 space-y-2 overflow-x-auto">
      {caption && <div className="text-xs text-zinc-500">{caption}</div>}
      {error
        ? <div className="text-xs text-red-300">diagram error: {error}</div>
        : <div ref={ref} className="[&_svg]:max-w-full [&_svg]:h-auto" />}
      <button onClick={() => setShowSrc((v) => !v)}
        className="text-[10px] text-zinc-500 hover:text-zinc-300">
        {showSrc ? "hide source" : "show source"}
      </button>
      {showSrc && (
        <pre className="text-[10px] text-zinc-400 bg-zinc-950/60 p-2 rounded overflow-x-auto whitespace-pre">
          {chart}
        </pre>
      )}
    </div>
  );
}
