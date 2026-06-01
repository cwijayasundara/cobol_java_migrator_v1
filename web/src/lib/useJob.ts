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
//
// Polling uses EXPONENTIAL BACKOFF (minIntervalMs → maxIntervalMs, ×factor) so a
// multi-minute job costs ~25 requests instead of one every 2.5s (~100+). A single
// `timer` ref plus clear-before-set keeps exactly one poll chain alive even under
// React StrictMode's double-mount (which previously spawned two overlapping chains).
export function useJob<T>(
  start: () => Promise<Job<T>>,
  poll: () => Promise<Job<T>>,
  minIntervalMs = 1500,
  maxIntervalMs = 10000,
  factor = 1.6,
) {
  const [status, setStatus] = useState<JobStatus | "">("");
  const [result, setResult] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delay = useRef(minIntervalMs);
  const alive = useRef(true);

  const schedule = (fn: () => void, ms: number) => {
    // Clear-before-set: only ever one pending timer, so StrictMode's two initial
    // ticks collapse to a single steady chain instead of doubling the poll rate.
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(fn, ms);
  };

  const apply = (job: Job<T>) => {
    setStatus(job.status); setResult(job.result); setError(job.error);
    // Only a 'running' job keeps polling; idle/done/failed are terminal here.
    if (job.status === "running") {
      schedule(tick, delay.current);
      delay.current = Math.min(maxIntervalMs, Math.round(delay.current * factor));
    }
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
    delay.current = minIntervalMs;  // reset backoff for a fresh run
    try {
      const job = await start();
      if (!alive.current) return;
      if (job.status === "done" || job.status === "failed") {
        setStatus(job.status); setResult(job.result); setError(job.error);
      } else {
        tick();  // poll immediately, then on a backing-off interval until terminal
      }
    } catch (e) {
      if (alive.current) { setStatus("failed"); setError(e instanceof Error ? e.message : String(e)); }
    }
  };

  return { status, result, error, busy: status === "running", run };
}
