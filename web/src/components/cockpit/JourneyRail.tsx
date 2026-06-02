"use client";

import Link from "next/link";
import { PHASES, stageOrdinal, stageLabel } from "@/lib/stages";
import type { JourneyStage, StageStatus } from "@/lib/types";

interface Props {
  workspaceId: string;
  stages: JourneyStage[];
  active: string;
}

/** Fill color for a stage node, keyed by status. */
const NODE_FILL: Record<StageStatus, string> = {
  pending: "bg-zinc-800 border border-zinc-600",
  running: "bg-sky-500 border border-sky-400 animate-pulse",
  blocked: "bg-amber-500 border border-amber-400",
  passed: "bg-emerald-500 border border-emerald-400",
  failed: "bg-red-500 border border-red-400",
};

export function JourneyRail({ workspaceId, stages, active }: Props) {
  const statusOf = (key: string): StageStatus =>
    stages.find((s) => s.stage_key === key)?.status ?? "pending";

  return (
    <nav
      aria-label="Migration workflow"
      className="w-52 shrink-0 overflow-y-auto border-r border-zinc-800 bg-zinc-900/30 py-4"
    >
      {PHASES.map((phase) => (
        <section key={phase.key} className="mb-5 last:mb-0">
          <h3 className="mb-1 px-4 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            {phase.label.toUpperCase()}
          </h3>
          <ol>
            {phase.stageKeys.map((key, i) => {
              const status = statusOf(key);
              const isActive = key === active;
              const isFirst = i === 0;
              const isLast = i === phase.stageKeys.length - 1;
              // The rail segment entering this node is "done" when the
              // previous stage in the phase has passed.
              const prevPassed =
                !isFirst && statusOf(phase.stageKeys[i - 1]) === "passed";
              const railDone = "bg-emerald-500/70";
              const railTodo = "bg-zinc-700";

              return (
                <li key={key}>
                  <Link
                    href={`/workspaces/${workspaceId}/journey/${key}`}
                    aria-current={isActive ? "step" : undefined}
                    className={`group flex items-stretch gap-3 pr-3 text-sm ${
                      isActive
                        ? "bg-zinc-800 text-white"
                        : "text-zinc-400 hover:bg-zinc-800/50"
                    }`}
                  >
                    {/* Rail column: connector lines + node */}
                    <span
                      aria-hidden
                      className="relative ml-4 flex w-3 shrink-0 flex-col items-center"
                    >
                      <span
                        className={`w-px flex-1 ${
                          isFirst ? "bg-transparent" : prevPassed ? railDone : railTodo
                        }`}
                      />
                      <span
                        className={`my-1 h-2.5 w-2.5 rounded-full ${NODE_FILL[status]} ${
                          isActive ? "ring-2 ring-white ring-offset-1 ring-offset-zinc-900" : ""
                        }`}
                      />
                      <span
                        className={`w-px flex-1 ${
                          isLast ? "bg-transparent" : status === "passed" ? railDone : railTodo
                        }`}
                      />
                    </span>

                    {/* Label */}
                    <span className="flex items-center gap-2 py-1.5">
                      <span className="w-4 text-xs tabular-nums text-zinc-600">
                        {stageOrdinal(key)}
                      </span>
                      {stageLabel(key)}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </nav>
  );
}
