"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Boxes, Play, PlayCircle, RefreshCw, AlertTriangle, CheckCircle2,
  FlaskConical, CircleDashed, ShieldQuestion, Ban, Hourglass,
} from "lucide-react";
import {
  api,
  type StoryCodegenPlan, type StoryCodegenItem,
  type StoryStatusRecord, type StoryStatusResponse,
  type StoryBuildCounts,
} from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Story-sliced codegen view (Tasks 1-7). Surfaces the deterministic story DAG
// (GET .../build/story-plan) merged with the richer persisted per-story telemetry
// (GET .../build/stories), and buttons to drive the background build jobs.
//
// `generated-unverified` (mvn/JDK absent on the host) is rendered DISTINCTLY in
// amber so it reads as "generated but not test-verified", NOT as a real pass
// (green) / failure (red) / blocked (grey). One status→style source of truth below.

type StatusStyle = { label: string; dot: string; text: string; Icon: typeof CheckCircle2; pulse?: boolean };

// Single source of truth for status → colour mapping.
function statusStyle(raw?: string): StatusStyle {
  switch ((raw ?? "pending").toLowerCase()) {
    case "passed":
      return { label: "passed", dot: "bg-emerald-500", text: "text-emerald-400", Icon: CheckCircle2 };
    case "failed":
      return { label: "failed", dot: "bg-red-500", text: "text-red-400", Icon: AlertTriangle };
    case "generated-unverified":
      return { label: "generated-unverified", dot: "bg-amber-500", text: "text-amber-400", Icon: ShieldQuestion };
    case "deferred":
      // Distinct from passed/failed/generated-unverified/blocked: a story that
      // exhausted its repeat-until-done attempt budget. Tolerated (pass-with-deferred),
      // never wedges the build — slate fill with an amber outline so it reads as
      // "set aside, retryable", NOT a real pass / hard failure / blocked.
      return { label: "deferred", dot: "bg-slate-500 ring-1 ring-amber-400", text: "text-amber-300", Icon: Hourglass };
    case "blocked":
      return { label: "blocked", dot: "bg-zinc-600", text: "text-zinc-400", Icon: Ban };
    case "running":
      return { label: "running", dot: "bg-indigo-500", text: "text-indigo-400", Icon: RefreshCw, pulse: true };
    case "skipped":
      return { label: "skipped", dot: "bg-zinc-700", text: "text-zinc-600", Icon: CircleDashed };
    case "pending":
    default:
      return { label: "pending", dot: "bg-zinc-700", text: "text-zinc-500", Icon: CircleDashed };
  }
}

// A dep is "satisfied" once it has produced code, verified or not.
const SATISFIED = new Set(["passed", "generated-unverified", "skipped"]);

// Derive each story's dependency WAVE from its `depends_on` (the plan already carries
// the DAG). wave 0 = no deps; wave k = 1 + max(dep waves). The build runs stories in
// these waves (Fan-Out-and-Synthesize), so grouping the table by wave mirrors how the
// engine actually schedules them. Returns story_id -> wave index. Defensive against a
// missing/cyclic dep (treated as wave 0) so a bad plan can never hang the render.
function deriveWaves(items: StoryCodegenItem[]): Record<string, number> {
  const byId = new Map(items.map((i) => [i.story_id, i]));
  const wave: Record<string, number> = {};
  const visiting = new Set<string>();
  const waveOf = (id: string): number => {
    if (wave[id] != null) return wave[id];
    const item = byId.get(id);
    if (!item || visiting.has(id) || item.depends_on.length === 0) {
      return (wave[id] = 0);
    }
    visiting.add(id);
    const w = 1 + Math.max(...item.depends_on.map((d) => waveOf(d)));
    visiting.delete(id);
    return (wave[id] = w);
  };
  for (const i of items) waveOf(i.story_id);
  return wave;
}

// Pull the gate's progress counts off the (possibly nested) job result. run_story_build
// returns { ...envelope, result: { pass_count, deferred_count, pending, story_count } },
// so prefer the nested counts and fall back to the envelope. All best-effort.
function extractCounts(result: StoryBuildCounts & { result?: StoryBuildCounts } | null | undefined):
  StoryBuildCounts | null {
  if (!result) return null;
  const inner = result.result ?? result;
  if (inner.pass_count == null && inner.deferred_count == null && inner.pending == null) {
    return null;
  }
  return inner;
}

function testResultLabel(result: StoryStatusRecord["test_result"]): string | null {
  if (!result) return null;
  if (typeof result === "string") return result;
  return result.status ?? null;
}

