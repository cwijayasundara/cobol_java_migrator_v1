// Test stub for the `mermaid` package (aliased in vitest.config.ts). Real mermaid needs
// browser layout APIs jsdom lacks; tests only care that MermaidDiagram wires up + the
// builder output, not the rendered SVG.
export default {
  initialize() {},
  async render(_id: string, chart: string) {
    return { svg: `<svg data-mermaid-len="${chart.length}"></svg>` };
  },
};
