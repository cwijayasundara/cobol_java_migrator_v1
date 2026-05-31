"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Boxes } from "lucide-react";
import { api } from "@/lib/api";
import type { Workspace, Budget } from "@/lib/types";

export function PortfolioDashboard() {
  const [rows, setRows] = useState<{ ws: Workspace; budget: Budget | null }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const workspaces = await api.listWorkspaces();
      const withBudget = await Promise.all(
        workspaces.map(async (ws) => ({
          ws,
          budget: await api.getWorkspaceBudget(ws.id).catch(() => null),
        })),
      );
      setRows(withBudget);
      setLoading(false);
    })();
  }, []);

  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-800 bg-zinc-900/50 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-3">
          <Boxes className="w-6 h-6 text-indigo-400" />
          <h1 className="text-xl font-semibold">Modernization Cockpit</h1>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-6 py-8">
        <h2 className="text-lg font-medium mb-4 text-zinc-300">
          Workspaces ({rows.length})
        </h2>
        {loading ? (
          <div className="text-zinc-500 text-sm">Loading...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {rows.map(({ ws, budget }) => (
              <Link
                key={ws.id}
                href={`/workspaces/${ws.id}/journey/outcome`}
                className="block rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 hover:border-indigo-600"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{ws.name}</span>
                  {budget && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-200">
                      ${budget.spent_usd.toFixed(2)} / ${budget.cap_usd.toFixed(0)}
                    </span>
                  )}
                </div>
                <div className="text-xs text-zinc-500 mt-1 font-mono">{ws.repo_slug}</div>
                <div className="text-xs text-zinc-600 mt-2">by {ws.created_by}</div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
