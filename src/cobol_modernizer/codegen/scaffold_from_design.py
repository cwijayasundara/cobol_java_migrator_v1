"""Deterministic Spring Boot 4.0.6 / Java 25 scaffold derived from a TechnicalDesign.

NO LLM. Given a `TechnicalDesign` (the target architecture: services, API/persistence/
integration contracts) this emits a compilable Spring Boot skeleton — one controller
per ApiContract, one service per TechnicalService, an entity + repository per
PersistenceDesign.resource, plus a `@SpringBootApplication` entrypoint. Every shell
is a TODO-bodied stub (returns defaults / throws `UnsupportedOperationException`) that
COMPILES as-is, so `mvn test` is green before any story fills in real behavior. The
story runner (Task 6) later replaces these bodies one story at a time.

The pure part (`design_to_shells`) returns an in-memory mapping of relative-path ->
file-content and is fully testable without disk I/O. `scaffold_from_design` is the
thin disk-writing wrapper: it reuses `scaffold_module` for the Maven layout + the four
quality gates, then writes the shells on top. Same TechnicalDesign -> same files
(deterministic, for resume/caching)."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from pydantic import BaseModel

from cobol_modernizer.codegen.scaffold import scaffold_module
from cobol_modernizer.technical_design.schema import (
    ApiContract,
    PersistenceDesign,
    TechnicalDesign,
    TechnicalService,
)

_PKG_SAFE = re.compile(r"[^a-z0-9]+")
_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")


class ShellFile(BaseModel):
    """One generated Java source file: a path relative to the module root and its
    content. Frozen so the pure result is hashable/comparable for determinism tests."""

    model_config = {"frozen": True}

    path: str
    content: str


def base_package_for(slug: str) -> str:
    """The Maven/Java base package for a repo slug. Mirrors
    `controlplane.build._base_package` exactly so the design scaffold and the legacy
    build path stay package-compatible: `com.cobolmodernizer.{sanitized-last-segment}`."""
    leaf = _PKG_SAFE.sub("", slug.split("/")[-1].lower()) or "app"
    return f"com.cobolmodernizer.{leaf}"


def module_name_for(slug: str) -> str:
    """The Maven artifactId / module directory name for a repo slug, matching the
    legacy build convention: the sanitized last slug segment (hyphenated)."""
    return _PKG_SAFE.sub("-", slug.split("/")[-1].lower()) or "app"


def java_identifier(raw: str) -> str:
    """PascalCase a free-text name into a valid Java type identifier. Splits on any
    non-alphanumeric run, capitalizes each chunk, drops empties. Defends against names
    that aren't valid identifiers: empty/all-symbol input -> `Generated`; a
    leading-digit result is prefixed so it still starts with a letter."""
    parts = [p for p in _NON_ALNUM.split(raw) if p]
    ident = "".join(p[:1].upper() + p[1:] for p in parts)
    if not ident:
        return "Generated"
    if ident[0].isdigit():
        ident = "N" + ident
    return ident


def _story_ids(service: TechnicalService) -> str:
    """The service's story ids as a comma-joined string (`none` when it has none).
    Deterministic (input order); used in TODO markers + UnsupportedOperationException
    messages so every shell links back to the stories that will fill it in."""
    return ",".join(service.story_ids) or "none"


def _marker(service: TechnicalService) -> str:
    """A `// TODO(story:<ids> service:<name>)` marker linking a shell back to the
    service/story ids it was derived from. Story ids are deterministic (input order)."""
    return f"// TODO(story:{_story_ids(service)} service:{service.name})"


def _http_mapping(method: str) -> str:
    """The Spring MVC mapping annotation simple-name for an HTTP method (default
    `RequestMapping` for anything unrecognized)."""
    return {
        "GET": "GetMapping",
        "POST": "PostMapping",
        "PUT": "PutMapping",
        "DELETE": "DeleteMapping",
        "PATCH": "PatchMapping",
    }.get(method.upper(), "RequestMapping")


def _java_path(pkg: str, class_name: str) -> str:
    pkg_dir = pkg.replace(".", "/")
    return f"src/main/java/{pkg_dir}/{class_name}.java"


def _resource_slug(raw: str) -> str:
    return _PKG_SAFE.sub("_", raw.lower()).strip("_") or "resource"


def _service_root_package(base_pkg: str, service: TechnicalService) -> str:
    leaf = service.name[:-8] if service.name.endswith("-service") else service.name
    return f"{base_pkg}.{_PKG_SAFE.sub('', leaf.lower()) or 'service'}"


def _request_type(contract: ApiContract) -> str:
    return java_identifier(contract.request_model or f"{contract.name}Request")


def _response_type(contract: ApiContract) -> str:
    return java_identifier(contract.response_model or f"{contract.name}Response")


def _java_column_type(sql_type: str) -> str:
    t = sql_type.upper()
    if "BIGINT" in t:
        return "Long"
    if "INT" in t:
        return "Integer"
    if "DECIMAL" in t or "NUMERIC" in t:
        return "java.math.BigDecimal"
    if "TIMESTAMP" in t:
        return "java.time.OffsetDateTime"
    if "DATE" in t:
        return "java.time.LocalDate"
    if "BOOL" in t:
        return "Boolean"
    return "String"


def _db_table_for(design: TechnicalDesign, service: TechnicalService,
                  persistence: PersistenceDesign) -> dict:
    for db in design.database_design:
        if not isinstance(db, dict) or db.get("service") != service.name:
            continue
        for table in db.get("tables", []) if isinstance(db.get("tables"), list) else []:
            if isinstance(table, dict) and table.get("legacy_resource") == persistence.resource:
                return table
    return {}


def _db_schema_for(design: TechnicalDesign, service: TechnicalService) -> dict:
    for db in design.database_design:
        if isinstance(db, dict) and db.get("service") == service.name:
            return db
    return {}


def _application_shell(pkg: str, app_class: str) -> ShellFile:
    content = f"""package {pkg};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class {app_class} {{
    public static void main(String[] args) {{
        SpringApplication.run({app_class}.class, args);
    }}
}}
"""
    return ShellFile(path=_java_path(pkg, app_class), content=content)


def _dto_shell(pkg: str, service: TechnicalService, class_name: str) -> ShellFile:
    content = f"""package {pkg};

