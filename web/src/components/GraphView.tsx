"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { forceCollide, forceX, forceY } from "d3-force-3d";
import { api, GraphData, GraphNode } from "@/lib/api";
import { kindColor, relColor } from "@/lib/colors";
import { Maximize2, Minimize2, Plus, Minus, Locate } from "lucide-react";

// Base radius for a node, in graph units. Mirrors the library's own sizing
// (sqrt(val) * nodeRelSize) so collision spacing and custom drawing agree.
// Bumped from 8 -> 12 so nodes read clearly without zooming in.
const NODE_REL_SIZE = 12;
const nodeRadius = (node: any) => Math.sqrt(node.val ?? 1) * NODE_REL_SIZE;

interface Props {
  repo?: string;
  onNodeClick?: (node: GraphNode) => void;
  // Seam overlay (Phase 1+): draw a ring around seam-candidate Program nodes.
  seamOverlay?: Record<string, { readerOnly: boolean; score: number }>;
}

export function GraphView({ repo, onNodeClick, seamOverlay }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const didFitRef = useRef(false);
  const expandedRef = useRef<Set<string>>(new Set()); // node ids already expanded
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [ForceGraph, setForceGraph] = useState<any>(null);
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 800, h: 600 });
  const [fullscreen, setFullscreen] = useState(false);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    import("react-force-graph-2d").then((mod) => {
      setForceGraph(() => mod.default);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    didFitRef.current = false; // re-fit once when a new repo's graph settles
    expandedRef.current = new Set(); // forget prior expansions for the new repo
    api
      .getGraph(repo, 300)
      .then(setGraphData)
      .catch(() => setGraphData({ nodes: [], links: [] }))
      .finally(() => setLoading(false));
  }, [repo]);

  // Track container size so the canvas fills the box and reflows on resize/fullscreen.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setSize({ w: Math.max(300, rect.width), h: Math.max(300, rect.height) });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fullscreen, ForceGraph, graphData]);

  // Tune the d3 force simulation for spaced-but-gathered clusters: strong, long
  // reaching repulsion pushes distinct components (and the orphan DataItems) apart
  // so they read as separate clusters rather than one dense blob, while a GENTLE
  // x/y pull toward the origin keeps the whole graph on-canvas (forceCenter only
  // recenters the mean each tick — it applies no attraction, so without this the
  // disconnected nodes drift off to the corners). The balance between charge
  // (spread) and forceX/Y (gather) is the knob: stronger charge / weaker x-y ->
  // more spacing; the reverse -> tighter.
  useEffect(() => {
    const fg = graphRef.current;
    if (!fg || !graphData || graphData.nodes.length === 0) return;

    const charge = fg.d3Force?.("charge");
    if (charge) {
      charge.strength(-160);   // strong repulsion -> clusters push well apart
      charge.distanceMax(600);  // long reach so separate clusters repel each other
    }
    const link = fg.d3Force?.("link");
    if (link) {
      link.distance(36);  // roomier edges -> clusters have internal breathing space
      link.strength(0.6); // still cohesive, but not collapsed onto each other
    }
    const center = fg.d3Force?.("center");
    if (center?.strength) center.strength(1);

    // GENTLE attractive pull toward the origin — only enough to keep disconnected
    // nodes on-canvas; too strong and everything collapses into a single blob.
    fg.d3Force?.("x", forceX(0).strength(0.05));
    fg.d3Force?.("y", forceY(0).strength(0.05));

    // Collision force: no two nodes may overlap, with generous padding so even a
    // dense cluster stays legible.
    fg.d3Force?.(
      "collide",
      forceCollide((node: any) => nodeRadius(node) + 8)
        .strength(1)
        .iterations(2)
    );

    fg.d3ReheatSimulation?.();
  }, [graphData, ForceGraph]);

  // Pre-compute neighbor adjacency for hover-highlighting.
  const { neighborMap, linkMap } = useMemo(() => {
    const nMap = new Map<string, Set<string>>();
    const lMap = new Map<string, Set<string>>(); // node id -> set of "src|tgt" link keys
    if (!graphData) return { neighborMap: nMap, linkMap: lMap };
    for (const l of graphData.links) {
      const s = typeof l.source === "string" ? l.source : (l.source as any).id;
      const t = typeof l.target === "string" ? l.target : (l.target as any).id;
      if (!nMap.has(s)) nMap.set(s, new Set());
      if (!nMap.has(t)) nMap.set(t, new Set());
      nMap.get(s)!.add(t);
      nMap.get(t)!.add(s);
      const key = `${s}|${t}`;
      if (!lMap.has(s)) lMap.set(s, new Set());
      if (!lMap.has(t)) lMap.set(t, new Set());
      lMap.get(s)!.add(key);
      lMap.get(t)!.add(key);
    }
    return { neighborMap: nMap, linkMap: lMap };
  }, [graphData]);

  const focusId = hoverId ?? selectedId;
  const focusedNeighbors = focusId ? neighborMap.get(focusId) ?? new Set<string>() : null;
  const focusedLinks = focusId ? linkMap.get(focusId) ?? new Set<string>() : null;

  // Double-click-to-expand: fetch a node's one-hop neighbors and merge them into
  // the live graph, preserving existing node positions so the layout doesn't jump.
  // New nodes are seeded at the expanded node's position so they fan outward as
  // the simulation reheats. Already-expanded nodes are remembered to avoid refetch.
  const handleNodeExpand = useCallback(
    async (node: any) => {
      if (!node?.id || expandedRef.current.has(node.id)) return;
      expandedRef.current.add(node.id);
      let nb: GraphData;
      try {
        nb = await api.getNeighbors(node.id, repo);
      } catch {
        expandedRef.current.delete(node.id); // let the user retry on failure
        return;
      }
      const idOf = (e: any) => (typeof e === "string" ? e : e.id);
      setGraphData((cur) => {
        if (!cur) return cur;
        // Map value is `any`: react-force-graph augments nodes with runtime x/y
        // that aren't on the GraphNode type, and we seed those on new nodes.
        const byId = new Map<string, any>(cur.nodes.map((n) => [n.id, n]));
        let added = 0;
        for (const n of nb.nodes) {
          if (!byId.has(n.id)) {
            byId.set(n.id, { ...n, x: node.x, y: node.y });
            added += 1;
          }
        }
        const seen = new Set(cur.links.map((l) => `${idOf(l.source)}|${idOf(l.target)}|${l.type}`));
        const links = [...cur.links];
        for (const l of nb.links) {
          const key = `${l.source}|${l.target}|${l.type}`;
          if (!seen.has(key)) {
            links.push(l);
            seen.add(key);
          }
        }
        if (added === 0) return cur; // no new neighbors -> avoid a needless reheat
        return { nodes: Array.from(byId.values()), links };
      });
    },
    [repo]
  );

  // react-force-graph 1.29 has no onNodeDoubleClick, so we synthesize one: defer
  // the single-click action briefly; a second click on the SAME node within the
  // window cancels it and expands instead.
  const pendingClickRef = useRef<{ id: string; timer: ReturnType<typeof setTimeout> } | null>(null);
  const doSingleClick = useCallback(
    (node: any) => {
      setSelectedId(node.id);
      if (graphRef.current && typeof node.x === "number" && typeof node.y === "number") {
        graphRef.current.centerAt(node.x, node.y, 600);
        graphRef.current.zoom(2.4, 600);
      }
      if (onNodeClick && node.id) onNodeClick(node as GraphNode);
    },
    [onNodeClick]
  );
  const handleNodeClick = useCallback(
    (node: any) => {
      const pending = pendingClickRef.current;
      if (pending && pending.id === node.id) {
        clearTimeout(pending.timer);
        pendingClickRef.current = null;
        void handleNodeExpand(node);
        return;
      }
      if (pending) clearTimeout(pending.timer);
      const timer = setTimeout(() => {
        pendingClickRef.current = null;
        doSingleClick(node);
      }, 250);
      pendingClickRef.current = { id: node.id, timer };
    },
    [handleNodeExpand, doSingleClick]
  );
  // Clear any pending single-click timer on unmount.
  useEffect(() => () => {
    if (pendingClickRef.current) clearTimeout(pendingClickRef.current.timer);
  }, []);

  const handleZoom = (delta: number) => {
    if (!graphRef.current) return;
    const z = graphRef.current.zoom();
    graphRef.current.zoom(Math.max(0.2, Math.min(8, z * delta)), 200);
  };

  const handleFit = () => {
    graphRef.current?.zoomToFit(400, 60);
  };

  // Allow Esc to exit fullscreen.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  const containerClass = fullscreen
    ? "fixed inset-0 z-[60] bg-zinc-950 border border-zinc-800 overflow-hidden"
    : "w-full h-[75vh] min-h-[560px] bg-zinc-950 rounded-lg border border-zinc-800 overflow-hidden relative";

  return (
    <div ref={containerRef} className={containerClass}>
      {/* Legend */}
      <div className="absolute top-3 left-3 z-10 flex flex-wrap gap-2 max-w-[60%]">
        {graphData &&
          Object.entries(
            graphData.nodes.reduce<Record<string, number>>((acc, n) => {
              acc[n.kind] = (acc[n.kind] || 0) + 1;
              return acc;
            }, {})
          )
            .sort((a, b) => b[1] - a[1])
            .map(([kind, count]) => (
              <span
                key={kind}
                className="flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full bg-zinc-900/80 backdrop-blur border border-zinc-800"
              >
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: kindColor(kind) }} />
                {kind} ({count})
              </span>
            ))}
      </div>

      {/* Toolbar */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1 bg-zinc-900/80 backdrop-blur border border-zinc-800 rounded-md p-1">
        <button
          onClick={() => handleZoom(1.4)}
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-300"
          title="Zoom in"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => handleZoom(1 / 1.4)}
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-300"
          title="Zoom out"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={handleFit}
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-300"
          title="Fit to view"
        >
          <Locate className="w-3.5 h-3.5" />
        </button>
        <div className="w-px h-4 bg-zinc-800 mx-0.5" />
        <button
          onClick={() => setFullscreen((v) => !v)}
          className="p-1.5 rounded hover:bg-zinc-800 text-zinc-300"
          title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
        >
          {fullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* States */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center text-zinc-500 text-sm">
          Loading graph...
        </div>
      )}
      {!loading && (!graphData || graphData.nodes.length === 0) && (
        <div className="absolute inset-0 flex items-center justify-center text-zinc-500 text-sm">
          No graph data available.
        </div>
      )}
      {!loading && graphData && graphData.nodes.length > 0 && !ForceGraph && (
        <div className="absolute inset-0 flex items-center justify-center text-zinc-500 text-sm">
          Loading visualization...
        </div>
      )}

      {ForceGraph && graphData && graphData.nodes.length > 0 && (
        <ForceGraph
          ref={graphRef}
          graphData={graphData}
          width={size.w}
          height={size.h}
          backgroundColor="#09090b"
          nodeLabel={(node: any) =>
            `${node.name} (${node.kind})${node.signature ? "\n" + node.signature : ""}`
          }
          nodeRelSize={NODE_REL_SIZE}
          nodeVal={(node: any) => {
            const sizes: Record<string, number> = {
              Module: 8,
              Class: 6,
              Enum: 6,
              Function: 4,
              Method: 3,
              Constant: 2,
              GlobalVar: 2,
              External: 2,
              // COBOL kinds
              Program: 8,
              Section: 5,
              Paragraph: 4,
              Copybook: 4,
              // v2 (Phase 1)
              DataItem: 3,
            };
            return sizes[node.kind] ?? 3;
          }}
          // Draw nodes ourselves (replace mode) so each gets a crisp dark
          // outline and stays distinct instead of blurring into its neighbors.
          nodeCanvasObjectMode={() => "replace" as const}
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const isFocus = node.id === focusId;
            const isNeighbor = focusedNeighbors?.has(node.id) ?? false;
            const dim = focusId !== null && !isFocus && !isNeighbor;
            const r = nodeRadius(node);

            // Node body.
            ctx.beginPath();
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
            ctx.fillStyle = dim ? "rgba(120,120,130,0.2)" : kindColor(node.kind);
            ctx.fill();
            // Crisp separating outline.
            ctx.lineWidth = 1.5 / globalScale;
            ctx.strokeStyle = dim ? "rgba(255,255,255,0.05)" : "rgba(9,9,11,0.85)";
            ctx.stroke();

            // Selection ring for explicitly selected node.
            if (node.id === selectedId) {
              ctx.beginPath();
              ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI, false);
              ctx.strokeStyle = "#facc15";
              ctx.lineWidth = 2 / globalScale;
              ctx.stroke();
            }

            // Seam-candidate overlay ring (Phase 1+): emerald reader-only, amber writer.
            const seam = seamOverlay?.[node.id];
            if (seam) {
              ctx.beginPath();
              ctx.arc(node.x, node.y, r + 5, 0, 2 * Math.PI, false);
              ctx.strokeStyle = seam.readerOnly ? "#10b981" : "#f59e0b";
              ctx.lineWidth = 2.5 / globalScale;
              ctx.stroke();
            }

            // Label only when zoomed in enough, or always for focused/neighbor nodes.
            if (globalScale > 1.2 || isFocus || isNeighbor) {
              const fontSize = isFocus ? 12 / globalScale : 10 / globalScale;
              ctx.font = `${fontSize}px sans-serif`;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillStyle = dim ? "rgba(255,255,255,0.15)" : "rgba(255,255,255,0.9)";
              ctx.fillText(node.name, node.x, node.y + r + fontSize);
            }
          }}
          // Keep hover/click hit areas matching the drawn circle in replace mode.
          nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(node.x, node.y, nodeRadius(node), 0, 2 * Math.PI, false);
            ctx.fill();
          }}
          linkColor={(link: any) => {
            const base = relColor(link.type);
            if (focusId === null) return base;
            const s = typeof link.source === "string" ? link.source : link.source.id;
            const t = typeof link.target === "string" ? link.target : link.target.id;
            const key = `${s}|${t}`;
            if (focusedLinks?.has(key)) return base;
            return "rgba(120,120,130,0.08)";
          }}
          linkWidth={(link: any) => {
            if (focusId === null) return 0.6;
            const s = typeof link.source === "string" ? link.source : link.source.id;
            const t = typeof link.target === "string" ? link.target : link.target.id;
            const key = `${s}|${t}`;
            return focusedLinks?.has(key) ? 1.6 : 0.4;
          }}
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={1}
          linkDirectionalParticles={(link: any) => {
            if (focusId === null) return 0;
            const s = typeof link.source === "string" ? link.source : link.source.id;
            const t = typeof link.target === "string" ? link.target : link.target.id;
            return focusedLinks?.has(`${s}|${t}`) ? 2 : 0;
          }}
          linkDirectionalParticleWidth={2}
          linkLabel={(link: any) => link.type}
          onNodeHover={(node: any) => setHoverId(node?.id ?? null)}
          onNodeClick={handleNodeClick}
          onBackgroundClick={() => setSelectedId(null)}
          cooldownTicks={120}
          d3VelocityDecay={0.25}
          warmupTicks={20}
          onEngineStop={() => {
            // Frame the (now-compact) graph once it settles, so it fills the
            // canvas instead of sitting as a small clump in the middle.
            if (didFitRef.current) return;
            didFitRef.current = true;
            graphRef.current?.zoomToFit(500, 50);
          }}
          enableNodeDrag
          enableZoomInteraction
          enablePanInteraction
        />
      )}

      {/* Hint */}
      <div className="absolute bottom-3 left-3 z-10 text-[10px] text-zinc-500 bg-zinc-900/70 backdrop-blur px-2 py-1 rounded border border-zinc-800/60">
        scroll to zoom · drag node to pin · double-click to expand · hover to highlight neighbors
      </div>
    </div>
  );
}
