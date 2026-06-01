"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Boxes, FileCode2, Library, ArrowRight, AlertTriangle } from "lucide-react";
import { api, type RepoInfo } from "@/lib/api";

// Intake stage: a read-only summary of the COBOL repository this workspace
// migrates (name/slug/path + program & copybook counts from GET /repos), with a
// "Next: Parse" link to start the actual work. The repo was already selected in
// the Portfolio, so this stage just confirms it before parsing.
export function RepositoryIntake(
  { workspaceId, repoSlug }: { workspaceId: string; repoSlug: string },
) {
  const [repo, setRepo] = useState<RepoInfo | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.listRepos()
      .then((repos) => setRepo(repos.find((r) => r.slug === repoSlug) ?? null))
      .catch(() => setRepo(null))
      .finally(() => setLoaded(true));
  }, [repoSlug]);

  return (
    <div className="p-4 space-y-4 max-w-md">
      <div className="flex items-center gap-2">
        <Boxes className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Repository</h3>
      </div>
      <p className="text-xs text-zinc-500">
        The COBOL repository this workspace migrates. Parsing + graph ingestion run next.
      </p>

      {!loaded && <p className="text-xs text-zinc-500">Loading…</p>}

      {loaded && !repo && (
        <div className="flex items-start gap-2 rounded-md border border-amber-900 bg-amber-950/40 p-3 text-xs text-amber-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>
            <span className="font-mono">{repoSlug}</span> isn’t a folder under{" "}
            <span className="font-mono">source_code_to_analyse/</span>. Pick a discovered
            repo from the Portfolio, or add the folder and reload.
          </span>
        </div>
      )}

      {repo && (
        <div className="rounded-md border border-zinc-800 p-3 space-y-1.5 text-sm">
          <div className="text-zinc-200">{repo.name}</div>
          <div className="text-xs text-zinc-500 font-mono">{repo.slug}</div>
          <div className="text-xs text-zinc-600 font-mono break-all">{repo.path}</div>
          <div className="flex gap-4 text-xs pt-1">
            <span className="flex items-center gap-1 text-zinc-400">
              <FileCode2 className="w-3.5 h-3.5" />{repo.programs} programs
            </span>
            <span className="flex items-center gap-1 text-zinc-400">
              <Library className="w-3.5 h-3.5" />{repo.copybooks} copybooks
            </span>
          </div>
        </div>
      )}

      <Link
        href={`/workspaces/${workspaceId}/journey/parse`}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600"
      >
        Next: Parse <ArrowRight className="w-4 h-4" />
      </Link>
    </div>
  );
}
