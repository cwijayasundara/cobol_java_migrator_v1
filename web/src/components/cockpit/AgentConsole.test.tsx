import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentConsole } from "@/components/cockpit/AgentConsole";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  constructor(public url: string) { FakeEventSource.instances.push(this); }
  emit(d: unknown) { this.onmessage?.({ data: JSON.stringify(d) } as MessageEvent); }
  close() {}
}
beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
});

describe("AgentConsole", () => {
  it("shows the single Modernization Agent label and the active run", async () => {
    render(<AgentConsole workspaceId="ws-1" stageKey="blueprint" />);
    expect(await screen.findByText(/Modernization Agent/i)).toBeInTheDocument();
    // run-1 from MSW fixtures is running
    expect(await screen.findByText(/run-1/)).toBeInTheDocument();
  });

  it("renders readable tool-call events as they stream", async () => {
    render(<AgentConsole workspaceId="ws-1" stageKey="blueprint" />);
    await screen.findByText(/run-1/);
    const es = FakeEventSource.instances[0];
    es.emit({ type: "tool_call", run_id: "run-1", seq: 0, ts: "t", summary: "find_entities(prefix=CBACT)" });
    expect(await screen.findByText("find_entities(prefix=CBACT)")).toBeInTheDocument();
  });
});
