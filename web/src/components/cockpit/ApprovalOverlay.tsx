"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Approval, Budget, Gate } from "@/lib/types";

const ROLES = ["lead_engineer", "architect", "risk_officer"];

interface Props {
  gate: Gate;
  budget: Budget | null;
  currentUserEmail: string;
  estimatedCostUsd: number;
  onDecided: (approval: Approval) => void;
}

export function ApprovalOverlay({ gate, budget, currentUserEmail, estimatedCostUsd, onDecided }: Props) {
  const [role, setRole] = useState("");
  const [rationale, setRationale] = useState("");
  const [riskAccepted, setRiskAccepted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const remainingAfter =
    budget ? Math.max(0, budget.cap_usd - budget.spent_usd - estimatedCostUsd) : null;
  const canDecide = role !== "" && rationale.trim().length > 0;

  const decide = async (decision: Approval["decision"]) => {
    setSubmitting(true);
    const approval = await api.submitApproval(gate.id, {
      decision,
      approver_email: currentUserEmail, // RBAC identity (non-negotiable)
      approver_role: role,
      risk_accepted: decision === "waived_with_risk" ? true : riskAccepted,
      rationale,
    });
    setSubmitting(false);
    onDecided(approval);
  };

  return (
    <div className="fixed inset-0 z-[70] bg-black/60 flex items-center justify-center">
      <div className="w-[28rem] rounded-lg border border-zinc-700 bg-zinc-900 p-5 space-y-3">
        <h3 className="text-base font-semibold">
          Approve gate: <span className="font-mono">{gate.gate_key}</span>
        </h3>

        {/* Budget impact */}
        <div className="rounded-md bg-zinc-800/60 p-2 text-xs text-zinc-300">
          estimated cost <span className="font-mono">${estimatedCostUsd.toFixed(2)}</span>
          {remainingAfter !== null && (
            <> · remaining after <span className="font-mono">${remainingAfter.toFixed(2)}</span>
              {budget && <> of ${budget.cap_usd.toFixed(0)} cap</>}</>
          )}
        </div>

        <label className="block text-xs text-zinc-400">
          Approver: <span className="font-mono text-zinc-200">{currentUserEmail}</span>
        </label>

        <label className="block text-xs text-zinc-400">
          Role
          <select
            aria-label="role"
            className="mt-1 w-full bg-zinc-800 rounded px-2 py-1 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="">Select role…</option>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>

        <label className="block text-xs text-zinc-400">
          Rationale
          <textarea
            aria-label="rationale"
            className="mt-1 w-full bg-zinc-800 rounded px-2 py-1 text-sm"
            rows={3}
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
        </label>

        <label className="flex items-center gap-2 text-xs text-zinc-400">
          <input type="checkbox" checked={riskAccepted}
                 onChange={(e) => setRiskAccepted(e.target.checked)} />
          accept risk (required for waive)
        </label>

        <div className="flex justify-end gap-2 pt-1">
          <button
            className="px-3 py-1.5 text-sm rounded bg-zinc-700 disabled:opacity-40"
            disabled={!canDecide || submitting}
            onClick={() => decide("rejected")}
          >
            Reject
          </button>
          <button
            className="px-3 py-1.5 text-sm rounded bg-amber-700 disabled:opacity-40"
            disabled={!canDecide || !riskAccepted || submitting}
            onClick={() => decide("waived_with_risk")}
          >
            Waive (risk)
          </button>
          <button
            className="px-3 py-1.5 text-sm rounded bg-emerald-700 disabled:opacity-40"
            disabled={!canDecide || submitting}
            onClick={() => decide("approved")}
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
