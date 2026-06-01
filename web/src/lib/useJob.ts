"use client";

import { useEffect, useRef, useState } from "react";
import type { JobStatus } from "@/lib/api";

interface Job<T> { status: JobStatus; result: T | null; error: string | null }

// Drives a long backend job: POST to start, then poll status until done/failed.
// Used by the multi-minute LLM stages (Blueprint, Build) so the UI stays
// responsive instead of hanging on one synchronous request.
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

  useEffect(() => () => {
    alive.current = false;
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const tick = async () => {
    try {
      const job = await poll();
      if (!alive.current) return;
      setStatus(job.status); setResult(job.result); setError(job.error);
      if (job.status === "running" || job.status === "idle") {
        timer.current = setTimeout(tick, intervalMs);  // keep polling
      }
    } catch (e) {
      if (alive.current) { setStatus("failed"); setError(e instanceof Error ? e.message : String(e)); }
    }
  };

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
