"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Workspace } from "@/lib/types";

// Phase 0: register a repository for ingest. Ingest/parse run server-side in
// FastAPI; this form only posts the intake request.
export function RepositoryIntake({ workspaceId }: { workspaceId: string }) {
  const [name, setName] = useState("");
  const [repoSlug, setRepoSlug] = useState("");
  const [created, setCreated] = useState<Workspace | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    const ws = await api
      .createWorkspace({ name, repo_slug: repoSlug, created_by: "cwijay@biz2bricks.ai" })
      .catch(() => null);
    setCreated(ws);
    setSubmitting(false);
  };

  return (
    <div className="p-4 space-y-3 max-w-md">
      <h3 className="text-sm font-medium text-zinc-300">Repository Intake</h3>
      <p className="text-xs text-zinc-500">
        Register a COBOL repository; parsing + graph ingestion run in the control plane.
      </p>
      <label className="block text-xs text-zinc-400">
        Name
        <input
          aria-label="name"
          className="mt-1 w-full bg-zinc-800 rounded px-2 py-1 text-sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label className="block text-xs text-zinc-400">
        Repo slug
        <input
          aria-label="repo slug"
          className="mt-1 w-full bg-zinc-800 rounded px-2 py-1 text-sm font-mono"
          value={repoSlug}
          onChange={(e) => setRepoSlug(e.target.value)}
        />
      </label>
      <button
        className="px-3 py-1.5 text-sm rounded bg-indigo-700 disabled:opacity-40"
        disabled={submitting || name === "" || repoSlug === ""}
        onClick={submit}
      >
        Register
      </button>
      {created && (
        <div className="text-xs text-emerald-400">Registered {created.name} ({created.repo_slug})</div>
      )}
    </div>
  );
}
