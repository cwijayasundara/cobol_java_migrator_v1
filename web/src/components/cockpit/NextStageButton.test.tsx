import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextStageButton } from "@/components/cockpit/NextStageButton";

describe("NextStageButton", () => {
  it("links each advanceable stage to the following stage", () => {
    const cases: Array<[string, string, string]> = [
      ["graph", "Explore", "explore"],
      ["explore", "Blueprint", "blueprint"],
      ["blueprint", "Seams", "seams"],
      ["seams", "Plan", "plan"],
      ["plan", "Design", "design"],
      ["design", "Build", "build"],
      ["build", "Verify", "verify"],
    ];
    for (const [stage, nextLabel, nextKey] of cases) {
      const { unmount } = render(<NextStageButton workspaceId="ws-1" stageKey={stage} />);
      const link = screen.getByRole("link", { name: /Next:/ });
      expect(link).toHaveTextContent(`Next: ${nextLabel}`);
      expect(link).toHaveAttribute("href", `/workspaces/ws-1/journey/${nextKey}`);
      unmount();
    }
  });

  it("renders nothing for non-advanceable stages", () => {
    for (const stage of ["outcome", "intake", "parse", "verify"]) {
      const { container } = render(<NextStageButton workspaceId="ws-1" stageKey={stage} />);
      expect(container).toBeEmptyDOMElement();
    }
  });
});
