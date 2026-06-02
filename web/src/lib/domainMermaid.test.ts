import { describe, it, expect } from "vitest";
import { contextMapMermaid, contextClassDiagram } from "@/lib/domainMermaid";
import type { DomainDesignResult } from "@/lib/api";

const RESULT: DomainDesignResult = {
  repo_slug: "demo", version: 1, rating: "high",
  contexts: [
    { name: "Account", business_capability: "accounts", member_programs: ["P2"],
      owned_resources: ["ACCT"], depends_on: [],
      topology: { deployment: "module", score: 0.2 }, extraction_rank: 2, identity_drift: true },
    { name: "Posting", business_capability: "post tx", member_programs: ["P1"],
      owned_resources: ["TRAN"],
      depends_on: [{ target: "Account", style: "async", reason: "emits TransactionPosted" }],
      topology: { deployment: "microservice", score: 0.7 }, extraction_rank: 1, identity_drift: false },
  ],
  designs: [
    { context: "Posting", aggregates: [{ name: "Transaction", root_entity: "Transaction",
        invariants: ["amount != 0"], entities: ["LineItem"], value_objects: ["Money"],
        methods: ["post", "reverse"] }],
      value_objects: [], domain_services: ["PostingService"], repositories: [],
      domain_events: ["TransactionPosted"], api_surface: "POST /transactions", cobol_mapping: [] },
  ],
};

describe("contextMapMermaid", () => {
  it("emits a flowchart with contexts ordered by extraction rank, topology classes, and a dotted async edge", () => {
    const m = contextMapMermaid(RESULT);
    expect(m.startsWith("flowchart LR")).toBe(true);
    // Posting (rank 1) declared before Account (rank 2)
    expect(m.indexOf("Posting[")).toBeLessThan(m.indexOf("Account["));
    expect(m).toMatch(/Posting\["#1 Posting · microservice/);
    expect(m).toContain(":::svc");
    expect(m).toContain(":::mod");
    // async dependency -> dotted edge with label
    expect(m).toMatch(/Posting -\. "async: emits TransactionPosted" \.-> Account/);
    // aggregate listed inside the node
    expect(m).toContain("▸ Transaction");
  });
});

describe("contextClassDiagram", () => {
  it("emits a classDiagram with the aggregate, its methods, and composition to entity/VO", () => {
    const m = contextClassDiagram(RESULT.designs[0]);
    expect(m.startsWith("classDiagram")).toBe(true);
    expect(m).toContain("class Transaction {");
    expect(m).toContain("+post()");
    expect(m).toContain("+reverse()");
    expect(m).toContain("Transaction *-- LineItem");
    expect(m).toContain("Transaction o-- Money");
    expect(m).toContain("class PostingService");
  });
});
