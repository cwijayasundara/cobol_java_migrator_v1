"use client";

import { useState } from "react";
import { Hammer, Play, AlertTriangle, FlaskConical, FileCode2, Boxes } from "lucide-react";
import { api, type BuildResult } from "@/lib/api";
import { useJob } from "@/lib/useJob";
import { StoryBuildLab } from "@/components/screens/StoryBuildLab";

// Build stage: TDD codegen for a writer slice grounded in the parsed graph (JUnit
// tests first, then minimal Spring Boot code), scaffolded into a Maven module with
// the four quality gates. Uses Claude — a multi-minute run, so the POST starts a
// background job and we poll for the result. Run Blueprint first (the BRD is the
// codegen brief). Compiling + running the gates (mvn verify) is a downstream step.
//
// Two modes via a small in-screen toggle (kept here rather than a new route so the
// Build stage stays a single screen): the legacy single-slice codegen, and the
// per-story codegen loop (StoryBuildLab) over the deterministic story DAG.
export function BuildLab({ workspaceId }: { workspaceId: string }) {
  const [mode, setMode] = useState<"slice" | "story">("slice");

  const { result, error, busy, run } = useJob<BuildResult>(
    () => api.startBuild(workspaceId),
    () => api.getBuildStatus(workspaceId),
    5000,
    30000,
  );

  const toggle = (
    <div className="flex items-center gap-1 text-xs">
      <button
        onClick={() => setMode("story")}
        className={`inline-flex items-center gap-1 px-2 py-1 rounded ${mode === "story" ? "bg-indigo-700 text-white" : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"}`}>
        <Boxes className="w-3.5 h-3.5" />Story build
      </button>
      <button
        onClick={() => setMode("slice")}
        className={`inline-flex items-center gap-1 px-2 py-1 rounded ${mode === "slice" ? "bg-indigo-700 text-white" : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"}`}>
        <Hammer className="w-3.5 h-3.5" />Single slice
      </button>
    </div>
  );

  if (mode === "story") {
    return (
      <div className="p-4 max-w-3xl">
        <div className="mb-2">{toggle}</div>
        <StoryBuildLab workspaceId={workspaceId} />
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      {toggle}
      <div className="flex items-center gap-2">
        <Hammer className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Build (TDD codegen)</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Generates a Java slice from the graph — JUnit tests first, then minimal Spring
        Boot code — scaffolded into a Maven module with ArchUnit, SpotBugs, Error Prone
        and Checkstyle wired. Uses Claude; run Blueprint first.
      </p>
      <button onClick={run} disabled={busy}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
        <Play className="w-4 h-4" />{busy ? "Generating… (this takes a minute)" : "Generate code"}
      </button>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error}</span>
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <div className="flex items-center gap-3 text-xs">
            <span className="font-mono text-zinc-200">{result.module}</span>
            <span className="text-zinc-500">{result.base_package}</span>
            <span className="text-emerald-400">{result.tests} test{result.tests === 1 ? "" : "s"}</span>
            <span className="text-zinc-400">{result.mains} main</span>
          </div>
          <p className="text-xs text-zinc-600">
            scaffolded at <span className="font-mono">{result.scaffold_path}</span> — run
            <span className="font-mono"> mvn verify</span> there for the quality gates.
          </p>
          <ul className="space-y-1">
            {result.files.map((f) => (
              <li key={f.path} className="flex items-center gap-2 text-xs border-b border-zinc-900 py-1.5">
                {f.kind === "test"
                  ? <FlaskConical className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  : <FileCode2 className="w-3.5 h-3.5 text-indigo-400 shrink-0" />}
                <span className="font-mono text-zinc-300 break-all">{f.path}</span>
                {f.evidence.length > 0 && (
                  <span className="text-zinc-600">← {f.evidence.join(", ")}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
