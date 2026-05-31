from __future__ import annotations

import html as html_lib

import bleach
from markdown_it import MarkdownIt

from cobol_modernizer.brd.schema import BRD, BRDSection


_MD = MarkdownIt("commonmark", {"breaks": True, "html": False})

_ALLOWED_TAGS = [
    "p", "strong", "em", "code", "pre", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "blockquote", "hr", "br", "table",
    "thead", "tbody", "tr", "td", "th", "a",
]
_ALLOWED_ATTRS = {"a": ["href", "title"]}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]

_INLINE_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 880px; margin: 2rem auto; padding: 0 1rem;
       line-height: 1.55; color: #1f2328; background: #fff; }
h1, h2 { border-bottom: 1px solid #d0d7de; padding-bottom: .3em; }
h1 { font-size: 2rem; } h2 { font-size: 1.5rem; margin-top: 2.5rem; }
h3 { font-size: 1.2rem; margin-top: 2rem; }
code { background: #f6f8fa; padding: 0.2em 0.4em; border-radius: 4px; }
.requirement { background: #f6f8fa; border-left: 3px solid #0969da;
              padding: 0.6em 0.9em; margin: 0.5em 0; border-radius: 4px; }
.requirement .id { font-weight: 600; color: #0969da; margin-right: 0.5em; }
.evidence-table { width: 100%; border-collapse: collapse; margin-top: 1em; }
.evidence-table th, .evidence-table td {
    border: 1px solid #d0d7de; padding: 0.4em 0.6em; text-align: left;
}
"""


def _section_to_html(section: BRDSection) -> str:
    body_md = section.body_markdown or ""
    rendered = _MD.render(body_md)
    safe_body = bleach.clean(
        rendered,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=False,
    )
    parts = [f"<h2>{html_lib.escape(section.title)}</h2>", safe_body]
    for req in section.requirements:
        parts.append(
            f'<div class="requirement"><span class="id">{html_lib.escape(req.id)}</span>'
            f"{html_lib.escape(req.text)}</div>"
        )
    return "\n".join(parts)


def _evidence_to_html(evidence_map: dict[str, list[str]]) -> str:
    if not evidence_map:
        return ""
    rows = []
    for req_id, refs in evidence_map.items():
        joined = ", ".join(html_lib.escape(r) for r in refs)
        rows.append(f"<tr><td>{html_lib.escape(req_id)}</td><td>{joined}</td></tr>")
    return (
        "<h2>Evidence</h2>"
        '<table class="evidence-table">'
        "<thead><tr><th>Requirement</th><th>Grounded in</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_html(brd: BRD, *, title: str | None = None) -> str:
    doc_title = title or f"BRD — {brd.repo_id}"
    sections_html = "\n".join(_section_to_html(s) for s in brd.sections)
    evidence_html = _evidence_to_html(brd.evidence_map)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{html_lib.escape(doc_title)}</title>"
        f"<style>{_INLINE_CSS}</style></head><body>"
        f"<h1>{html_lib.escape(doc_title)}</h1>"
        f"{sections_html}{evidence_html}"
        "</body></html>"
    )
