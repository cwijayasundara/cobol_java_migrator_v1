"""Self-contained HTML render of a DomainDesign for the cockpit iframe (no external CSS/JS).
Escapes all model-supplied text."""
from __future__ import annotations

from html import escape

from cobol_modernizer.domain.schema import DomainDesign


def _li(items: list[str]) -> str:
    return "".join(f"<li>{escape(s)}</li>" for s in items)


def render_html(dd: DomainDesign) -> str:
    blocks: list[str] = []
    designs = {d.context: d for d in dd.designs}
    for c in sorted(dd.contexts, key=lambda x: x.extraction_rank or 0):
        topo = c.topology
        badge = escape(topo.deployment) if topo else "n/a"
        score = f"{topo.score:.2f}" if topo else "-"
        d = designs.get(c.name)
        aggs = "".join(
            f"<div class=agg><b>{escape(a.name)}</b> (root: {escape(a.root_entity)})"
            f"<div>invariants:<ul>{_li(a.invariants)}</ul>methods:<ul>{_li(a.methods)}</ul></div></div>"
            for a in (d.aggregates if d else []))
        api = escape(d.api_surface) if d and d.api_surface else ""
        mapping = "".join(
            f"<tr><td>{escape(m.cobol_ref)}</td><td>{escape(m.maps_to)}</td><td>{escape(m.note)}</td></tr>"
            for m in (d.cobol_mapping if d else []))
        blocks.append(
            f"<section class=ctx><h2>#{c.extraction_rank} {escape(c.name)} "
            f"<span class=badge>{badge}</span> <small>score {score}</small></h2>"
            f"<p><i>{escape(c.business_capability)}</i></p>"
            f"<p>Owns: {escape(', '.join(c.owned_resources))}"
            f"{' &middot; identity-drift' if c.identity_drift else ''}</p>"
            f"<h3>Aggregates</h3>{aggs or '<p>none</p>'}"
            f"{('<h3>API</h3><pre>' + api + '</pre>') if api else ''}"
            f"{('<h3>COBOL mapping</h3><table><tr><th>COBOL</th><th>Domain</th><th>Note</th></tr>' + mapping + '</table>') if mapping else ''}"
            "</section>")
    style = ("body{font-family:system-ui;margin:2rem;color:#222}"
             ".ctx{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}"
             ".badge{background:#eef;border-radius:12px;padding:2px 8px;font-size:.8rem}"
             "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}"
             ".agg{margin:.5rem 0}")
    return (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<title>Domain Design v{dd.version} — {escape(dd.repo_slug)}</title>"
            f"<style>{style}</style></head><body>"
            f"<h1>Domain Design — {escape(dd.repo_slug)} "
            f"<small>v{dd.version} · {escape(dd.rating)}</small></h1>"
            f"{''.join(blocks)}</body></html>")
