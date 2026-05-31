import { describe, it, expect } from "vitest";
import { kindColor, relColor } from "@/lib/colors";

describe("graph colors", () => {
  it("colors COBOL v1 + v2 node kinds distinctly", () => {
    expect(kindColor("Program")).toBe("#0ea5e9");
    expect(kindColor("DataItem")).toBe("#f472b6"); // v2
    expect(kindColor("Unknown")).toBe("#6b7280");
  });
  it("colors readers and writers differently (Fowler pivotal split)", () => {
    expect(relColor("READS")).not.toBe(relColor("WRITES"));
    expect(relColor("EXECUTES_CICS")).toBeTruthy();
  });
});
