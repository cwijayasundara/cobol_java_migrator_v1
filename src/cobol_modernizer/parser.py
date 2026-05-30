from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

from cobol_modernizer.models import (
    CodeEntity,
    CodeRelationship,
    EntityKind,
    ParseResult,
    RelKind,
)
from cobol_modernizer.language_registry import run_repo_extractors


TREE_SITTER_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java"}
DEFAULT_EXTENSIONS = {".py", *TREE_SITTER_EXTENSIONS}


class PythonASTParser:
    """Parse a Python source file into code entities and relationships using the ast module."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def parse_file(self, file_path: Path) -> ParseResult:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        rel_path = str(file_path.relative_to(self.repo_root))
        module_qname = self._path_to_module(rel_path)

        entities: list[CodeEntity] = []
        relationships: list[CodeRelationship] = []

        module_entity = CodeEntity(
            kind=EntityKind.MODULE,
            qualified_name=module_qname,
            simple_name=file_path.stem,
            file_path=rel_path,
            start_line=1,
            end_line=len(source.splitlines()),
            docstring=ast.get_docstring(tree),
        )
        entities.append(module_entity)

        self._walk_module(tree, module_qname, rel_path, entities, relationships)
        self._extract_imports(tree, module_qname, rel_path, relationships)

        return ParseResult(entities=entities, relationships=relationships, file_path=rel_path)

    def _path_to_module(self, rel_path: str) -> str:
        return rel_path.replace("/", ".").removesuffix(".py").replace(".__init__", "")

    def _walk_module(
        self,
        tree: ast.Module,
        module_qname: str,
        rel_path: str,
        entities: list[CodeEntity],
        relationships: list[CodeRelationship],
    ) -> None:
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._extract_class(node, module_qname, rel_path, entities, relationships)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._extract_function(node, module_qname, rel_path, entities, relationships)
            elif isinstance(node, ast.Assign):
                self._extract_global_assignment(node, module_qname, rel_path, entities)

    def _extract_class(
        self,
        node: ast.ClassDef,
        parent_qname: str,
        rel_path: str,
        entities: list[CodeEntity],
        relationships: list[CodeRelationship],
    ) -> None:
        qname = f"{parent_qname}.{node.name}"
        base_names = [self._name_from_node(b) for b in node.bases if self._name_from_node(b)]
        decorator_names = [self._name_from_node(d) for d in node.decorator_list if self._name_from_node(d)]

        entity = CodeEntity(
            kind=EntityKind.CLASS,
            qualified_name=qname,
            simple_name=node.name,
            file_path=rel_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            docstring=ast.get_docstring(node),
            is_private=node.name.startswith("_"),
            decorators=decorator_names,
            base_classes=base_names,
        )

        if issubclass(type(node), ast.ClassDef) and any(
            self._name_from_node(b) in ("str, Enum", "Enum", "IntEnum") for b in node.bases
        ):
            entity.kind = EntityKind.ENUM
        entities.append(entity)

        relationships.append(CodeRelationship(
            source_qname=parent_qname,
            target_qname=qname,
            kind=RelKind.DEFINES,
            file_path=rel_path,
            line=node.lineno,
        ))

        for base in base_names:
            relationships.append(CodeRelationship(
                source_qname=qname,
                target_qname=base,
                kind=RelKind.INHERITS,
                file_path=rel_path,
                line=node.lineno,
            ))

        for dec in decorator_names:
            relationships.append(CodeRelationship(
                source_qname=dec,
                target_qname=qname,
                kind=RelKind.DECORATES,
                file_path=rel_path,
                line=node.lineno,
            ))

        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._extract_method(child, qname, rel_path, entities, relationships)

    def _extract_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent_qname: str,
        rel_path: str,
        entities: list[CodeEntity],
        relationships: list[CodeRelationship],
    ) -> None:
        qname = f"{parent_qname}.{node.name}"
        decorator_names = [self._name_from_node(d) for d in node.decorator_list if self._name_from_node(d)]
        sig = self._build_signature(node)

        entity = CodeEntity(
            kind=EntityKind.FUNCTION,
            qualified_name=qname,
            simple_name=node.name,
            file_path=rel_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            docstring=ast.get_docstring(node),
            signature=sig,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_private=node.name.startswith("_"),
            decorators=decorator_names,
            complexity=self._cyclomatic_complexity(node),
        )
        entities.append(entity)

        relationships.append(CodeRelationship(
            source_qname=parent_qname,
            target_qname=qname,
            kind=RelKind.DEFINES,
            file_path=rel_path,
            line=node.lineno,
        ))

        for dec in decorator_names:
            relationships.append(CodeRelationship(
                source_qname=dec,
                target_qname=qname,
                kind=RelKind.DECORATES,
                file_path=rel_path,
                line=node.lineno,
            ))

        self._extract_calls_and_raises(node, qname, rel_path, relationships)

    def _extract_method(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_qname: str,
        rel_path: str,
        entities: list[CodeEntity],
        relationships: list[CodeRelationship],
    ) -> None:
        qname = f"{class_qname}.{node.name}"
        decorator_names = [self._name_from_node(d) for d in node.decorator_list if self._name_from_node(d)]
        sig = self._build_signature(node)

        entity = CodeEntity(
            kind=EntityKind.METHOD,
            qualified_name=qname,
            simple_name=node.name,
            file_path=rel_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            docstring=ast.get_docstring(node),
            signature=sig,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_private=node.name.startswith("_"),
            decorators=decorator_names,
            complexity=self._cyclomatic_complexity(node),
        )
        entities.append(entity)

        relationships.append(CodeRelationship(
            source_qname=class_qname,
            target_qname=qname,
            kind=RelKind.CONTAINS,
            file_path=rel_path,
            line=node.lineno,
        ))

        for dec in decorator_names:
            relationships.append(CodeRelationship(
                source_qname=dec,
                target_qname=qname,
                kind=RelKind.DECORATES,
                file_path=rel_path,
                line=node.lineno,
            ))

        self._extract_calls_and_raises(node, qname, rel_path, relationships)

    def _extract_global_assignment(
        self,
        node: ast.Assign,
        module_qname: str,
        rel_path: str,
        entities: list[CodeEntity],
    ) -> None:
        for target in node.targets:
            name = self._name_from_node(target)
            if not name:
                continue
            kind = EntityKind.CONSTANT if name.isupper() else EntityKind.GLOBAL_VAR
            entities.append(CodeEntity(
                kind=kind,
                qualified_name=f"{module_qname}.{name}",
                simple_name=name,
                file_path=rel_path,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            ))

    def _extract_imports(
        self,
        tree: ast.Module,
        module_qname: str,
        rel_path: str,
        relationships: list[CodeRelationship],
    ) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    relationships.append(CodeRelationship(
                        source_qname=module_qname,
                        target_qname=alias.name,
                        kind=RelKind.IMPORTS,
                        file_path=rel_path,
                        line=node.lineno,
                    ))
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for alias in node.names:
                    target = f"{base}.{alias.name}" if base else alias.name
                    relationships.append(CodeRelationship(
                        source_qname=module_qname,
                        target_qname=target,
                        kind=RelKind.IMPORTS,
                        file_path=rel_path,
                        line=node.lineno,
                    ))

    def _extract_calls_and_raises(
        self,
        node: ast.AST,
        caller_qname: str,
        rel_path: str,
        relationships: list[CodeRelationship],
    ) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                callee = self._name_from_node(child.func)
                if callee:
                    relationships.append(CodeRelationship(
                        source_qname=caller_qname,
                        target_qname=callee,
                        kind=RelKind.CALLS,
                        file_path=rel_path,
                        line=getattr(child, "lineno", None),
                    ))
            elif isinstance(child, ast.Raise) and child.exc:
                exc_name = self._name_from_node(child.exc)
                if not exc_name and isinstance(child.exc, ast.Call):
                    exc_name = self._name_from_node(child.exc.func)
                if exc_name:
                    relationships.append(CodeRelationship(
                        source_qname=caller_qname,
                        target_qname=exc_name,
                        kind=RelKind.RAISES,
                        file_path=rel_path,
                        line=getattr(child, "lineno", None),
                    ))

    def _build_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = []
        for arg in node.args.args:
            annotation = ""
            if arg.annotation:
                annotation = f": {ast.unparse(arg.annotation)}"
            args.append(f"{arg.arg}{annotation}")
        ret = ""
        if node.returns:
            ret = f" -> {ast.unparse(node.returns)}"
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        return f"{prefix}def {node.name}({', '.join(args)}){ret}"

    def _cyclomatic_complexity(self, node: ast.AST) -> int:
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    @staticmethod
    def _name_from_node(node: ast.AST | None) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            value = PythonASTParser._name_from_node(node.value)
            return f"{value}.{node.attr}" if value else node.attr
        if isinstance(node, ast.Call):
            return PythonASTParser._name_from_node(node.func)
        if isinstance(node, ast.Subscript):
            return PythonASTParser._name_from_node(node.value)
        return None


class TreeSitterCodeParser:
    """Parse non-Python source files into the shared code graph model using Tree-sitter."""

    CLASS_NODES = {
        "class_declaration",
        "interface_declaration",
        "struct_item",
        "struct_type",
        "type_spec",
    }
    FUNCTION_NODES = {
        "function_declaration",
        "function_item",
        "method_declaration",
        "method_definition",
    }
    METHOD_NODES = {"method_declaration", "method_definition"}
    IMPORT_NODES = {
        "import_statement",
        "import_declaration",
        "use_declaration",
    }
    CALL_NODES = {
        "call_expression",
        "method_invocation",
        "macro_invocation",
    }

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def parse_file(self, file_path: Path) -> ParseResult:
        source = file_path.read_bytes()
        rel_path = str(file_path.relative_to(self.repo_root))
        module_qname = self._path_to_module(rel_path)
        root = self._parse_tree(file_path.suffix, source).root_node

        entities = [
            CodeEntity(
                kind=EntityKind.MODULE,
                qualified_name=module_qname,
                simple_name=file_path.stem,
                file_path=rel_path,
                start_line=1,
                end_line=max(1, len(source.decode("utf-8", errors="ignore").splitlines())),
            )
        ]
        relationships: list[CodeRelationship] = []

        self._extract_imports(root, source, module_qname, rel_path, relationships)
        self._extract_declarations(root, source, module_qname, rel_path, entities, relationships)
        return ParseResult(entities=entities, relationships=relationships, file_path=rel_path)

    @staticmethod
    def supports(file_path: Path) -> bool:
        return file_path.suffix in TREE_SITTER_EXTENSIONS

    @staticmethod
    def _language_for_suffix(suffix: str) -> Any:
        from tree_sitter import Language

        if suffix in {".js", ".jsx"}:
            import tree_sitter_javascript

            return Language(tree_sitter_javascript.language())
        if suffix == ".go":
            import tree_sitter_go

            return Language(tree_sitter_go.language())
        if suffix == ".rs":
            import tree_sitter_rust

            return Language(tree_sitter_rust.language())
        if suffix == ".java":
            import tree_sitter_java

            return Language(tree_sitter_java.language())
        if suffix == ".ts":
            import tree_sitter_typescript

            return Language(tree_sitter_typescript.language_typescript())
        if suffix == ".tsx":
            import tree_sitter_typescript

            return Language(tree_sitter_typescript.language_tsx())
        raise ValueError(f"Unsupported Tree-sitter suffix: {suffix}")

    def _parse_tree(self, suffix: str, source: bytes) -> Any:
        from tree_sitter import Parser

        parser = Parser(self._language_for_suffix(suffix))
        return parser.parse(source)

    def _extract_declarations(
        self,
        node: Any,
        source: bytes,
        parent_qname: str,
        rel_path: str,
        entities: list[CodeEntity],
        relationships: list[CodeRelationship],
        in_class: bool = False,
    ) -> None:
        for child in self._named_children(node):
            if child.type in self.CLASS_NODES:
                name = self._declaration_name(child, source)
                if name:
                    qname = f"{parent_qname}.{name}"
                    entity = CodeEntity(
                        kind=EntityKind.CLASS,
                        qualified_name=qname,
                        simple_name=name,
                        file_path=rel_path,
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        is_private=name.startswith("_"),
                    )
                    entities.append(entity)
                    relationships.append(CodeRelationship(
                        source_qname=parent_qname,
                        target_qname=qname,
                        kind=RelKind.DEFINES if not in_class else RelKind.CONTAINS,
                        file_path=rel_path,
                        line=child.start_point[0] + 1,
                    ))
                    self._extract_calls(child, source, qname, rel_path, relationships)
                    self._extract_declarations(
                        child, source, qname, rel_path, entities, relationships, in_class=True
                    )
                continue

            if child.type in self.FUNCTION_NODES:
                name = self._declaration_name(child, source)
                if name:
                    qname = f"{parent_qname}.{name}"
                    kind = EntityKind.METHOD if in_class or child.type in self.METHOD_NODES else EntityKind.FUNCTION
                    entities.append(CodeEntity(
                        kind=kind,
                        qualified_name=qname,
                        simple_name=name,
                        file_path=rel_path,
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        signature=self._signature(child, source),
                        is_private=name.startswith("_"),
                    ))
                    relationships.append(CodeRelationship(
                        source_qname=parent_qname,
                        target_qname=qname,
                        kind=RelKind.CONTAINS if kind == EntityKind.METHOD else RelKind.DEFINES,
                        file_path=rel_path,
                        line=child.start_point[0] + 1,
                    ))
                    self._extract_calls(child, source, qname, rel_path, relationships)
                continue

            self._extract_declarations(
                child, source, parent_qname, rel_path, entities, relationships, in_class=in_class
            )

    def _extract_imports(
        self,
        node: Any,
        source: bytes,
        module_qname: str,
        rel_path: str,
        relationships: list[CodeRelationship],
    ) -> None:
        for child in self._walk(node):
            if child.type not in self.IMPORT_NODES:
                continue
            target = self._import_target(child, source)
            if not target:
                continue
            relationships.append(CodeRelationship(
                source_qname=module_qname,
                target_qname=target,
                kind=RelKind.IMPORTS,
                file_path=rel_path,
                line=child.start_point[0] + 1,
            ))

    def _extract_calls(
        self,
        node: Any,
        source: bytes,
        caller_qname: str,
        rel_path: str,
        relationships: list[CodeRelationship],
    ) -> None:
        for child in self._walk(node):
            if child.type not in self.CALL_NODES:
                continue
            name = self._call_name(child, source)
            if not name:
                continue
            relationships.append(CodeRelationship(
                source_qname=caller_qname,
                target_qname=name,
                kind=RelKind.CALLS,
                file_path=rel_path,
                line=child.start_point[0] + 1,
            ))

    def _declaration_name(self, node: Any, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return self._text(source, name_node)
        for child in self._named_children(node):
            if child.type in {"identifier", "type_identifier", "property_identifier"}:
                return self._text(source, child)
        return None

    def _signature(self, node: Any, source: bytes) -> str:
        text = self._text(source, node).strip()
        body = node.child_by_field_name("body")
        if body is not None:
            text = text[: max(0, body.start_byte - node.start_byte)].strip()
        return " ".join(text.split())

    def _import_target(self, node: Any, source: bytes) -> str | None:
        string_node = self._first_descendant(node, {"string_fragment", "interpreted_string_literal_content"})
        if string_node is not None:
            return self._text(source, string_node)
        scoped = self._first_descendant(node, {"scoped_identifier"})
        if scoped is not None:
            return self._text(source, scoped)
        identifier = self._first_descendant(node, {"identifier", "type_identifier", "package_identifier"})
        if identifier is not None:
            return self._text(source, identifier)
        return None

    def _call_name(self, node: Any, source: bytes) -> str | None:
        function = node.child_by_field_name("function")
        if function is not None:
            return self._expression_name(function, source)
        name = node.child_by_field_name("name")
        if name is not None:
            return self._expression_name(name, source)
        # Rust macro invocations expose the macro identifier as a direct child.
        for child in self._named_children(node):
            if child.type in {"identifier", "scoped_identifier"}:
                name = self._expression_name(child, source)
                return f"{name}!" if node.type == "macro_invocation" and name else name
        return None

    def _expression_name(self, node: Any, source: bytes) -> str | None:
        if node.type in {
            "identifier",
            "property_identifier",
            "field_identifier",
            "type_identifier",
            "package_identifier",
        }:
            return self._text(source, node)
        if node.type in {"member_expression", "selector_expression", "field_expression"}:
            parts = [
                self._expression_name(child, source)
                for child in self._named_children(node)
                if child.type
                in {
                    "identifier",
                    "property_identifier",
                    "field_identifier",
                    "type_identifier",
                    "package_identifier",
                    "member_expression",
                    "selector_expression",
                    "field_expression",
                }
            ]
            return ".".join(part for part in parts if part)
        if node.type == "scoped_identifier":
            return self._text(source, node).replace("::", ".")
        return self._text(source, node)

    def _first_descendant(self, node: Any, types: set[str]) -> Any | None:
        for child in self._walk(node):
            if child.type in types:
                return child
        return None

    def _walk(self, node: Any) -> list[Any]:
        results = [node]
        for child in self._named_children(node):
            results.extend(self._walk(child))
        return results

    @staticmethod
    def _named_children(node: Any) -> list[Any]:
        return [child for child in node.children if child.is_named]

    @staticmethod
    def _text(source: bytes, node: Any) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

    def _path_to_module(self, rel_path: str) -> str:
        return rel_path.replace("/", ".").rsplit(".", 1)[0]


def parse_directory(repo_root: Path, extensions: set[str] | None = None) -> list[ParseResult]:
    if extensions is None:
        extensions = DEFAULT_EXTENSIONS
    python_parser = PythonASTParser(repo_root)
    tree_sitter_parser = TreeSitterCodeParser(repo_root)
    results: list[ParseResult] = []
    for path in sorted(repo_root.rglob("*")):
        if path.suffix not in extensions:
            continue
        rel_parts = path.relative_to(repo_root).parts
        if any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv", ".venv")
               for part in rel_parts):
            continue
        try:
            if path.suffix == ".py":
                results.append(python_parser.parse_file(path))
            elif tree_sitter_parser.supports(path):
                results.append(tree_sitter_parser.parse_file(path))
        except SyntaxError:
            continue
    results.extend(run_repo_extractors(repo_root))
    return results
