import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { JourneyRail } from "@/components/cockpit/JourneyRail";
import { STAGES } from "@/test/fixtures/controlplane";

describe("JourneyRail", () => {
  it("renders all stages and marks the active one", () => {
    render(<JourneyRail workspaceId="ws-1" stages={STAGES} active="blueprint" />);
    // all canonical stages present (incl. the Domain Design stage)
    ["Outcome","Intake","Parse","Graph","Explore","Blueprint","Seams","Plan","Domain Design","Design","Build","Verify"]
      .forEach((label) => expect(screen.getByText(label)).toBeInTheDocument());
    const active = screen.getByText("Blueprint").closest("a");
    expect(active?.getAttribute("aria-current")).toBe("step");
  });

  it("groups stages under the three workflow phases", () => {
    render(<JourneyRail workspaceId="ws-1" stages={STAGES} active="blueprint" />);
    ["UNDERSTAND", "DESIGN", "MIGRATE"].forEach((heading) =>
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument(),
    );
  });
});
