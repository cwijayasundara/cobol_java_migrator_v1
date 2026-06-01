"use client";

import { useState } from "react";
import { MessageSquare, Send, Bot, User } from "lucide-react";
import { api } from "@/lib/api";

type Msg =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; grounded: boolean; model: string | null };

// Explore stage: "ask the codebase" chat. Questions are answered by Claude,
// grounded in the parsed Neo4j graph (run Parse first). Read-only exploration.
export function ExploreChat({ workspaceId, repoSlug }: { workspaceId: string; repoSlug: string }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  const ask = async () => {
    const question = q.trim();
    if (!question || busy) return;
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setQ("");
    setBusy(true);
    try {
      const a = await api.askWorkspace(workspaceId, question);
      setMsgs((m) => [...m, { role: "assistant", text: a.answer, grounded: a.grounded, model: a.model }]);
    } catch (e) {
      setMsgs((m) => [...m, {
        role: "assistant", grounded: false, model: null,
        text: `Ask failed: ${e instanceof Error ? e.message : String(e)}`,
      }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-4 flex flex-col h-full max-w-3xl">
      <div className="flex items-center gap-2 mb-1">
        <MessageSquare className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Ask the codebase</h3>
      </div>
      <p className="text-xs text-zinc-500 mb-3">
        Natural-language questions about <span className="font-mono">{repoSlug}</span>,
        answered by Claude and grounded in the parsed graph (run the Parse stage first).
      </p>

      <ol className="flex-1 overflow-auto space-y-3 pr-1">
        {msgs.length === 0 && (
          <li className="text-xs text-zinc-600">
            e.g. “Which programs write ACCTFILE?” · “What does CBVALDTM do?” ·
            “Which programs are reader-only?”
          </li>
        )}
        {msgs.map((m, i) => (
          <li key={i} className="flex gap-2 text-sm">
            <span className="mt-0.5 shrink-0">
              {m.role === "user"
                ? <User className="w-4 h-4 text-zinc-400" />
                : <Bot className="w-4 h-4 text-indigo-400" />}
            </span>
            <div className={m.role === "user" ? "text-zinc-200" : "text-zinc-300"}>
              <div className="whitespace-pre-wrap">{m.text}</div>
              {m.role === "assistant" && !m.grounded && (
                <div className="text-xs text-amber-400 mt-1">not grounded in a parsed graph</div>
              )}
            </div>
          </li>
        ))}
        {busy && <li className="text-xs text-zinc-500">thinking…</li>}
      </ol>

      <form
        className="mt-3 flex items-center gap-2"
        onSubmit={(e) => { e.preventDefault(); ask(); }}
      >
        <input
          aria-label="question"
          className="flex-1 bg-zinc-800 rounded px-3 py-2 text-sm"
          placeholder="Ask about this codebase…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy || q.trim() === ""}
          className="inline-flex items-center gap-1 px-3 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40"
        >
          <Send className="w-4 h-4" /> Ask
        </button>
      </form>
    </div>
  );
}
