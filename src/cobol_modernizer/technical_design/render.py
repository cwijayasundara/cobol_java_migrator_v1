"""Self-contained HTML view of a TechnicalDesign: services with their bounded context,
deployment unit, delivered stories, and API/persistence/integration contracts."""
from __future__ import annotations

from html import escape

from cobol_modernizer.technical_design.schema import TechnicalDesign


def render_html(design: TechnicalDesign) -> str:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;color:#18181b}"
        "h1{font-size:1.4rem}.svc{border:1px solid #e4e4e7;border-radius:8px;padding:1rem;margin:.75rem 0}"
        "table{border-collapse:collapse;margin:.5rem 0}td,th{border:1px solid #e4e4e7;padding:.25rem .5rem;font-size:.85rem}"
        "</style></head><body>",
        f"<h1>Technical Design — {escape(design.repo_slug)} (v{design.version})</h1>",
    ]
    for svc in design.services:
        parts.append("<div class='svc'>")
        parts.append(f"<h2>{escape(svc.name)} <small>[{escape(svc.bounded_context)} · {escape(svc.deployment)}]</small></h2>")
        if svc.story_ids:
            parts.append(f"<p>stories: {escape(', '.join(svc.story_ids))}</p>")
        if svc.api_contracts:
            parts.append("<table><tr><th>API</th><th>Method</th><th>Path</th></tr>")
            for a in svc.api_contracts:
                parts.append(f"<tr><td>{escape(a.name)}</td><td>{escape(a.method)}</td><td>{escape(a.path)}</td></tr>")
            parts.append("</table>")
        if svc.persistence:
            parts.append("<table><tr><th>Resource</th><th>Access pattern</th></tr>")
            for p in svc.persistence:
                parts.append(f"<tr><td>{escape(p.resource)}</td><td>{escape(p.access_pattern)}</td></tr>")
            parts.append("</table>")
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)
