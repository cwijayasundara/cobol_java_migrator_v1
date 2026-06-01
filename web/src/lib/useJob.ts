"use client";

import { useEffect, useRef, useState } from "react";
import type { JobStatus } from "@/lib/api";

interface Job<T> { status: JobStatus; result: T | null; error: string | null }

// Drives a long backend job: POST to start, then poll status until done/failed.
// Used by the multi-minute LLM stages (Blueprint, Build) so the UI stays
// responsive instead of hanging on one synchronous request. On mount it syncs
// with the backend, so if a run is already in flight (e.g. after a reload or
// navigating back) the action stays disabled and polling resumes — a fresh mount
// can't fire a second run on top of one that's still going.
export function useJob<T>(
  start: () => Promise<Job<T>>,
  poll: () => Promise<Job<T>>,
  intervalMs = 2500,
) {
  const [status, setStatus] = useState<JobStatus | "">("");
  const [result, setResult] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  const apply = (job: Job<T>) => {
    setStatus(job.status); setResult(job.result); setError(job.error);
    // Only a 'running' job keeps polling; idle/done/failed are terminal here.
    if (job.status === "running") timer.current = setTimeout(tick, intervalMs);
  };

  const tick = async () => {
    try {
      const job = await poll();
      if (alive.current) apply(job);
    } catch (e) {
      if (alive.current) { setStatus("failed"); setError(e instanceof Error ? e.message : String(e)); }
    }
  };

  // Sync with the backend once on mount (reflect an in-flight or finished run).
  useEffect(() => {
    alive.current = true;
    void tick();
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async () => {
    setError(null); setResult(null); setStatus("running");
    try {
      const job = await start();
      if (!alive.current) return;
      if (job.status === "done" || job.status === "failed") {
        setStatus(job.status); setResult(job.result); setError(job.error);
      } else {
        tick();  // poll immediately, then on an interval until terminal
      }
    } catch (e) {
      if (alive.current) { setStatus("failed"); setError(e instanceof Error ? e.message : String(e)); }
    }
  };

  return { status, result, error, busy: status === "running", run };
}
