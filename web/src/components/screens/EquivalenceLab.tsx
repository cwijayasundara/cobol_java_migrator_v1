"use client";

import { useState } from "react";
import { Scale, Play, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { api, type VerifyResult } from "@/lib/api";

// Verify stage: deterministic COBOL↔Java equivalence. Diffs a candidate (generated
// Java) record set against a golden master (the COBOL oracle) with COBOL-aware
// tolerance, linking each mismatch back to its source seam in the graph. No LLM.
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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true); setError(null);
    try {
      const body = {
        program, record, record_key: recordKey,
        golden_records: JSON.parse(golden),
        candidate_records: JSON.parse(candidate),
        tolerance_yaml: tolerance || undefined,
        dialect: "cobc 3.2 (ibm-strict, ASCII)",
      };
      setResult(await api.runVerify(workspaceId, body));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const field = (label: string, value: string, set: (v: string) => void) => (
    <label className="flex flex-col gap-1 text-xs text-zinc-500">
      {label}
      <input value={value} onChange={(e) => set(e.target.value)}
        className="rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-zinc-200 font-mono" />
    </label>
  );

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Scale className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Equivalence (Verify)</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Field-aware diff of generated-Java output against the COBOL golden master,
        with COMP-3 / scale &amp; date tolerance. Mismatches link back to the source
        seam in the graph. Deterministic (no LLM). Supply both record sets below.
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
