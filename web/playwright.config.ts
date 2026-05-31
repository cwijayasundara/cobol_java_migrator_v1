import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:3000" },
  // The control plane (FastAPI) must be running on :8000 and proxied via
  // next.config.ts rewrites. Run `uv run uvicorn cobol_modernizer.api:app`
  // and `npm run dev` before `npm run e2e`.
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