{_marker(service)}
public record {class_name}() {{
}}
"""
    return ShellFile(path=_java_path(pkg, class_name), content=content)


def _controller_shell(pkg: str, service: TechnicalService,
                      contract: ApiContract) -> ShellFile:
    class_name = java_identifier(contract.name) + "Controller"
    mapping = _http_mapping(contract.method)
    path = contract.path or "/"
    request_type = _request_type(contract)
    response_type = _response_type(contract)
    body_arg = "" if contract.method.upper() == "GET" else f"@RequestBody {request_type} request"
    response_expr = f"new {response_type}()"
    # Import only the mapping annotation actually used, so the checkstyle UnusedImports
    # gate stays green. RequestMapping is the @{mapping} for unrecognized methods, so
    # avoid importing it twice.
    mapping_import = (
        "" if mapping == "RequestMapping"
        else f"import org.springframework.web.bind.annotation.{mapping};\n")
    request_body_import = (
        "import org.springframework.web.bind.annotation.RequestBody;\n"
        if body_arg else "")
    content = f"""package {pkg};

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
{mapping_import}
{request_body_import}
{_marker(service)}
@RestController
@RequestMapping("{path}")
public class {class_name} {{

    @{mapping}
    public {response_type} handle({body_arg}) {{
        // TODO: implement API contract '{contract.name}' ({contract.method} {path})
        return {response_expr};
    }}
}}
"""
    return ShellFile(path=_java_path(pkg, class_name), content=content)


def _service_shell(pkg: str, service: TechnicalService) -> ShellFile:
    class_name = java_identifier(service.name) + "Service"
    content = f"""package {pkg};

