"use client";

import type { Gate, GateStatus } from "@/lib/types";

const TONE: Record<GateStatus, string> = {
  open: "bg-zinc-700 text-zinc-200",
  passed: "bg-emerald-700 text-white",
  failed: "bg-red-700 text-white",
  waived: "bg-amber-700 text-white",
};

export function GatePills({ gates }: { gates: Gate[] }) {
  if (gates.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5">
      {gates.map((g) => (
        <span key={g.id} className={`text-xs px-2 py-1 rounded-full ${TONE[g.status]}`}>
          {g.gate_key}: {g.status}
        </span>
      ))}
    </div>
  );
}
