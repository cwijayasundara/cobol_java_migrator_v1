// Pure, deterministic builders that turn a DomainDesignResult into Mermaid diagram source.
// No rendering here — MermaidDiagram renders the strings. Kept pure so it's unit-testable.
import type {
  DomainDesignResult, DomainContextDesign,
} from "@/lib/api";

// Mermaid node/class ids must be alphanumeric; labels must not contain raw double quotes.
const idOf = (name: string) => name.replace(/[^A-Za-z0-9_]/g, "_") || "n";
const label = (s: string) => s.replace(/"/g, "'").replace(/[\r\n]+/g, " ");
const method = (m: string) => m.replace(/[^A-Za-z0-9_]/g, "") || "op";

/**
 * High-level CONTEXT MAP: one node per bounded context (name + topology + aggregates),
 * edges for inter-context dependencies (solid = sync/ACL, dotted = async/event), ordered
 * by extraction rank, colored by module-vs-microservice.
 */
export function contextMapMermaid(result: DomainDesignResult): string {
  const designByCtx: Record<string, DomainContextDesign> =
    Object.fromEntries(result.designs.map((d) => [d.context, d]));
  const contexts = [...result.contexts].sort(
    (a, b) => (a.extraction_rank || 0) - (b.extraction_rank || 0));

  const lines: string[] = ["flowchart LR"];
  for (const c of contexts) {
    const aggs = (designByCtx[c.name]?.aggregates ?? []).map((a) => a.name);
    const aggLine = aggs.length ? `<br/>▸ ${label(aggs.join(", "))}` : "";
    const dep = c.topology?.deployment ?? "n/a";
    const cls = dep === "microservice" ? "svc" : "mod";
    lines.push(`  ${idOf(c.name)}["#${c.extraction_rank} ${label(c.name)} · ${dep}${aggLine}"]:::${cls}`);
  }
  for (const c of contexts) {
    for (const d of c.depends_on) {
      const text = label(`${d.style}: ${d.reason}`).slice(0, 60);
      lines.push(d.style === "async"
        ? `  ${idOf(c.name)} -. "${text}" .-> ${idOf(d.target)}`
        : `  ${idOf(c.name)} -->|"${text}"| ${idOf(d.target)}`);
    }
  }
  lines.push("  classDef svc fill:#064e3b,stroke:#10b981,color:#d1fae5;");
  lines.push("  classDef mod fill:#27272a,stroke:#52525b,color:#e4e4e7;");
  return lines.join("\n");
}

/**
 * Per-context CLASS DIAGRAM: each aggregate as a class with its methods, composing its
 * entities (*--) and value objects (o--). Standalone value objects / domain services are
 * added as bare classes. Self-references (entity named like its aggregate) are skipped.
 */
export function contextClassDiagram(design: DomainContextDesign): string {
  const lines: string[] = ["classDiagram"];
  for (const a of design.aggregates) {
    const id = idOf(a.name);
    if (a.methods.length) {
      lines.push(`  class ${id} {`);
      for (const m of a.methods) lines.push(`    +${method(m)}()`);
      lines.push("  }");
    } else {
      lines.push(`  class ${id}`);
    }
    for (const e of a.entities) if (idOf(e) !== id) lines.push(`  ${id} *-- ${idOf(e)}`);
    for (const v of a.value_objects) if (idOf(v) !== id) lines.push(`  ${id} o-- ${idOf(v)}`);
  }
  for (const v of design.value_objects) lines.push(`  class ${idOf(v)}`);
  for (const s of design.domain_services) lines.push(`  class ${idOf(s)}`);
  return lines.join("\n");
}
