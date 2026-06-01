"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Boxes, FolderGit2, Plus } from "lucide-react";
import { api, type RepoInfo } from "@/lib/api";
import type { Workspace, Budget } from "@/lib/types";

const ME = "cwijay@biz2bricks.ai";

export function PortfolioDashboard() {
  const [rows, setRows] = useState<{ ws: Workspace; budget: Budget | null }[]>([]);
  const [repos, setRepos] = useState<RepoInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState<string | null>(null);

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
      setRepos(await api.listRepos().catch(() => []));
      setLoading(false);
    })();
  }, []);

  const wsBySlug = new Map(rows.map((r) => [r.ws.repo_slug, r.ws]));

  const createForRepo = async (repo: RepoInfo) => {
    setCreating(repo.slug);
    const ws = await api
      .createWorkspace({ name: repo.name, repo_slug: repo.slug, created_by: ME })
      .catch(() => null);
    if (ws) setRows((prev) => [...prev, { ws, budget: null }]);
    setCreating(null);
  };

  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-800 bg-zinc-900/50 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-3">
          <Boxes className="w-6 h-6 text-indigo-400" />
          <h1 className="text-xl font-semibold">Modernization Cockpit</h1>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-6 py-8 space-y-10">
        <section>
          <h2 className="text-lg font-medium mb-4 text-zinc-300">
            Workspaces ({rows.length})
          </h2>
          {loading ? (
            <div className="text-zinc-500 text-sm">Loading...</div>
          ) : rows.length === 0 ? (
            <div className="text-zinc-500 text-sm">
              No workspaces yet — pick a repository below to start one.
            </div>
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
        </section>

        <section>
          <div className="flex items-center gap-2 mb-1">
            <FolderGit2 className="w-4 h-4 text-indigo-400" />
            <h2 className="text-lg font-medium text-zinc-300">Available repositories</h2>
          </div>
          <p className="text-xs text-zinc-500 mb-4">
            COBOL repos discovered under <span className="font-mono">source_code_to_analyse/</span>.
            Pick one to start (or open) its migration — no default repo.
          </p>
          {!loading && repos.length === 0 ? (
            <div className="text-zinc-500 text-sm">
              No COBOL repos found. Drop a repo under{" "}
              <span className="font-mono">source_code_to_analyse/</span> and refresh.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {repos.map((repo) => {
                const existing = wsBySlug.get(repo.slug);
                return (
                  <div
                    key={repo.slug}
                    className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col gap-2"
                  >
                    <div className="font-mono text-sm">{repo.name}</div>
                    <div className="text-xs text-zinc-500">
                      {repo.programs} programs · {repo.copybooks} copybooks
                    </div>
                    {existing ? (
                      <Link
                        href={`/workspaces/${existing.id}/journey/outcome`}
                        className="mt-1 inline-flex items-center justify-center px-3 py-1.5 text-sm rounded bg-zinc-700 hover:bg-zinc-600"
                      >
                        Open workspace →
                      </Link>
                    ) : (
                      <button
                        className="mt-1 inline-flex items-center justify-center gap-1 px-3 py-1.5 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40"
                        disabled={creating === repo.slug}
                        onClick={() => createForRepo(repo)}
                      >
                        <Plus className="w-3.5 h-3.5" />
                        {creating === repo.slug ? "Creating…" : "Create workspace"}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