import org.springframework.stereotype.Service;

{_marker(service)}
@Service
public class {class_name} {{

    public Object process() {{
        // TODO: implement bounded context '{service.bounded_context}'
        throw new UnsupportedOperationException(
            "TODO: story {_story_ids(service)} — {service.name}");
    }}
}}
"""
    return ShellFile(path=_java_path(pkg, class_name), content=content)


def _entity_shell(pkg: str, service: TechnicalService,
                  persistence: PersistenceDesign, table: dict) -> ShellFile:
    class_name = java_identifier(persistence.resource)
    table_name = str(table.get("table") or _resource_slug(persistence.resource))
    columns = table.get("columns") if isinstance(table.get("columns"), list) else []
    if not columns:
        columns = [{"name": "id", "type": "BIGINT", "primary_key": True, "nullable": False}]

    imports = ["import jakarta.persistence.Column;", "import jakarta.persistence.Entity;",
               "import jakarta.persistence.Id;", "import jakarta.persistence.Table;"]
    fields: list[str] = []
    accessors: list[str] = []
    for column in columns:
        if not isinstance(column, dict) or not column.get("name"):
            continue
        name = str(column["name"])
        field = _PKG_SAFE.sub("_", name.lower()).strip("_") or "value"
        java_type = _java_column_type(str(column.get("type", "VARCHAR")))
        col_bits = [f'name = "{name}"']
        if column.get("nullable") is False:
            col_bits.append("nullable = false")
        if column.get("unique"):
            col_bits.append("unique = true")
        if java_type.startswith("java."):
            imports.append(f"import {java_type};")
            java_type = java_type.rsplit(".", 1)[1]
        annotation = "@Id" if column.get("primary_key") else f"@Column({', '.join(col_bits)})"
        fields.append(f"    {annotation}\n    private {java_type} {field};")
        method = java_identifier(field)
        accessors.append(f"""
    public {java_type} get{method}() {{
        return this.{field};
    }}

    public void set{method}({java_type} {field}) {{
        this.{field} = {field};
    }}
""")
    import_block = "\n".join(sorted(set(imports)))
    content = f"""package {pkg};

{import_block}

{_marker(service)}
@Entity
@Table(name = "{table_name}")
public class {class_name} {{

{chr(10).join(fields)}
{''.join(accessors)}
}}
"""
    return ShellFile(path=_java_path(pkg, class_name), content=content)


def _repository_shell(pkg: str, service: TechnicalService,
                      persistence: PersistenceDesign) -> ShellFile:
    entity = java_identifier(persistence.resource)
    class_name = entity + "Repository"
    content = f"""package {pkg};

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

