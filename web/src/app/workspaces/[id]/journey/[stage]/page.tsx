"use client";

import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { JourneyStage, Gate, Budget, Workspace } from "@/lib/types";
import { JourneyRail } from "@/components/cockpit/JourneyRail";
import { StageHeader } from "@/components/cockpit/StageHeader";
import { AgentConsole } from "@/components/cockpit/AgentConsole";
import { EvidenceDrawer } from "@/components/cockpit/EvidenceDrawer";
import { StageScreen } from "@/components/screens/StageScreen";

export default function Page({ params }: { params: Promise<{ id: string; stage: string }> }) {
  const { id, stage } = use(params);
  const [ws, setWs] = useState<Workspace | null>(null);
  const [stages, setStages] = useState<JourneyStage[]>([]);
  const [gates, setGates] = useState<Gate[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);

  useEffect(() => {
    (async () => {
      setWs(await api.getWorkspace(id));
      setStages(await api.listStages(id));
      setGates(await api.listGates(id));
      setBudget(await api.getWorkspaceBudget(id).catch(() => null));
    })();
  }, [id]);

  const stageGates = gates.filter(
    (g) => g.stage_id === stages.find((s) => s.stage_key === stage)?.id,
  );

  return (
    <>
      <JourneyRail workspaceId={id} stages={stages} active={stage} />
      <div className="flex-1 flex flex-col min-w-0">
        <StageHeader stageKey={stage} gates={stageGates} budget={budget} />
        <div className="flex-1 overflow-auto">
          {ws && <StageScreen workspaceId={id} stageKey={stage} repoSlug={ws.repo_slug} />}
        </div>
        <AgentConsole workspaceId={id} stageKey={stage} />
      </div>
      <EvidenceDrawer workspaceId={id} />
    </>
  );
}
