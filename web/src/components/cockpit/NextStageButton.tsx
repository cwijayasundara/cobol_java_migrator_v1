"use client";

import Link from "next/link";
import { ADVANCEABLE_STAGES, nextStage } from "@/lib/stages";

interface Props {
  workspaceId: string;
  stageKey: string;
}

/**
 * "Next step" button that advances from the current workbench screen to the
 * following stage in the journey. Rendered only for the interactive stages
 * listed in {@link ADVANCEABLE_STAGES}; returns null otherwise.
 */
export function NextStageButton({ workspaceId, stageKey }: Props) {
  if (!ADVANCEABLE_STAGES.has(stageKey)) return null;
  const next = nextStage(stageKey);
  if (!next) return null;

  return (
    <Link
      href={`/workspaces/${workspaceId}/journey/${next.key}`}
      className="inline-flex items-center gap-1.5 rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-sky-500"
    >
      Next: {next.label}
      <span aria-hidden>→</span>
    </Link>
  );
}
