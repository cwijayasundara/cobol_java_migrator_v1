from __future__ import annotations

from pathlib import Path

try:
    from rich.console import Console
    from rich.progress import Progress
    console = Console()
    _RICH = True
except ModuleNotFoundError:  # rich is not a declared dependency; guard gracefully
    console = None  # type: ignore[assignment]
    _RICH = False

from cobol_modernizer.git_analyzer import GitAnalyzer
from cobol_modernizer.models import CodeEntity, CodeRelationship, ParseResult
from cobol_modernizer.neo4j_client import Neo4jClient
from cobol_modernizer.parser import parse_directory
from cobol_modernizer.ingestion_hash import build_manifest, diff_manifest


def _print(msg: str) -> None:
    if _RICH and console is not None:
        console.print(msg)
    else:
        import re
        plain = re.sub(r"\[/?[^\]]*\]", "", msg)
        print(plain)


# Optional/v2 CodeEntity columns projected onto the graph node when present.
_OPTIONAL_COLS = (
    "docstring", "signature", "level", "picture", "usage", "redefines", "parent_qname",
)


def _entity_props(entity: CodeEntity) -> dict:
    """Graph property projection for a CodeEntity (v1 + v2 columns). `repo` is set
    by the MERGE key, not here."""
    props: dict = {
        "kind": entity.kind.value,
        "simple_name": entity.simple_name,
        "file_path": entity.file_path,
        "start_line": entity.start_line,
        "end_line": entity.end_line,
        "is_async": entity.is_async,
        "is_private": entity.is_private,
        "is_external": entity.is_external,
    }
    for col in _OPTIONAL_COLS:
        val = getattr(entity, col, None)
        if val is not None:
            props[col] = val
    if entity.occurs:
        props["occurs"] = entity.occurs
    if entity.decorators:
        props["decorators"] = entity.decorators
    if entity.base_classes:
        props["base_classes"] = entity.base_classes
    if entity.complexity is not None:
        props["complexity"] = entity.complexity
    return props


def _rel_props(rel: CodeRelationship) -> dict:
    props: dict = {}
    if rel.file_path:
        props["file_path"] = rel.file_path
    if rel.line is not None:
        props["line"] = rel.line
    props.update(rel.metadata)
    return props


def ingest_parse_results(client, results: list[ParseResult], *, repo: str) -> dict[str, int]:
    """Repo-scoped ingest of already-parsed results (no disk parse, no git). The
    canonical v2 load path: every entity carries `repo`, every relationship is
    matched within `repo`, so the graph is isolated per repository."""
    client.apply_schema()
    entity_count = rel_count = 0
    for result in results:
        for entity in result.entities:
            client.merge_entity(
                qualified_name=entity.qualified_name, label=entity.kind.value,
                props=_entity_props(entity), repo=repo,
            )
            entity_count += 1
        for rel in result.relationships:
            client.merge_relationship(
                source_qname=rel.source_qname, target_qname=rel.target_qname,
                rel_type=rel.kind.value, props=_rel_props(rel),
                allow_unresolved=True, repo=repo,
            )
            rel_count += 1
    return {"entities": entity_count, "relationships": rel_count}