{_marker(service)}
@Repository
public interface {class_name} extends JpaRepository<{entity}, Long> {{
    // TODO: access pattern '{persistence.access_pattern}' for resource '{persistence.resource}'
}}
"""
    return ShellFile(path=_java_path(pkg, class_name), content=content)


def _migration_shell(design: TechnicalDesign, service: TechnicalService,
                     persistence: PersistenceDesign, table: dict) -> ShellFile | None:
    db = _db_schema_for(design, service)
    schema = str(db.get("schema") or _resource_slug(service.name))
    location = str(db.get("migration_location") or f"src/main/resources/db/migration/{schema}")
    table_name = str(table.get("table") or _resource_slug(persistence.resource))
    columns = table.get("columns") if isinstance(table.get("columns"), list) else []
    if not columns:
        return None
    lines = [f"CREATE SCHEMA IF NOT EXISTS {schema};", "",
             f"CREATE TABLE IF NOT EXISTS {schema}.{table_name} ("]
    col_defs: list[str] = []
    constraints: list[str] = []
    for column in columns:
        if not isinstance(column, dict) or not column.get("name"):
            continue
        name = str(column["name"])
        sql_type = str(column.get("type") or "VARCHAR(255)")
        bits = [f"  {name} {sql_type}"]
        if column.get("primary_key"):
            bits.append("PRIMARY KEY")
        if column.get("nullable") is False:
            bits.append("NOT NULL")
        if column.get("unique") and not column.get("primary_key"):
            constraints.append(f"  UNIQUE ({name})")
        col_defs.append(" ".join(bits))
    lines.append(",\n".join(col_defs + constraints))
    lines.append(");")
    content = "\n".join(lines) + "\n"
    return ShellFile(
        path=f"{location.rstrip('/')}/V001__create_{table_name}.sql",
        content=content)


def design_to_shells(design: TechnicalDesign) -> list[ShellFile]:
    """Pure: a TechnicalDesign -> the deterministic set of Java shell files (relative
    path + content). No disk I/O. Emits a `@SpringBootApplication` entrypoint plus, per
    service, a controller per ApiContract, one service class, and an entity+repository
    per PersistenceDesign.resource. Order follows the design (services -> contracts ->
    persistence) so output is stable.

    Raises ValueError on a class-name collision — two inputs that sanitize to the same
    Java identifier (e.g. contracts "Post Transaction" and "post-transaction", or a
    "Process" contract in two services) would overwrite each other and silently drop a
    contract/service and its story link. That's an ambiguous design the upstream stage
    must disambiguate, so we fail loudly with the colliding class names rather than
    dropping work."""
    pkg = base_package_for(design.repo_slug)
    app_class = java_identifier(module_name_for(design.repo_slug)) + "Application"

    shells: list[ShellFile] = [_application_shell(pkg, app_class)]
    for service in design.services:
        root_pkg = _service_root_package(pkg, service)
        api_pkg = f"{root_pkg}.api"
        app_pkg = f"{root_pkg}.application"
        persistence_pkg = f"{root_pkg}.infrastructure.persistence"
        for contract in service.api_contracts:
            shells.append(_dto_shell(api_pkg, service, _request_type(contract)))
            shells.append(_dto_shell(api_pkg, service, _response_type(contract)))
            shells.append(_controller_shell(api_pkg, service, contract))
        shells.append(_service_shell(app_pkg, service))
        for persistence in service.persistence:
            table = _db_table_for(design, service, persistence)
            shells.append(_entity_shell(persistence_pkg, service, persistence, table))
            shells.append(_repository_shell(persistence_pkg, service, persistence))
            migration = _migration_shell(design, service, persistence, table)
            if migration is not None:
                shells.append(migration)

    by_path: dict[str, ShellFile] = {}
    collisions: list[str] = []
    for shell in shells:
        if shell.path in by_path:
            collisions.append(Path(shell.path).stem)
        else:
            by_path[shell.path] = shell
    if collisions:
        raise ValueError(
            "TechnicalDesign produces colliding Java class names "
            f"(distinct contracts/services/resources that sanitize to the same "
            f"identifier): {', '.join(sorted(set(collisions)))}. Disambiguate the "
            "names in the design.")
    return list(by_path.values())


def scaffold_from_design(parent: Path, design: TechnicalDesign) -> Path:
    """Disk-writing wrapper: scaffold the Maven module (layout + four quality gates via
    `scaffold_module`) under `parent`, then write the design-derived Java shells into it.
    Returns the module root. Deterministic: same TechnicalDesign -> same files."""
    base_package = base_package_for(design.repo_slug)
    module = module_name_for(design.repo_slug)
    root = Path(parent) / module
    if root.exists():
        shutil.rmtree(root)
    root = scaffold_module(Path(parent), module=module, base_package=base_package)
    for shell in design_to_shells(design):
        dest = root / shell.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(shell.content, encoding="utf-8")
    return root
