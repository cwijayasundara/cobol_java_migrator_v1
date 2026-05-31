import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAgentStream } from "@/lib/useAgentStream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  url: string;
  closed = false;
  constructor(url: string) { this.url = url; FakeEventSource.instances.push(this); }
  emit(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent); }
  close() { this.closed = true; }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
});

describe("useAgentStream", () => {
  it("accumulates ordered agent events from the SSE stream", async () => {
    const { result } = renderHook(() => useAgentStream("ws-1", "run-1"));
    const es = FakeEventSource.instances[0];
    expect(es.url).toContain("/api/workspaces/ws-1/runs/run-1/events");
    act(() => {
      es.emit({ type: "plan", run_id: "run-1", seq: 0, ts: "t0", summary: "drafting BRD plan" });
      es.emit({ type: "tool_call", run_id: "run-1", seq: 1, ts: "t1", summary: "neighbors(CBACT01C)" });
    });
    await waitFor(() => expect(result.current.events.length).toBe(2));
    expect(result.current.events[1].summary).toBe("neighbors(CBACT01C)");
  });
});
