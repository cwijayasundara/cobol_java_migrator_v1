"use client";

import { RepositoryIntake } from "@/components/screens/RepositoryIntake";
import { ParseStudio } from "@/components/screens/ParseStudio";
import { GraphExplorer } from "@/components/screens/GraphExplorer";
import { ExploreChat } from "@/components/screens/ExploreChat";
import { BlueprintStudio } from "@/components/screens/BlueprintStudio";
import { SeamStudio } from "@/components/screens/SeamStudio";
import { IncrementPlanner } from "@/components/screens/IncrementPlanner";
import { DesignStudio } from "@/components/screens/DesignStudio";
import { BuildLab } from "@/components/screens/BuildLab";
import { EquivalenceLab } from "@/components/screens/EquivalenceLab";

export function StageScreen(
  { workspaceId, stageKey, repoSlug }: { workspaceId: string; stageKey: string; repoSlug: string },
) {
  switch (stageKey) {
    case "intake": return <RepositoryIntake workspaceId={workspaceId} />;
    case "parse": return <ParseStudio workspaceId={workspaceId} />;
    case "graph": return <GraphExplorer workspaceId={workspaceId} repoSlug={repoSlug} />;
    case "explore": return <ExploreChat workspaceId={workspaceId} repoSlug={repoSlug} />;
    case "blueprint": return <BlueprintStudio workspaceId={workspaceId} />;
    case "seams": return <SeamStudio workspaceId={workspaceId} />;
    case "plan": return <IncrementPlanner workspaceId={workspaceId} />;
    case "design": return <DesignStudio workspaceId={workspaceId} />;
    case "build": return <BuildLab workspaceId={workspaceId} />;
    case "verify": return <EquivalenceLab workspaceId={workspaceId} />;
    default:
      return <div className="p-4 text-sm text-zinc-500">Stage: {stageKey}</div>;
  }
}
