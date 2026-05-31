"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Artifact, Gate } from "@/lib/types";

export function BlueprintStudio({ workspaceId }: { workspaceId: string }) {
  const [brds, setBrds] = useState<Artifact[]>([]);
  const [gate, setGate] = useState<Gate | null>(null);
  useEffect(() => {
    (async () => {
      const arts = await api.listArtifacts(workspaceId);
      setBrds(arts.filter((a) => a.kind === "brd"));
      const gates = await api.listGates(workspaceId);
      setGate(gates.find((g) => g.gate_key === "brd_groundedness") ?? null);
    })();
  }, [workspaceId]);
  return (
    <div className="p-4 space-y-3">
      <h3 className="text-sm font-medium text-zinc-300">Functional Blueprint (BRD)</h3>
      {gate && (
        <div className="text-xs text-zinc-400">
          groundedness gate: weighted {String(gate.result.weighted ?? "—")} /
          threshold {String((gate.threshold as Record<string, unknown>).min_weighted ?? "—")} ·{" "}
          <span className={gate.status === "passed" ? "text-emerald-400" : "text-amber-400"}>
            {gate.status}
          </span>
        </div>
      )}
      <ul className="space-y-1">
        {brds.map((b) => (
          <li key={b.id}>
            <Link className="text-indigo-400 hover:underline text-sm"
                  href={`/workspaces/${workspaceId}/artifacts/${b.id}`}>
              BRD v{b.version}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
