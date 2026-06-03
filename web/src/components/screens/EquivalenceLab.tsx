"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Scale, Play, AlertTriangle, CheckCircle2, XCircle, Wrench, Hourglass, Crosshair,
} from "lucide-react";
import {
  api,
  type VerifyResult, type VerifyReport, type PerStoryVerdict, type VerifyRequest,
} from "@/lib/api";

// Verify stage: COBOL↔Java equivalence over the deterministic equivalence engine,
// now a Fan-Out-and-Synthesize workflow — one equivalence check PER backlog story
// (each story cites different COBOL seams), a soft per-story timeout (overrun ->
// PARTIAL, never a hard kill), and a decompose-further loop that LOCALIZES which
// program/COBOL-context sub-slice of a failing story actually failed. The verdict is
// persisted as a versioned report, so it survives a refresh (lazy-loaded on mount).
// Golden masters aren't pre-captured for these repos, so both record sets are
// supplied here (honest provenance). Pre-filled with a demo precision mismatch.
const DEMO_GOLDEN = JSON.stringify([{ "ID": "1", "BAL": "1234.56" }], null, 2);
const DEMO_CANDIDATE = JSON.stringify([{ "ID": "1", "BAL": "1234.50" }], null, 2);
const DEMO_TOLERANCE =
  "record: ACCT-RECORD\ndefault:\n  matcher: exact\nrules:\n  - field: BAL\n    matcher: numeric_scale\n    scale: 2";

