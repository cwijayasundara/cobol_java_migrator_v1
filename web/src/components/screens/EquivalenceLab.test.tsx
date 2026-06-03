import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { EquivalenceLab } from "@/components/screens/EquivalenceLab";

describe("EquivalenceLab", () => {
  it("runs equivalence and shows the verdict + seam-linked defect", async () => {
    render(<EquivalenceLab workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /run equivalence/i }));
    expect(await screen.findByText("fail")).toBeInTheDocument();
    expect(screen.getByText(/1 compared · 1 defect/)).toBeInTheDocument();
    expect(screen.getByText("BAL")).toBeInTheDocument();
    expect(screen.getByText(/CBPOST1M\.1300-POST \(MOVES_TO\)/)).toBeInTheDocument();
    expect(screen.getByText(/golden=1234\.56 candidate=1234\.50/)).toBeInTheDocument();
  });

  // ---- lazy-load + per-story verdicts + repair (Fan-Out-and-Synthesize) ---- //

  // The REAL GET /verify/status `result` shape (verify.py verify_status): the
  // persisted verify_report's rollup PLUS per_story_verdicts + failing_subslices +
  // stage_status. Each per-story sub mirrors `_fan_out_per_story` (slice_name/ok/
  // verdict/defect_count/partial/...); a FAILING decomposed story also carries
  // `subslices` leaves (the UI derives the failing ones from these). The flat
  // report-level `failing_subslices` is the deduped roll-up across stories.
  // Here: S2 fails and localizes to CBACT01C, S3 is a partial/timeout, S1 passes.
  const STATUS_RESULT = {
    version: 3,
    repo_slug: "carddemo-mini",
    verdict: "fail",
    records_compared: 6,
    defect_count: 2,
    open_questions: ["golden master stale for S2?"],
    defects: [],
    per_story_verdicts: [
      {
        story_id: "S1", slice_name: "S1", ok: true, verdict: "pass",
        records_compared: 2, defect_count: 0, open_questions: [], defects: [],
        partial: false, reason: "equivalence passed",
      },
      {
        story_id: "S2", slice_name: "S2", ok: false, verdict: "fail",
        records_compared: 4, defect_count: 2, open_questions: [], defects: [],
        partial: false, reason: "equivalence failed",
        subslices: [
          { subslice: "CBPOST1M", ok: true, verdict: "pass", defect_count: 0,
            partial: false, reason: "equivalence passed" },
          { subslice: "CBACT01C", ok: false, verdict: "fail", defect_count: 2,
            partial: false, reason: "equivalence failed" },
        ],
      },
      {
        story_id: "S3", slice_name: "S3", ok: false, verdict: "fail",
        records_compared: 0, defect_count: 0, open_questions: [], defects: [],
        partial: true, reason: "timeout",
      },
    ],
    failing_subslices: ["CBACT01C"],
    stage_status: "failed",
  };

  function registerVerifyHandlers(opts?: { onRepair?: (storyId: string) => void }) {
    server.use(
      http.get("/api/workspaces/:id/verify/status", () =>
        HttpResponse.json({
          status: "done", result: STATUS_RESULT, error: null,
          started_at: null, finished_at: null,
        })),
      http.post("/api/workspaces/:id/verify/repair/:storyId", ({ params }) => {
        opts?.onRepair?.(String(params.storyId));
        return HttpResponse.json({
          repo_slug: "carddemo-mini", story_id: String(params.storyId),
          verdict: "pass", resolved: true, attempts: 1, records_compared: 2,
          defect_count: 0, open_questions: [], defects: [], version: 4,
        });
      }),
    );
  }

  it("lazy-loads the latest persisted verdict on mount (idle when none)", async () => {
    registerVerifyHandlers();
    render(<EquivalenceLab workspaceId="ws-1" />);

    // The persisted report's verdict + version surface without clicking "Run".
    await waitFor(() => expect(screen.getByText(/v3/)).toBeInTheDocument());
    expect(screen.getAllByText(/fail/i).length).toBeGreaterThan(0);
    // The defect/coverage summary from the persisted report.
    expect(screen.getByText(/6 compared/)).toBeInTheDocument();
  });

  it("renders per-story verdicts with defect counts, partial flag and localized sub-slices", async () => {
    registerVerifyHandlers();
    render(<EquivalenceLab workspaceId="ws-1" />);

    await waitFor(() => expect(screen.getByText("S1")).toBeInTheDocument());
    expect(screen.getByText("S2")).toBeInTheDocument();
    expect(screen.getByText("S3")).toBeInTheDocument();

    // S2's localized failing sub-slice (decompose-further) is surfaced.
    expect(screen.getByText(/CBACT01C/)).toBeInTheDocument();
    // S3 is a partial / timeout sub-verdict, flagged distinctly.
    expect(screen.getByText(/partial/i)).toBeInTheDocument();
    // Defect count for S2 (also surfaced in the report roll-up, hence getAllByText).
    expect(screen.getAllByText(/2 defects/).length).toBeGreaterThan(0);
  });

  it("shows a Repair button only for failing stories and POSTs to /verify/repair/{story_id}", async () => {
    let repaired: string | null = null;
    registerVerifyHandlers({ onRepair: (s) => { repaired = s; } });
    render(<EquivalenceLab workspaceId="ws-1" />);

    await waitFor(() => expect(screen.getByText("S2")).toBeInTheDocument());

    // One repair button per FAILING story (S2 + S3), none for the passing S1.
    const repairButtons = screen.getAllByRole("button", { name: /repair/i });
    expect(repairButtons.length).toBe(2);

    await userEvent.click(repairButtons[0]);
    // The first failing story is S2 (plan order).
    await waitFor(() => expect(repaired).toBe("S2"));
  });

  it("idle when no verify has been persisted (404/idle status)", async () => {
    server.use(
      http.get("/api/workspaces/:id/verify/status", () =>
        HttpResponse.json({
          status: "idle", result: null, error: null,
          started_at: null, finished_at: null,
        })),
    );
    render(<EquivalenceLab workspaceId="ws-1" />);
    // No persisted verdict — the "Run equivalence" action is still available.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /run equivalence/i })).toBeInTheDocument());
    expect(screen.queryByText(/per-story/i)).not.toBeInTheDocument();
  });
});