class CodeGraphIngester:
    """Orchestrates parsing source code + git history and loading into Neo4j."""

    def __init__(self, client: Neo4jClient, repo_root: Path,
                 repo_slug: str | None = None) -> None:
        self.client = client
        self.repo_root = repo_root
        self.repo = repo_slug or repo_root.name

    def ingest(self, clear: bool = False, with_git: bool = True) -> dict[str, int]:
        if clear:
            _print("[yellow]Clearing existing graph...[/yellow]")
            self.client.clear()

        self.client.apply_schema()

        _print(f"[cyan]Parsing source files in {self.repo_root}...[/cyan]")
        parse_results = parse_directory(self.repo_root)
        _print(f"  Found {len(parse_results)} files")

        entity_count = 0
        rel_count = 0

        if _RICH:
            with Progress() as progress:  # type: ignore[name-defined]
                task = progress.add_task("Loading entities...", total=len(parse_results))
                for result in parse_results:
                    for entity in result.entities:
                        self._load_entity(entity)
                        entity_count += 1
                    progress.advance(task)
            with Progress() as progress:  # type: ignore[name-defined]
                task = progress.add_task("Loading relationships...", total=len(parse_results))
                for result in parse_results:
                    for rel in result.relationships:
                        self._load_relationship(rel)
                        rel_count += 1
                    progress.advance(task)
        else:
            for result in parse_results:
                for entity in result.entities:
                    self._load_entity(entity)
                    entity_count += 1
            for result in parse_results:
                for rel in result.relationships:
                    self._load_relationship(rel)
                    rel_count += 1

        git_stats = {"authors": 0, "co_changes": 0}
        if with_git:
            git_stats = self._ingest_git()

        stats = {
            "files_parsed": len(parse_results),
            "entities": entity_count,
            "relationships": rel_count,
            **git_stats,
        }
        _print(f"[green]Ingestion complete: {stats}[/green]")
        return stats

    def _load_entity(self, entity: CodeEntity) -> None:
        self.client.merge_entity(
            qualified_name=entity.qualified_name,
            label=entity.kind.value,
            props=_entity_props(entity),
            repo=self.repo,
        )

    def _load_relationship(self, rel: CodeRelationship) -> None:
        self.client.merge_relationship(
            source_qname=rel.source_qname,
            target_qname=rel.target_qname,
            rel_type=rel.kind.value,
            props=_rel_props(rel),
            allow_unresolved=True,
            repo=self.repo,
        )

    def _ingest_git(self) -> dict[str, int]:
        try:
            analyzer = GitAnalyzer(self.repo_root)
        except Exception:
            _print("[yellow]Not a git repo — skipping git analysis[/yellow]")
            return {"authors": 0, "co_changes": 0}

        _print("[cyan]Analyzing git history...[/cyan]")

        authors = analyzer.authors()
        for author in authors:
            self.client.merge_author(
                name=author.name,
                email=author.email,
                commit_count=author.commit_count,
            )

        file_authors = analyzer.file_authors()
        for file_path, emails in file_authors.items():
            for rank, email in enumerate(emails):
                self.client.merge_authored_by(file_path, email, rank)

        co_changes = analyzer.co_changes(min_times=2)
        path_to_module = self._build_path_to_module_map()
        loaded_co = 0
        for cc in co_changes:
            qname_a = path_to_module.get(cc.file_a)
            qname_b = path_to_module.get(cc.file_b)
            if qname_a and qname_b:
                self.client.merge_co_change(qname_a, qname_b, cc.times_changed_together, cc.confidence)
                loaded_co += 1

        _print(f"  Authors: {len(authors)}, Co-changes: {loaded_co}")
        return {"authors": len(authors), "co_changes": loaded_co}

    def _build_path_to_module_map(self) -> dict[str, str]:
        results = self.client.run(
            "MATCH (e:CodeEntity) WHERE e.kind = 'Module' RETURN e.file_path AS path, e.qualified_name AS qname"
        )
        return {r["path"]: r["qname"] for r in results}


class IncrementalIngester:
    """Content-hash incremental re-ingest. parse_fn(paths)->list[ParseResult]
    is injected so unit tests need neither the JAR nor Neo4j; production wires
    it to CobolParser.parse_repo. Only added+changed files are (re)loaded; the
    stored manifest makes an unchanged re-ingest re-pay ~0 LLM/parse cost."""

    def __init__(self, client, *, repo_root: Path, repo_slug: str, parse_fn) -> None:
        self.client = client
        self.repo_root = Path(repo_root)
        self.repo_slug = repo_slug
        self.parse_fn = parse_fn

    def _discover(self) -> list[Path]:
        exts = {".cbl", ".cob", ".cobol", ".cpy"}
        return [p for p in sorted(self.repo_root.rglob("*"))
                if p.suffix.lower() in exts
                and not any(part.startswith(".") for part in
                            p.relative_to(self.repo_root).parts[:-1])]

    def ingest_incremental(self) -> dict[str, int]:
        self.client.apply_schema()
        files = self._discover()
        new_manifest = build_manifest(files, root=self.repo_root)
        old_manifest = self.client.load_manifest(self.repo_slug)
        d = diff_manifest(old=old_manifest, new=new_manifest)
        to_process = d.to_process
        processed = 0
        if to_process:
            rel_to_path = {str(p.relative_to(self.repo_root)): p for p in files}
            targets = [rel_to_path[r] for r in sorted(to_process)]
            for result in self.parse_fn(targets):
                for e in result.entities:
                    self.client.merge_entity(
                        qualified_name=e.qualified_name, label=e.kind.value,
                        props={"file_path": e.file_path,
                               "source_hash": new_manifest.get(e.file_path, "")},
                        repo=self.repo_slug)
                for rel in result.relationships:
                    self.client.merge_relationship(
                        source_qname=rel.source_qname,
                        target_qname=rel.target_qname,
                        rel_type=rel.kind.value, props=dict(rel.metadata),
                        allow_unresolved=True, repo=self.repo_slug)
                processed += 1
        self.client.save_manifest(self.repo_slug, new_manifest)
        return {"processed": processed, "skipped": len(d.unchanged),
                "added": len(d.added), "changed": len(d.changed),
                "removed": len(d.removed)}
