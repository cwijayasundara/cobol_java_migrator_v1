import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { StoryBuildLab } from "@/components/screens/StoryBuildLab";

// MSW handlers for the four story-build endpoints (Task 7 contract). The default
// server has no story handlers, so every test registers its own via server.use.
function registerStoryHandlers(opts?: {
  onBuildAll?: () => void;
  onBuildStory?: (storyId: string) => void;
}) {
  server.use(
    http.get("/api/workspaces/:id/build/story-plan", () =>
      HttpResponse.json({
        repo_slug: "carddemo-mini",
        version: 1,
        items: [
          {
            story_id: "S1", bounded_context: "Posting", service_name: "posting-service",
            acceptance_criteria_ids: ["AC1", "AC2"], cobol_refs: ["CBPOST1M.WRITE-ACCT"],
            depends_on: [], status: "passed",
          },
          {
            story_id: "S2", bounded_context: "Validation", service_name: "validation-service",
            acceptance_criteria_ids: ["AC3"], cobol_refs: ["CBVALDTM.100-INIT"],
            depends_on: ["S1"], status: "generated-unverified",
          },
          {
            story_id: "S3", bounded_context: "Reporting", service_name: "reporting-service",
            acceptance_criteria_ids: ["AC4"], cobol_refs: ["CBRPT01.MAIN"],
            depends_on: ["S2"], status: "pending",
          },
        ],
      })),
    http.get("/api/workspaces/:id/build/stories", () =>
      HttpResponse.json({
        stories: {
          S1: {
            status: "passed", wall_time_s: 42.5, model: "claude-sonnet-4-6",
            cost_usd: 0.12, attempts: 1,
            changed_files: ["src/main/java/Posting.java", "src/test/java/PostingTest.java"],
            test_result: "1 passed", ac_covered: ["AC1", "AC2"], ac_missing: [],
            rationale: "Posting writer ported.",
          },
          S2: {
            status: "generated-unverified", wall_time_s: 30.1, model: "claude-sonnet-4-6",
            cost_usd: 0.09, attempts: 1,
            changed_files: ["src/main/java/Validation.java"],
            test_result: "toolchain absent (mvn/JDK not found)",
            ac_covered: ["AC3"], ac_missing: [],
            rationale: "Generated but not test-verified.",
          },
        },
        job: { status: "idle", result: null, error: null, started_at: null, finished_at: null },
      })),
    http.post("/api/workspaces/:id/build/stories", () => {
      opts?.onBuildAll?.();
      return HttpResponse.json(
        { status: "running", result: null, error: null, started_at: 1, finished_at: null },
        { status: 202 });
    }),
    http.post("/api/workspaces/:id/build/stories/:storyId", ({ params }) => {
      opts?.onBuildStory?.(String(params.storyId));
      return HttpResponse.json(
        { status: "running", result: null, error: null, started_at: 1, finished_at: null },
        { status: 202 });
    }),
  );
}

describe("StoryBuildLab", () => {
  it("renders the story DAG plan in order with statuses and dependencies", async () => {
    registerStoryHandlers();
    render(<StoryBuildLab workspaceId="ws-1" />);

    // Stories appear in plan order S1, S2, S3.
    await waitFor(() => expect(screen.getByText("S1")).toBeInTheDocument());
    expect(screen.getByText("S2")).toBeInTheDocument();
    expect(screen.getByText("S3")).toBeInTheDocument();

    // Dependencies surfaced.
    expect(screen.getAllByText(/after S1/i).length).toBeGreaterThan(0);

    // Bounded context / service shown.
    expect(screen.getByText(/posting-service/i)).toBeInTheDocument();
  });

  it("surfaces generated-unverified distinctly from passed/pending", async () => {
    registerStoryHandlers();
    render(<StoryBuildLab workspaceId="ws-1" />);

    await waitFor(() => expect(screen.getByText("S2")).toBeInTheDocument());

    // The generated-unverified status label is rendered with its own wording.
    expect(screen.getAllByText(/generated-unverified/i).length).toBeGreaterThan(0);
    // And a passed one exists too.
    expect(screen.getAllByText(/passed/i).length).toBeGreaterThan(0);
  });

  it("renders per-story telemetry from the status map (cost/time/files/test/AC)", async () => {
    registerStoryHandlers();
    render(<StoryBuildLab workspaceId="ws-1" />);

    await waitFor(() => expect(screen.getByText("S1")).toBeInTheDocument());

    // Cost + wall time.
    expect(screen.getByText(/\$0\.12/)).toBeInTheDocument();
    expect(screen.getByText(/42\.5/)).toBeInTheDocument();
    // Touched file.
    expect(screen.getByText(/Posting\.java/)).toBeInTheDocument();
    // Test result + AC coverage.
    expect(screen.getByText(/1 passed/)).toBeInTheDocument();
    expect(screen.getByText(/AC1/)).toBeInTheDocument();
    // The generated-unverified test result wording.
    expect(screen.getByText(/toolchain absent/i)).toBeInTheDocument();
  });

  it("triggers the build-all POST when 'Build all ready stories' is clicked", async () => {
    let called = false;
    registerStoryHandlers({ onBuildAll: () => { called = true; } });
    render(<StoryBuildLab workspaceId="ws-1" />);

    await waitFor(() => expect(screen.getByText("S1")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /build all ready stories/i }));
    await waitFor(() => expect(called).toBe(true));
  });

  it("triggers the per-story POST when 'Build next ready story' is clicked", async () => {
    let builtStory: string | null = null;
    registerStoryHandlers({ onBuildStory: (s) => { builtStory = s; } });
    render(<StoryBuildLab workspaceId="ws-1" />);

    await waitFor(() => expect(screen.getByText("S1")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /build next ready story/i }));
    // S3 is the next "pending" ready story (S1 passed, S2 generated-unverified).
    await waitFor(() => expect(builtStory).toBe("S3"));
  });
});
