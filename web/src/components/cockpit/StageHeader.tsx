"use client";

import { stageLabel } from "@/lib/stages";
import { GatePills } from "@/components/cockpit/GatePills";
import { CostPill } from "@/components/cockpit/CostPill";
import { NextStageButton } from "@/components/cockpit/NextStageButton";
import type { Gate, Budget } from "@/lib/types";

interface Props {
  workspaceId: string;
  stageKey: string;
  gates: Gate[];
  budget: Budget | null;
}

export function StageHeader({ workspaceId, stageKey, gates, budget }: Props) {
  return (
    <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
      <h2 className="text-lg font-semibold">{stageLabel(stageKey)}</h2>
      <div className="flex items-center gap-2">
        <GatePills gates={gates} />
        <CostPill budget={budget} />
        <NextStageButton workspaceId={workspaceId} stageKey={stageKey} />
      </div>
    </header>
  );
}
