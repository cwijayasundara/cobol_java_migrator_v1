"use client";

import { DollarSign, Ban } from "lucide-react";
import type { Budget } from "@/lib/types";

export function CostPill({ budget }: { budget: Budget | null }) {
  if (!budget) return null;
  const pct = budget.cap_usd > 0 ? budget.spent_usd / budget.cap_usd : 0;
  const tone = budget.killed
    ? "bg-red-700 text-white"
    : pct >= 0.9
      ? "bg-amber-600 text-white"
      : "bg-zinc-800 text-zinc-200";
  return (
    <span className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${tone}`}>
      {budget.killed ? <Ban className="w-3 h-3" /> : <DollarSign className="w-3 h-3" />}
      ${budget.spent_usd.toFixed(2)} / ${budget.cap_usd.toFixed(0)}
      {budget.killed && <span className="ml-1 font-semibold">killed</span>}
    </span>
  );
}
