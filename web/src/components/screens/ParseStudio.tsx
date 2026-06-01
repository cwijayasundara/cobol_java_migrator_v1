"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Play, CheckCircle2, AlertTriangle, ArrowRight, Network } from "lucide-react";
import { api, type ParseResultSummary, type GraphSummary } from "@/lib/api";

// Parse stage: run the deterministic COBOL extractor on the workspace's repo and
// ingest it into Neo4j (no LLM). On success the Graph stage is populated, and a
// "Next: Graph" button takes you straight to the code graph. If the repo was
// already parsed in a previous session, that button shows up front too.
export function ParseStudio({ workspaceId }: { workspaceId: string }) {
  const [result, setResult] = useState<ParseResultSummary | null>(null);
  const [summary, setSummary] = useState<GraphSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  // On load, check whether a graph already exists for this repo (parsed earlier).
  useEffect(() => {
    api.getGraphSummary(workspaceId).then(setSummary).catch(() => setSummary(null));
  }, [workspaceId]);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.parseWorkspace(workspaceId);
      setResult(r);
      setSummary({ repo_slug: r.repo_slug, entities: r.entities,
                   relationships: r.relationships, by_kind: {} });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const parsed = (summary?.entities ?? 0) > 0;

  const nextGraph = (
    <Link
      href={`/workspaces/${workspaceId}/journey/graph`}
      className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600"
    >
      Next: Graph <ArrowRight className="w-4 h-4" />
    </Link>
  );

  return (
    <div className="p-4 space-y-4 max-w-2xl">
      <div>
        <h3 className="text-sm font-medium text-zinc-300">Parse</h3>
        <p className="text-xs text-zinc-500 mt-1">
          Runs the ProLeap COBOL extractor on this repository and ingests the code
          graph (programs, paragraphs, data items, READS/WRITES/CALLS) into Neo4j.
          Deterministic — no LLM. Populates the Graph stage.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={run}
          disabled={running}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40"
        >
          <Play className="w-4 h-4" />
          {running ? "Parsing…" : parsed ? "Re-parse" : "Run parse"}
        </button>
        {/* available without re-parsing once a graph exists */}
        {parsed && !result && nextGraph}
      </div>

      {/* already parsed in a previous session */}
      {parsed && !result && (
        <div className="flex items-center gap-2 text-xs text-zinc-400">
          <Network className="w-3.5 h-3.5 text-indigo-400" />
          Graph already in Neo4j — {summary!.entities} entities, {summary!.relationships} relationships.
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">Parse failed</div>
            <div className="mt-1 font-mono break-all">{error}</div>
          </div>
        </div>
      )}

      {result && (
        <div className="rounded-md border border-emerald-900 bg-emerald-950/30 p-4 text-sm space-y-3">
          <div className="flex items-center gap-2 text-emerald-300">
            <CheckCircle2 className="w-4 h-4" />
            <span className="font-medium">Parsed {result.repo_slug} → ingested into Neo4j</span>
          </div>
          <ul className="text-xs text-zinc-300 grid grid-cols-2 gap-x-6 gap-y-1 font-mono">
            <li>programs: {result.programs}</li>
            <li>copybooks: {result.copybooks}</li>
            <li>entities: {result.entities}</li>
            <li>relationships: {result.relationships}</li>
            <li className={result.parse_errors ? "text-amber-400" : ""}>
              parse errors: {result.parse_errors}
            </li>
          </ul>
          {nextGraph}
        </div>
      )}
    </div>
  );
}
