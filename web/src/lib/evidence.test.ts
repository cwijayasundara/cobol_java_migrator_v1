import { describe, expect, it } from "vitest";
import { evidenceRefs } from "@/lib/evidence";

describe("evidenceRefs", () => {
  it("keeps array refs", () => {
    expect(evidenceRefs(["REQ-1", "CBPOST1M"])).toEqual(["REQ-1", "CBPOST1M"]);
  });

  it("renders object refs without throwing", () => {
    expect(evidenceRefs({ status: "running", attempts: 1 })).toEqual([
      "status: running",
      "attempts: 1",
    ]);
  });

  it("renders scalar refs", () => {
    expect(evidenceRefs("inline://artifact")).toEqual(["inline://artifact"]);
    expect(evidenceRefs(null)).toEqual([]);
  });
});
