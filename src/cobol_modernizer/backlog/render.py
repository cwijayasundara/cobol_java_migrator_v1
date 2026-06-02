"""Self-contained HTML view of a Backlog (epics → stories → acceptance criteria →
dependencies) plus the BRD logic-coverage summary, for inline cockpit display."""
from __future__ import annotations

from html import escape

from cobol_modernizer.backlog.schema import Backlog


def render_html(backlog: Backlog, coverage: dict) -> str:
    ratio = float(coverage.get("coverage_ratio", 0.0)) if coverage else 0.0
    pct = round(ratio * 100)
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;color:#18181b}"
        "h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:1.5rem}"
        ".story{border:1px solid #e4e4e7;border-radius:8px;padding:.75rem;margin:.5rem 0}"
        ".ac{color:#3f3f46;font-size:.9rem;margin-left:1rem}"
        ".cov{font-weight:600}</style></head><body>",
        f"<h1>Business Backlog — {escape(backlog.repo_slug)} (v{backlog.version})</h1>",
        f"<p class='cov'>BRD logic coverage: {pct}%</p>",
    ]
    for epic in backlog.epics:
        parts.append(f"<h2>{escape(epic.id)} · {escape(epic.title)}</h2>")
        parts.append(f"<p>{escape(epic.outcome)}</p>")
        for story in [s for s in backlog.stories if s.epic_id == epic.id]:
            parts.append("<div class='story'>")
            parts.append(f"<strong>{escape(story.id)} — {escape(story.title)}</strong>")
            parts.append(f"<p>{escape(story.narrative)}</p>")
            if story.depends_on:
                parts.append(f"<p>depends on: {escape(', '.join(story.depends_on))}</p>")
            for ac in story.acceptance_criteria:
                parts.append(f"<div class='ac'>{escape(ac.id)}: {escape(ac.statement)}</div>")
            parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)