export function EquivalenceLab({ workspaceId }: { workspaceId: string }) {
  const [program, setProgram] = useState("CBPOST1M");
  const [record, setRecord] = useState("ACCT-RECORD");
  const [recordKey, setRecordKey] = useState("ID");
  const [golden, setGolden] = useState(DEMO_GOLDEN);
  const [candidate, setCandidate] = useState(DEMO_CANDIDATE);
  const [tolerance, setTolerance] = useState(DEMO_TOLERANCE);
  const [result, setResult] = useState<VerifyResult | null>(null);
  // The latest persisted verify_report (lazy-loaded on mount; idle when none).
  const [report, setReport] = useState<VerifyReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [repairing, setRepairing] = useState<string | null>(null);

  // Build the VerifyRequest body from the current form (shared by run + repair).
  const buildBody = useCallback((): VerifyRequest => ({
    program, record, record_key: recordKey,
    golden_records: JSON.parse(golden),
    candidate_records: JSON.parse(candidate),
    tolerance_yaml: tolerance || undefined,
    dialect: "cobc 3.2 (ibm-strict, ASCII)",
  }), [program, record, recordKey, golden, candidate, tolerance]);

  // Lazy-load: replay the latest persisted verdict so it survives a refresh. Idle
  // (or a 404 before any run) leaves the screen in its blank "run me" state.
  const refresh = useCallback(async () => {
    try {
      const job = await api.getVerifyStatus(workspaceId);
      setReport(job.status === "done" ? job.result : null);
    } catch {
      setReport(null); // no persisted run yet — stay idle, never block the screen.
    }
  }, [workspaceId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const run = async () => {
    setBusy(true); setError(null);
    try {
      const res = await api.runVerify(workspaceId, buildBody());
      setResult(res);
      await refresh(); // pull the freshly-persisted report (per-story verdicts).
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Repair ONE failing story's Java (red->green), then re-pull the persisted report.
  const repair = async (storyId: string) => {
    setRepairing(storyId); setError(null);
    try {
      await api.repairVerifyStory(workspaceId, storyId, buildBody());
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRepairing(null);
    }
  };

  const field = (label: string, value: string, set: (v: string) => void) => (
    <label className="flex flex-col gap-1 text-xs text-zinc-500">
      {label}
      <input value={value} onChange={(e) => set(e.target.value)}
        className="rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-zinc-200 font-mono" />
    </label>
  );

  // Per-story verdicts come from the persisted report (lazy-loaded) and are also
  // present on a fresh POST result — prefer the persisted report (survives refresh).
  const perStory: PerStoryVerdict[] =
    report?.per_story_verdicts ?? result?.per_story_verdicts ?? [];

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Scale className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Equivalence (Verify)</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Field-aware diff of generated-Java output against the COBOL golden master,
        with COMP-3 / scale &amp; date tolerance. Fans out one equivalence check per
        backlog story, decomposes a failing story to localize which sub-slice failed,
        and persists a versioned verdict (survives a refresh). Supply both record sets.
      </p>

      <div className="grid grid-cols-3 gap-3">
        {field("Program", program, setProgram)}
        {field("Record", record, setRecord)}
        {field("Key field", recordKey, setRecordKey)}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-xs text-zinc-500">Golden (COBOL oracle) — JSON
          <textarea value={golden} onChange={(e) => setGolden(e.target.value)}
            className="h-28 rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-zinc-200 font-mono text-xs" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-zinc-500">Candidate (Java) — JSON
          <textarea value={candidate} onChange={(e) => setCandidate(e.target.value)}
            className="h-28 rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-zinc-200 font-mono text-xs" />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs text-zinc-500">Tolerance ruleset (YAML)
        <textarea value={tolerance} onChange={(e) => setTolerance(e.target.value)}
          className="h-24 rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-zinc-200 font-mono text-xs" />
      </label>

      <button onClick={run} disabled={busy}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
        <Play className="w-4 h-4" />{busy ? "Comparing…" : "Run equivalence"}
      </button>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error}</span>
        </div>
      )}

      {/* Persisted verdict (lazy-loaded on mount) — survives a refresh. */}
      {report && (
        <div className="space-y-2 rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            {report.verdict === "pass"
              ? <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-4 h-4" />pass</span>
              : <span className="flex items-center gap-1 text-red-400"><XCircle className="w-4 h-4" />fail</span>}
            {report.version != null && (
              <span className="text-xs text-zinc-500 font-mono">v{report.version}</span>
            )}
            <span className="text-xs text-zinc-500">
              {report.records_compared ?? 0} compared · {report.defect_count ?? 0} defect
              {report.defect_count === 1 ? "" : "s"}
            </span>
            <span className="text-xs text-zinc-600">latest persisted report</span>
          </div>
          {(report.open_questions ?? []).map((q) => (
            <p key={q} className="text-xs text-amber-400">{q}</p>
          ))}

          {perStory.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-medium text-indigo-300">per-story verdicts</div>
              <ul className="space-y-1">
                {perStory.map((p) => {
                  const failingSubs =
                    p.failing_subslices ??
                    (p.subslices ?? []).filter((s) => !s.ok).map((s) => s.subslice);
                  return (
                    <li key={p.story_id}
                      className="flex flex-col gap-1 border-b border-zinc-900 py-2 text-xs">
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="font-mono text-zinc-200">{p.story_id}</span>
                        {p.ok
                          ? <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" />pass</span>
                          : <span className="flex items-center gap-1 text-red-400"><XCircle className="w-3.5 h-3.5" />fail</span>}
                        {p.partial && (
                          <span className="flex items-center gap-1 text-amber-300">
                            <Hourglass className="w-3.5 h-3.5" />partial (timeout)
                          </span>
                        )}
                        <span className="text-zinc-500">
                          {p.defect_count ?? 0} defect{p.defect_count === 1 ? "" : "s"}
                        </span>
                        {!p.ok && (
                          <button
                            onClick={() => repair(p.story_id)}
                            disabled={repairing != null}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-200 disabled:opacity-40">
                            <Wrench className="w-3.5 h-3.5" />
                            {repairing === p.story_id ? "Repairing…" : "Repair"}
                          </button>
                        )}
                      </div>
                      {/* Decompose-further localization: which program/context sub-slice failed. */}
                      {failingSubs.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2 text-zinc-500">
                          <Crosshair className="w-3.5 h-3.5 text-red-400" />
                          <span>failing sub-slice{failingSubs.length === 1 ? "" : "s"}:</span>
                          {failingSubs.map((s) => (
                            <span key={s} className="font-mono text-red-400">{s}</span>
                          ))}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="space-y-2">
          <div className="flex items-center gap-3 text-sm">
            {result.verdict === "pass"
              ? <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-4 h-4" />pass</span>
              : <span className="flex items-center gap-1 text-red-400"><XCircle className="w-4 h-4" />fail</span>}
            <span className="text-xs text-zinc-500">
              {result.records_compared} compared · {result.defect_count} defect{result.defect_count === 1 ? "" : "s"}
            </span>
          </div>
          {result.open_questions.map((q) => (
            <p key={q} className="text-xs text-amber-400">{q}</p>
          ))}
          {result.defects.length > 0 && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-zinc-500 border-b border-zinc-800">
                  <th className="py-1">Field</th><th>Reason</th><th>Source seam</th><th>Severity</th>
                </tr>
              </thead>
              <tbody>
                {result.defects.map((d, i) => (
                  <tr key={i} className="border-b border-zinc-900">
                    <td className="py-1 font-mono text-zinc-300">{d.field}</td>
                    <td className="text-zinc-400">{d.reason}</td>
                    <td className="font-mono text-zinc-400">{d.source_seam}{d.seam_edge_kind ? ` (${d.seam_edge_kind})` : ""}</td>
                    <td className={d.severity === "high" ? "text-red-400" : "text-amber-400"}>{d.severity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
