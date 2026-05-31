import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalOverlay } from "@/components/cockpit/ApprovalOverlay";
import { GATES, BUDGET } from "@/test/fixtures/controlplane";

describe("ApprovalOverlay", () => {
  it("requires RBAC identity + rationale and surfaces budget impact, then submits attributed approval", async () => {
    const onDecided = vi.fn();
    render(
      <ApprovalOverlay
        gate={GATES[0]}
        budget={BUDGET}
        currentUserEmail="lead@biz2bricks.ai"
        estimatedCostUsd={1.25}
        onDecided={onDecided}
      />,
    );
    // budget impact shown: estimate + remaining-after
    expect(screen.getByText(/\$1\.25/)).toBeInTheDocument();
    expect(screen.getByText(/remaining/i)).toBeInTheDocument();

    // approve disabled until role + rationale provided (RBAC attribution)
    const approve = screen.getByRole("button", { name: /approve/i });
    expect(approve).toBeDisabled();

    await userEvent.selectOptions(screen.getByLabelText(/role/i), "lead_engineer");
    await userEvent.type(screen.getByLabelText(/rationale/i), "groundedness gate cleared");
    expect(approve).toBeEnabled();

    await userEvent.click(approve);
    expect(onDecided).toHaveBeenCalledWith(
      expect.objectContaining({ approver_email: "lead@biz2bricks.ai", decision: "approved" }),
    );
  });
});
