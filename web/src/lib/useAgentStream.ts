"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AgentEvent } from "@/lib/types";

// Reads the server-side agent run's SSE stream. Execution is in FastAPI;
// this hook never starts/runs the agent, it only subscribes to events.
export function useAgentStream(workspaceId: string | null, runId: string | null) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setEvents([]);
    if (!workspaceId || !runId) return;
    const es = new EventSource(api.runEventsUrl(workspaceId, runId));
    esRef.current = es;
    setConnected(true);
    es.onmessage = (e: MessageEvent) => {
      try {
        const evt = JSON.parse(e.data) as AgentEvent;
        setEvents((prev) => [...prev, evt].sort((a, b) => a.seq - b.seq));
      } catch {
        /* ignore malformed frame */
      }
    };
    es.onerror = () => setConnected(false);
    return () => { es.close(); esRef.current = null; setConnected(false); };
  }, [workspaceId, runId]);

  return { events, connected };
}