export function StoryBuildLab({ workspaceId }: { workspaceId: string }) {
  const [plan, setPlan] = useState<StoryCodegenPlan | null>(null);
  const [statuses, setStatuses] = useState<StoryStatusResponse["stories"]>({});
  const [counts, setCounts] = useState<StoryBuildCounts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [perStoryBusy, setPerStoryBusy] = useState(false);

  // Fetch the deterministic plan + persisted telemetry. Defensive: either may 404
  // before the stage has run; leave the screen in manual mode on failure.
  const refresh = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([
        api.getStoryPlan(workspaceId),
        api.getStoryStatuses(workspaceId).catch(() => null),
      ]);
      setPlan(p);
      if (s) {
        setStatuses(s.stories ?? {});
        setCounts(extractCounts(s.job?.result));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [workspaceId]);

  useEffect(() => { void refresh(); }, [refresh]);

  // Build-all: poll only the lightweight story-status endpoint while the job runs.
  // The story plan is static for this screen, so re-fetch it only when the job
  // settles; otherwise the backend logs get cluttered by duplicate plan polls.
  const buildAll = useJob(
    () => api.startStoryBuild(workspaceId),
    async () => {
      const s = await api.getStoryStatuses(workspaceId);
      setStatuses(s.stories ?? {});
      setCounts(extractCounts(s.job?.result));
      if (s.job.status !== "running") {
        void refresh();
      }
      return { status: s.job.status, result: s.job.result, error: s.job.error };
    },
    5000,
    20000,
    1.6,
  );

  // Dependency waves derived from the plan DAG (wave 0 = no deps; wave k = deps in
  // earlier waves). The build engine fans these out wave-by-wave, so we group the
  // rendered stories the same way.
  const waves = deriveWaves(plan?.items ?? []);

  // Merge plan item status with the (superseding) persisted status map by story_id,
  // carrying each story's wave index so we can group the table by wave below.
  const merged = (plan?.items ?? []).map((item) => {
    const rec: StoryStatusRecord = statuses[item.story_id] ?? {};
    const status = rec.status ?? item.status;
    return { item, rec, status, wave: waves[item.story_id] ?? 0 };
  });

  // Group the merged rows by wave index, preserving plan order within each wave.
  const waveGroups = Array.from(
    merged.reduce((acc, row) => {
      (acc.get(row.wave) ?? acc.set(row.wave, []).get(row.wave)!).push(row);
      return acc;
    }, new Map<number, typeof merged>()),
  ).sort((a, b) => a[0] - b[0]);

  const statusOf = (id: string): string =>
    statuses[id]?.status ?? plan?.items.find((i) => i.story_id === id)?.status ?? "pending";

  // The next ready story: own status pending/failed/deferred (deferred = exhausted its
  // budget last run, still retryable) AND every dep satisfied.
  const nextReady = (): StoryCodegenItem | undefined =>
    (plan?.items ?? []).find((i) => {
      const st = (statusOf(i.story_id) || "").toLowerCase();
      const ready = st === "pending" || st === "failed" || st === "deferred";
      const depsOk = i.depends_on.every((d) => SATISFIED.has(statusOf(d).toLowerCase()));
      return ready && depsOk;
    });

  const buildOne = async (storyId: string) => {
    setPerStoryBusy(true); setError(null);
    try {
      await api.startStory(workspaceId, storyId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPerStoryBusy(false);
    }
  };

  const busy = buildAll.busy || perStoryBusy;
  const next = nextReady();
  // A failed story is retryable via the same per-story POST.
  const firstFailed = (plan?.items ?? []).find(
    (i) => (statusOf(i.story_id) || "").toLowerCase() === "failed",
  );

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Boxes className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Story build (per-story codegen)</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Drives the per-story codegen loop over the deterministic story DAG. Each story
        is scaffolded from the technical design + BRD, patched test-first, then run.
        <span className="text-amber-400"> generated-unverified</span> means the code was
        generated but the toolchain (mvn/JDK) was absent — not a test failure.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => next && buildOne(next.story_id)}
          disabled={busy || !next}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
          <Play className="w-4 h-4" />
          {next ? `Build next ready story (${next.story_id})` : "Build next ready story"}
        </button>
        <button
          onClick={buildAll.run}
          disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
          <PlayCircle className="w-4 h-4" />
          {buildAll.busy ? "Building all…" : "Build all ready stories"}
        </button>
        <button
          onClick={() => firstFailed && buildOne(firstFailed.story_id)}
          disabled={busy || !firstFailed}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40">
          <RefreshCw className="w-4 h-4" />Retry failed story
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error}</span>
        </div>
      )}
      {buildAll.error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{buildAll.error}</span>
        </div>
      )}

      {plan && (
        <div className="space-y-2">
          <div className="text-xs text-zinc-500">
            {plan.repo_slug} · plan v{plan.version} · {plan.items.length} stor
            {plan.items.length === 1 ? "y" : "ies"} · {waveGroups.length} wave
            {waveGroups.length === 1 ? "" : "s"}
          </div>

          {/* Build progress counts (pass-with-deferred): built / deferred / pending of
              total, from the gate's `story_counts`. Only shown once a build has run. */}
          {counts && (
            <div className="flex flex-wrap items-center gap-3 rounded-md border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-xs">
              <span className="text-emerald-400">built {counts.pass_count ?? 0}</span>
              <span className="text-sky-300">rerun {counts.rebuilt_count ?? counts.pass_count ?? 0}</span>
              <span className="text-zinc-400">cache hits {counts.cache_hit_count ?? counts.skipped_count ?? 0}</span>
              <span className="text-amber-300">deferred {counts.deferred_count ?? 0}</span>
              <span className="text-zinc-400">pending {counts.pending ?? 0}</span>
              <span className="text-zinc-500">of {counts.story_count ?? plan.items.length} total</span>
            </div>
          )}

          {waveGroups.map(([waveIdx, rows]) => (
          <div key={waveIdx} className="space-y-1">
            <div className="flex items-center gap-2 pt-1 text-xs font-medium text-indigo-300">
              <Boxes className="w-3.5 h-3.5" />
              Wave {waveIdx}
              <span className="text-zinc-600 font-normal">
                ({rows.length} stor{rows.length === 1 ? "y" : "ies"})
              </span>
            </div>
          <ol className="space-y-1">
            {rows.map(({ item, rec, status }) => {
              const st = statusStyle(status);
              const { Icon } = st;
              const testStatus = testResultLabel(rec.test_result);
              return (
                <li key={item.story_id} className="flex flex-col gap-1 border-b border-zinc-900 py-2">
                  <div className="flex flex-wrap items-baseline gap-3 text-sm">
                    <span className="font-mono text-zinc-200">{item.story_id}</span>
                    <span className="text-xs text-zinc-400">{item.bounded_context}</span>
                    <span className="text-xs text-zinc-600 font-mono">{item.service_name}</span>
                    <span className={`inline-flex items-center gap-1 text-xs ${st.text}`}>
                      <span className={`w-2 h-2 rounded-full ${st.dot} ${st.pulse ? "animate-pulse" : ""}`} />
                      <Icon className={`w-3.5 h-3.5 ${st.pulse ? "animate-spin" : ""}`} />
                      {st.label}
                    </span>
                    {status.toLowerCase() === "running" && (rec.phase_label || rec.phase) && (
                      <span className="text-xs text-indigo-300">
                        {rec.phase_label ?? rec.phase}
                      </span>
                    )}
                    {item.depends_on.length > 0 && (
                      <span className="text-xs text-zinc-500">after {item.depends_on.join(", ")}</span>
                    )}
                  </div>

                  {/* AC coverage — prefer the telemetry split, fall back to the plan's ids. */}
                  <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                    <span>AC:</span>
                    {(rec.ac_covered ?? item.acceptance_criteria_ids).map((ac) => (
                      <span key={ac} className="text-emerald-400 font-mono">{ac}</span>
                    ))}
                    {(rec.ac_missing ?? []).map((ac) => (
                      <span key={ac} className="text-red-400 font-mono line-through">{ac}</span>
                    ))}
                  </div>

                  {/* Per-story telemetry from the status map (rendered defensively). */}
                  {(rec.cost_usd != null || rec.wall_time_s != null || rec.model || rec.attempts != null) && (
                    <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-600 font-mono">
                      {rec.cost_usd != null && <span>${rec.cost_usd.toFixed(2)}</span>}
                      {rec.wall_time_s != null && <span>{rec.wall_time_s}s</span>}
                      {rec.model && <span>{rec.model}</span>}
                      {rec.attempts != null && <span>{rec.attempts} attempt{rec.attempts === 1 ? "" : "s"}</span>}
                    </div>
                  )}

                  {rec.resume && (
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className={rec.resume.cache_hit ? "text-sky-300" : "text-zinc-500"}>
                        {rec.resume.cache_hit ? "cache hit" : "rebuilt"}
                      </span>
                      {rec.resume.reason && (
                        <span className="text-zinc-600">{rec.resume.reason}</span>
                      )}
                    </div>
                  )}

                  {rec.quality_gate && (
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className={rec.quality_gate.passed ? "text-emerald-400" : "text-red-400"}>
                        quality {rec.quality_gate.passed ? "passed" : "failed"}
                      </span>
                      {rec.quality_gate.score != null && (
                        <span className="text-zinc-600">score {rec.quality_gate.score}</span>
                      )}
                    </div>
                  )}

                  {testStatus && (
                    <div className="flex items-center gap-1.5 text-xs">
                      <FlaskConical className={`w-3.5 h-3.5 shrink-0 ${st.text}`} />
                      <span className="text-zinc-400">{testStatus}</span>
                    </div>
                  )}

                  {(rec.changed_files ?? []).length > 0 && (
                    <ul className="ml-1 space-y-0.5">
                      {(rec.changed_files ?? []).map((f) => (
                        <li key={f} className="font-mono text-xs text-zinc-500 break-all">{f}</li>
                      ))}
                    </ul>
                  )}

                  {rec.rationale && (
                    <p className="text-xs text-zinc-600 italic">{rec.rationale}</p>
                  )}
                </li>
              );
            })}
          </ol>
          </div>
          ))}
        </div>
      )}
    </div>
  );
}
