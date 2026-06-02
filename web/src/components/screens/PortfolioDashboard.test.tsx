import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { PortfolioDashboard } from "@/components/screens/PortfolioDashboard";

describe("PortfolioDashboard", () => {
  it("shows a friendly error with Retry when the workspaces API fails", async () => {
    server.use(
      http.get("*/api/workspaces", () => new HttpResponse("Not Found", { status: 404 })),
    );
    render(<PortfolioDashboard />);
    expect(await screen.findByText(/reach the control-plane API/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    // the raw status is surfaced for debugging
    expect(screen.getByText(/404/)).toBeInTheDocument();
  });

  it("lists workspaces with repo slug and a cost-vs-cap pill", async () => {
    render(<PortfolioDashboard />);
    expect(await screen.findByText("CardDemo")).toBeInTheDocument();
    expect(screen.getByText("aws-mf-carddemo")).toBeInTheDocument();
    // cost vs cap pill, not just spend
    expect(screen.getByText(/\$18\.42\s*\/\s*\$50/)).toBeInTheDocument();
  });

  it("shows discovered local repos with a Create-workspace action (not just carddemo)", async () => {
    render(<PortfolioDashboard />);
    expect(await screen.findByText("Available repositories")).toBeInTheDocument();
    // both discovered repos are selectable
    expect(screen.getByText("aws-mf-mod-carddemo")).toBeInTheDocument();
    expect(screen.getByText("carddemo-mini")).toBeInTheDocument();
    expect(screen.getByText(/3 programs · 1 copybooks/)).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: /create workspace/i });
    expect(buttons.length).toBe(2); // neither discovered slug matches the seeded workspace
  });

  it("creates a workspace for a selected repo and surfaces it as selectable", async () => {
    render(<PortfolioDashboard />);
    await screen.findByText("Available repositories");
    const miniCard = screen.getByText("carddemo-mini").closest(".rounded-lg")!;
    await userEvent.click(within(miniCard as HTMLElement).getByRole("button", { name: /create workspace/i }));
    // the new workspace appears in the Workspaces section (selectable card -> journey)
    const wsLink = await screen.findByRole("link", { name: /carddemo-mini/i });
    expect(wsLink.getAttribute("href")).toMatch(/^\/workspaces\/.*\/journey\/outcome$/);
  });
});
