"use client";

import Link from "next/link";
import { STAGES, STAGE_STATUS_COLOR } from "@/lib/stages";
import type { JourneyStage, StageStatus } from "@/lib/types";

interface Props {
  workspaceId: string;
  stages: JourneyStage[];
  active: string;
}

export function JourneyRail({ workspaceId, stages, active }: Props) {
  const statusOf = (key: string): StageStatus =>
    stages.find((s) => s.stage_key === key)?.status ?? "pending";

  return (
    <nav className="w-44 shrink-0 border-r border-zinc-800 bg-zinc-900/30 py-4">
      <ol className="space-y-1">
        {STAGES.map((stage, i) => {
          const status = statusOf(stage.key);
          const isActive = stage.key === active;
          return (
            <li key={stage.key}>
              <Link
                href={`/workspaces/${workspaceId}/journey/${stage.key}`}
                aria-current={isActive ? "step" : undefined}
                className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-md mx-2 ${
                  isActive ? "bg-zinc-800 text-white" : "text-zinc-400 hover:bg-zinc-800/50"
                }`}
              >
                <span className={`w-2 h-2 rounded-full ${STAGE_STATUS_COLOR[status].split(" ")[0]}`} />
                <span className="text-xs text-zinc-600 w-4">{i}</span>
                {stage.label}
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
