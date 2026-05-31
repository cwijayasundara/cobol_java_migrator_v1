"use client";

import { useEffect, useState } from "react";
import { Bot } from "lucide-react";
import { api } from "@/lib/api";
import { useAgentStream } from "@/lib/useAgentStream";
import type { AgentRun, AgentEventType } from "@/lib/types";

const EVENT_LABEL: Record<AgentEventType, string> = {
  plan: "plan", tool_call: "tool", tool_result: "result", cost: "cost",
  result: "done", approval_request: "approval", failed: "failed", killed: "killed",
};

export function AgentConsole({ workspaceId, stageKey }: { workspaceId: string; stageKey: string }) {
  const [run, setRun] = useState<AgentRun | null>(null);
  useEffect(() => {
    (async () => {
      const runs = await api.listRuns(workspaceId);
      // single user-visible agent: show the most recent running run, else newest
      const active = runs.find((r) => r.status === "running") ?? runs[0] ?? null;
      setRun(active);
    })();
  }, [workspaceId, stageKey]);

  const { events, connected } = useAgentStream(workspaceId, run?.id ?? null);

  return (
    <section className="border-t border-zinc-800 bg-zinc-900/40 h-56 flex flex-col">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
        <Bot className="w-4 h-4 text-indigo-400" />
        <span className="text-sm font-medium">Modernization Agent</span>
        {run && (
          <span className="text-xs text-zinc-500 font-mono">
            {run.id} · {run.role} · {run.model} · {run.status}
            {connected ? " · live" : ""}
          </span>
        )}
      </div>
      <ol className="flex-1 overflow-auto px-4 py-2 space-y-1 font-mono text-xs">
        {events.map((e) => (
          <li key={`${e.seq}-${e.ts}`} className="flex gap-2">
            <span className="text-zinc-600 w-16 shrink-0">[{EVENT_LABEL[e.type]}]</span>
            <span className="text-zinc-300">{e.summary}</span>
          </li>
        ))}
        {events.length === 0 && (
          <li className="text-zinc-600">No agent activity yet for this run.</li>
        )}
      </ol>
    </section>
  );
}
