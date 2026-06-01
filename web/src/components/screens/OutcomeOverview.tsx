"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Target, GitBranch, DollarSign, ArrowRight } from "lucide-react";
import { api, type GraphSummary } from "@/lib/api";
import type { JourneyStage, Budget } from "@/lib/types";
import { STAGES, stageLabel } from "@/lib/stages";

// Outcome stage = workspace landing/overview: repo, journey progress, graph stats,
// budget, and the next actionable step.
export function OutcomeOverview({ workspaceId, repoSlug }: { workspaceId: string; repoSlug: string }) {
  const [stages, setStages] = useState<JourneyStage[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [graph, setGraph] = useState<GraphSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setStages(await api.listStages(workspaceId).catch(() => []));
      setBudget(await api.getWorkspaceBudget(workspaceId).catch(() => null));
      setGraph(await api.getGraphSummary(workspaceId).catch(() => null));
      setLoading(false);
    })();
  }, [workspaceId]);

  const statusOf = (key: string) => stages.find((s) => s.stage_key === key)?.status ?? "pending";
  const passed = STAGES.filter((s) => statusOf(s.key) === "passed").length;
  const running = STAGES.find((s) => statusOf(s.key) === "running");
  // next actionable stage = first non-passed stage after "outcome"
  const next = STAGES.find((s) => s.key !== "outcome" && statusOf(s.key) !== "passed");

  const Stat = ({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) => (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex items-center gap-2 text-xs text-zinc-500">{icon}{label}</div>
      <div className="mt-2 text-sm text-zinc-200">{children}</div>
    </div>
  );

  return (
    <div className="p-6 max-w-4xl space-y-6">
      <div className="flex items-center gap-2">
        <Target className="w-5 h-5 text-indigo-400" />
        <h2 className="text-lg font-semibold">Outcome</h2>
        <span className="text-xs text-zinc-500 font-mono">{repoSlug}</span>
      </div>

      {loading ? (
        <div className="text-sm text-zinc-500">Loading overview…</div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Stat icon={<GitBranch className="w-3.5 h-3.5" />} label="Journey">
              {passed} / {STAGES.length} stages passed
              {running && <div className="text-xs text-sky-400 mt-1">● {stageLabel(running.key)} running</div>}
            </Stat>
            <Stat icon={<GitBranch className="w-3.5 h-3.5" />} label="Code graph">
              {graph && graph.entities > 0
                ? <>{graph.entities} entities · {graph.relationships} relationships</>
                : <span className="text-zinc-500">not parsed yet</span>}
            </Stat>
            <Stat icon={<DollarSign className="w-3.5 h-3.5" />} label="Budget">
              {budget ? <>${budget.spent_usd.toFixed(2)} / ${budget.cap_usd.toFixed(0)}</> : "—"}
            </Stat>
          </div>

          {graph && graph.entities > 0 && (
            <div className="text-xs text-zinc-500">
              {Object.entries(graph.by_kind).map(([k, v]) => `${k}: ${v}`).join(" · ")}
            </div>
          )}

          {next && (
            <Link
              href={`/workspaces/${workspaceId}/journey/${next.key}`}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600"
            >
              Next: {stageLabel(next.key)} <ArrowRight className="w-4 h-4" />
            </Link>
          )}
        </>
      )}
    </div>
  );
}
