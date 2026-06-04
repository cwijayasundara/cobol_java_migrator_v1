"use client";

import { Fragment } from "react";
import { AlertTriangle, Boxes, CheckCircle2, Database, FolderTree, Play } from "lucide-react";
import { api, type TechnicalDesignResultSummary } from "@/lib/api";
import { useJob } from "@/lib/useJob";
import { MermaidDiagram } from "@/components/MermaidDiagram";

type PackageNode = { name: string; children: Map<string, PackageNode> };

function packageTree(paths: string[] = []): PackageNode {
  const root: PackageNode = { name: "", children: new Map() };
  for (const path of paths) {
    const parts = path.split(".").map((p) => p.trim()).filter(Boolean);
    let node = root;
    for (const part of parts) {
      if (!node.children.has(part)) node.children.set(part, { name: part, children: new Map() });
      node = node.children.get(part)!;
    }
  }
  return root;
}

function PackageTreeView({ packages }: { packages: string[] }) {
  const root = packageTree(packages);
  const render = (node: PackageNode, depth = 0) => (
    Array.from(node.children.values()).map((child) => (
      <div key={`${depth}-${child.name}-${Array.from(child.children.keys()).join(".")}`}>
        <div className="flex items-center gap-2 font-mono text-xs text-zinc-300"
          style={{ paddingLeft: `${depth * 14}px` }}>
          <span className="text-zinc-600">{child.children.size ? "▾" : "·"}</span>
          <span>{child.name}</span>
        </div>
        {render(child, depth + 1)}
      </div>
    ))
  );
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/40 p-3 max-h-72 overflow-auto">
      {root.children.size ? render(root) : (
        <div className="text-xs text-zinc-500">No package structure generated.</div>
      )}
    </div>
  );
}

function QualityBadge({ result }: { result: TechnicalDesignResultSummary }) {
  if (result.quality_passed === true) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-950 px-2 py-0.5 text-xs text-emerald-300">
        <CheckCircle2 className="h-3 w-3" /> quality passed
      </span>
    );
  }
  if (result.quality_passed === false) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-950 px-2 py-0.5 text-xs text-amber-300">
        <AlertTriangle className="h-3 w-3" /> quality needs review
      </span>
    );
  }
  return null;
}

// Technical Design stage: generate LLM-grounded service contracts (APIs, persistence,
// integration) from the BRD and DDD/OO design. POST starts a background job; poll for
// result. Once done, the rendered HTML view is served inline from the backend.
// Run Blueprint + Domain Design first — the BRD + OO design are the primary inputs.
export function DesignStudio({ workspaceId }: { workspaceId: string }) {
  const { result, error, busy, run } = useJob<TechnicalDesignResultSummary>(
    () => api.startTechnicalDesign(workspaceId),
    () => api.getTechnicalDesignStatus(workspaceId),
    5000,
    30000,
  );

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Boxes className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Technical Design</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Generates a Spring Boot 4 microservices design — service contracts, database ownership,
        package layout, and integration points — from the BRD and DDD/OO design.
        Run Blueprint and Domain Design first.
      </p>
      <button onClick={run} disabled={busy}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
        <Play className="w-4 h-4" />{busy ? "Generating… (this takes a minute)" : "Generate technical design"}
      </button>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error}</span>
        </div>
      )}

      {result && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 text-xs">
            <span className="font-mono text-zinc-200">Technical Design v{result.version}</span>
            <span className="text-zinc-400">
              {result.services} service{result.services === 1 ? "" : "s"}
            </span>
            {result.generation_mode && (
              <span className="rounded-full bg-zinc-900 px-2 py-0.5 text-zinc-400">
                {result.generation_mode}
              </span>
            )}
            <QualityBadge result={result} />
          </div>

          {result.target_platform && Object.keys(result.target_platform).length > 0 && (
            <div className="rounded-md border border-zinc-800 p-3">
              <div className="mb-2 text-xs font-medium text-zinc-300">Target platform</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {Object.entries(result.target_platform).map(([key, value]) => (
                  <div key={key} className="rounded bg-zinc-950/50 px-2 py-1">
                    <div className="text-[10px] uppercase text-zinc-600">{key.replaceAll("_", " ")}</div>
                    <div className="font-mono text-xs text-zinc-300">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.mermaid_component_diagram && (
            <MermaidDiagram
              caption="Spring Boot microservices component diagram"
              chart={result.mermaid_component_diagram}
            />
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-medium text-zinc-300">
                <FolderTree className="h-4 w-4 text-indigo-400" /> Java package structure
              </div>
              <PackageTreeView packages={result.package_structure ?? []} />
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-medium text-zinc-300">
                <Database className="h-4 w-4 text-indigo-400" /> Database design
              </div>
              <div className="space-y-2">
                {(result.database_design ?? []).map((db) => (
                  <div key={`${db.service}-${db.schema}`}
                    className="rounded-md border border-zinc-800 bg-zinc-950/40 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-mono text-xs text-zinc-200">{db.service}</div>
                      <div className="font-mono text-[10px] text-zinc-500">{db.schema}</div>
                    </div>
                    {db.migration_location && (
                      <div className="mt-1 font-mono text-[10px] text-zinc-500">{db.migration_location}</div>
                    )}
                    <div className="mt-2 overflow-x-auto">
                      <table className="w-full text-left text-[11px]">
                        <thead className="text-zinc-500">
                          <tr><th className="py-1 pr-2">Resource</th><th className="py-1 pr-2">Table</th><th className="py-1 pr-2">Entity</th></tr>
                        </thead>
                        <tbody>
                          {(db.tables ?? []).map((table) => (
                            <Fragment key={`${db.service}-${table.legacy_resource}-${table.table}`}>
                              <tr className="border-t border-zinc-900">
                                <td className="py-1 pr-2 font-mono text-zinc-300">{table.legacy_resource}</td>
                                <td className="py-1 pr-2 font-mono text-zinc-400">{table.table}</td>
                                <td className="py-1 pr-2 font-mono text-zinc-400">{table.entity}</td>
                              </tr>
                              {(table.columns ?? []).length > 0 && (
                                <tr>
                                  <td colSpan={3} className="pb-2">
                                    <div className="mt-1 rounded border border-zinc-900 bg-zinc-950/70 p-2">
                                      <div className="mb-1 text-[10px] uppercase text-zinc-600">Table schema</div>
                                      <table className="w-full text-left text-[10px]">
                                        <thead className="text-zinc-600">
                                          <tr><th className="py-1 pr-2">Column</th><th className="py-1 pr-2">Type</th><th className="py-1 pr-2">Constraints</th></tr>
                                        </thead>
                                        <tbody>
                                          {(table.columns ?? []).map((column) => (
                                            <tr key={`${table.table}-${column.name}`}
                                              className="border-t border-zinc-900">
                                              <td className="py-1 pr-2 font-mono text-zinc-300">{column.name}</td>
                                              <td className="py-1 pr-2 font-mono text-zinc-400">{column.type}</td>
                                              <td className="py-1 pr-2 text-zinc-500">
                                                {[
                                                  column.primary_key ? "PK" : "",
                                                  column.unique ? "unique" : "",
                                                  column.nullable === false ? "not null" : "nullable",
                                                ].filter(Boolean).join(", ")}
                                              </td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
                {(result.database_design ?? []).length === 0 && (
                  <div className="rounded-md border border-zinc-800 p-3 text-xs text-zinc-500">
                    No database design generated.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
