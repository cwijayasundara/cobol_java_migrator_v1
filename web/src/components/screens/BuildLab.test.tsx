import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { BuildLab } from "@/components/screens/BuildLab";
import { server } from "@/test/msw/server";

function registerStoryHandlers() {
  server.use(
    http.get("/api/workspaces/:id/build/story-plan", () =>
      HttpResponse.json({
        repo_slug: "carddemo-mini",
        version: 1,
        items: [{
          story_id: "S1", bounded_context: "Posting", service_name: "posting-service",
          acceptance_criteria_ids: ["AC1"], cobol_refs: ["CBPOST1M.WRITE-ACCT"],
          depends_on: [], status: "pending",
        }],
      })),
    http.get("/api/workspaces/:id/build/stories", () =>
      HttpResponse.json({
        stories: {},
        job: { status: "idle", result: null, error: null, started_at: null, finished_at: null },
      })),
  );
}

describe("BuildLab", () => {
  it("opens on the optimized story-build path by default", async () => {
    registerStoryHandlers();
    render(<BuildLab workspaceId="ws-1" />);
    expect(await screen.findByText(/story build \(per-story codegen\)/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /build all ready stories/i })).toBeInTheDocument();
  });

  it("generates a slice and lists test-first files with evidence", async () => {
    registerStoryHandlers();
    render(<BuildLab workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /single slice/i }));
    await userEvent.click(screen.getByRole("button", { name: /generate code/i }));
    expect(await screen.findByText("carddemo-mini-posting")).toBeInTheDocument();
    expect(screen.getByText("com.cobolmodernizer.carddemomini")).toBeInTheDocument();
    expect(screen.getByText(/1 test/)).toBeInTheDocument();
    expect(screen.getByText(/PostingServiceTest\.java/)).toBeInTheDocument();
    expect(screen.getByText(/CBPOST1M\.WRITE-ACCT/)).toBeInTheDocument();
  });
});
