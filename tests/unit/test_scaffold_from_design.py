from pathlib import Path

import pytest

from cobol_modernizer.codegen.scaffold_from_design import (
    ShellFile,
    base_package_for,
    design_to_shells,
    java_identifier,
    scaffold_from_design,
)
from cobol_modernizer.technical_design.schema import (
    ApiContract,
    IntegrationContract,
    PersistenceDesign,
    TechnicalDesign,
    TechnicalService,
)


def _design() -> TechnicalDesign:
    return TechnicalDesign(
        repo_slug="acme/card-demo",
        version=3,
        database_design=[
            {
                "service": "Card Posting",
                "schema": "posting",
                "migration_location": "src/main/resources/db/migration/posting",
                "tables": [{
                    "legacy_resource": "Account Ledger",
                    "table": "account_ledger",
                    "columns": [
                        {"name": "id", "type": "BIGINT", "nullable": False,
                         "primary_key": True},
                        {"name": "legacy_record_key", "type": "VARCHAR(128)",
                         "nullable": False, "unique": True},
                        {"name": "legacy_payload", "type": "JSON", "nullable": False},
                        {"name": "updated_at", "type": "TIMESTAMP WITH TIME ZONE",
                         "nullable": False},
                    ],
                }],
            },
            {
                "service": "Statement",
                "schema": "statement",
                "tables": [{
                    "legacy_resource": "Statement Record",
                    "table": "statement_record",
                    "columns": [
                        {"name": "id", "type": "BIGINT", "nullable": False,
                         "primary_key": True},
                        {"name": "legacy_payload", "type": "JSON", "nullable": False},
                    ],
                }],
            },
        ],
        services=[
            TechnicalService(
                name="Card Posting",
                bounded_context="posting",
                deployment="microservice",
                story_ids=["S-1", "S-2"],
                api_contracts=[
                    ApiContract(name="Post Transaction", method="POST",
                                path="/transactions",
                                request_model="PostTransactionRequest",
                                response_model="PostTransactionResponse"),
                    ApiContract(name="Get Balance", method="GET",
                                path="/accounts/{id}/balance"),
                ],
                persistence=[
                    PersistenceDesign(resource="Account Ledger",
                                      access_pattern="repository",
                                      owner_service="Card Posting"),
                ],
                integrations=[
                    IntegrationContract(name="Fraud Check", style="sync",
                                        target="fraud-svc"),
                ],
            ),
            TechnicalService(
                name="Statement",
                bounded_context="statement",
                deployment="module",
                story_ids=["S-9"],
                api_contracts=[
                    ApiContract(name="Generate Statement", method="POST",
                                path="/statements"),
                ],
                persistence=[
                    PersistenceDesign(resource="Statement Record",
                                      access_pattern="read-replica",
                                      owner_service="Statement"),
                ],
                integrations=[],
            ),
        ],
    )


# ---- java_identifier helper ---------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Card Posting", "CardPosting"),
    ("post-transaction", "PostTransaction"),
    ("Account Ledger!!", "AccountLedger"),
    ("statement_record", "StatementRecord"),
])
def test_java_identifier_pascal_cases_and_sanitizes(raw, expected):
    out = java_identifier(raw)
    assert out == expected
    assert out.isidentifier()


def test_java_identifier_handles_numeric_and_empty():
    assert java_identifier("123").isidentifier()
    assert java_identifier("").isidentifier()
    assert java_identifier("@#$%").isidentifier()


# ---- base_package_for matches build.py convention ----------------------------

def test_base_package_matches_build_convention():
    from cobol_modernizer.controlplane.build import _base_package
    slug = "acme/card-demo"
    assert base_package_for(slug) == _base_package(slug)
    assert base_package_for(slug) == "com.cobolmodernizer.carddemo"


# ---- pure design_to_shells ---------------------------------------------------

def test_design_to_shells_is_pure_and_returns_shellfiles():
    shells = design_to_shells(_design())
    assert shells
    assert all(isinstance(s, ShellFile) for s in shells)
    # deterministic: same input -> same output
    assert design_to_shells(_design()) == shells
    paths = {s.path for s in shells}
    assert len(paths) == len(shells)  # no duplicate paths


def test_design_to_shells_emits_application_class():
    shells = design_to_shells(_design())
    apps = [s for s in shells if s.path.endswith("Application.java")]
    assert len(apps) == 1
    body = apps[0].content
    assert "@SpringBootApplication" in body
    assert "public static void main" in body
    assert "package com.cobolmodernizer.carddemo" in body


def test_design_to_shells_controller_per_api_contract():
    shells = design_to_shells(_design())
    controllers = [s for s in shells if s.path.endswith("Controller.java")]
    # 2 contracts on service 1 + 1 on service 2 = 3 controllers
    assert len(controllers) == 3
    names = {Path(s.path).name for s in controllers}
    assert "PostTransactionController.java" in names
    assert "GetBalanceController.java" in names
    assert "GenerateStatementController.java" in names
    joined = "\n".join(s.content for s in controllers)
    assert "@RestController" in joined
    assert "@PostMapping" in joined and "@GetMapping" in joined
    assert "/transactions" in joined
    assert "public PostTransactionResponse handle(@RequestBody PostTransactionRequest request)" in joined


def test_design_to_shells_raises_on_colliding_contract_names():
    # Two contracts that sanitize to the same Java identifier in one service would
    # overwrite each other -> a contract + its story link silently dropped. Fail loudly.
    design = TechnicalDesign(
        repo_slug="acme/card-demo",
        services=[TechnicalService(
            name="Posting", bounded_context="posting", deployment="module",
            story_ids=["S-1"],
            api_contracts=[
                ApiContract(name="Post Transaction", method="POST", path="/a"),
                ApiContract(name="post-transaction", method="GET", path="/b"),
            ])],
    )
    with pytest.raises(ValueError, match="PostTransactionController"):
        design_to_shells(design)


def test_design_to_shells_allows_same_controller_name_in_different_service_packages():
    design = TechnicalDesign(
        repo_slug="acme/card-demo",
        services=[
            TechnicalService(name="One", bounded_context="a", deployment="module",
                             story_ids=["S-1"],
                             api_contracts=[ApiContract(name="Process", method="POST",
                                                        path="/one")]),
            TechnicalService(name="Two", bounded_context="b", deployment="module",
                             story_ids=["S-2"],
                             api_contracts=[ApiContract(name="Process", method="POST",
                path="/two")]),
        ],
    )
    paths = {s.path for s in design_to_shells(design)}
    assert "src/main/java/com/cobolmodernizer/carddemo/one/api/ProcessController.java" in paths
    assert "src/main/java/com/cobolmodernizer/carddemo/two/api/ProcessController.java" in paths


def test_design_to_shells_service_per_technical_service():
    shells = design_to_shells(_design())
    services = [s for s in shells if s.path.endswith("Service.java")]
    names = {Path(s.path).name for s in services}
    assert "CardPostingService.java" in names
    assert "StatementService.java" in names
    joined = "\n".join(s.content for s in services)
    assert "@Service" in joined


def test_design_to_shells_repository_and_entity_per_resource():
    shells = design_to_shells(_design())
    names = {Path(s.path).name for s in shells}
    assert "AccountLedger.java" in names           # entity
    assert "AccountLedgerRepository.java" in names  # repository
    assert "StatementRecord.java" in names
    assert "StatementRecordRepository.java" in names
    entity = next(s for s in shells if s.path.endswith("/AccountLedger.java"))
    assert "@Entity" in entity.content
    assert '@Table(name = "account_ledger")' in entity.content
    assert 'private String legacy_payload;' in entity.content
    assert 'private OffsetDateTime updated_at;' in entity.content
    repo = next(s for s in shells if s.path.endswith("AccountLedgerRepository.java"))
    assert "JpaRepository" in repo.content
    assert "@Repository" in repo.content


def test_design_to_shells_emits_dtos_and_flyway_migrations_from_table_schema():
    shells = design_to_shells(_design())
    paths = {s.path for s in shells}
    assert "src/main/java/com/cobolmodernizer/carddemo/cardposting/api/PostTransactionRequest.java" in paths
    assert "src/main/java/com/cobolmodernizer/carddemo/cardposting/api/PostTransactionResponse.java" in paths
    assert "src/main/resources/db/migration/posting/V001__create_account_ledger.sql" in paths
    migration = next(s for s in shells if s.path.endswith("V001__create_account_ledger.sql"))
    assert "CREATE SCHEMA IF NOT EXISTS posting;" in migration.content
    assert "legacy_record_key VARCHAR(128) NOT NULL" in migration.content
    assert "UNIQUE (legacy_record_key)" in migration.content


def test_design_to_shells_carry_story_service_markers():
    shells = design_to_shells(_design())
    # Every generated class (not the Application) links to a service via a TODO marker.
    derived = [s for s in shells if s.path.endswith(".java") and not s.path.endswith("Application.java")]
    for s in derived:
        assert "// TODO(story:" in s.content
        assert "service:" in s.content


def test_design_to_shells_packages_derived_from_slug():
    shells = design_to_shells(_design())
    for s in shells:
        if s.path.endswith(".java"):
            assert "package com.cobolmodernizer.carddemo" in s.content


def test_shells_have_balanced_todo_bodies():
    shells = design_to_shells(_design())
    joined = "\n".join(s.content for s in shells)
    assert "UnsupportedOperationException" in joined
    # Controllers / services should have method bodies (balanced braces, no stub gaps).
    for s in [x for x in shells if x.path.endswith(".java")]:
        assert s.content.count("{") == s.content.count("}")
        assert s.content.rstrip().endswith("}")


def test_controllers_reference_generated_dto_types():
    shells = design_to_shells(_design())
    joined = "\n".join(s.content for s in shells)
    assert "public record PostTransactionRequest" in joined
    assert "public record PostTransactionResponse" in joined
    controllers = [s for s in shells if s.path.endswith("Controller.java")]
    assert any("PostTransactionResponse handle(@RequestBody PostTransactionRequest request)" in s.content
               for s in controllers)


# ---- disk writer -------------------------------------------------------------

def test_scaffold_from_design_writes_pom_and_shells(tmp_path):
    root = scaffold_from_design(tmp_path, _design())
    assert (root / "pom.xml").exists()
    pom = (root / "pom.xml").read_text()
    assert "<version>4.0.6</version>" in pom
    assert "<java.version>25</java.version>" in pom
    # the shells use Spring MVC + JPA, so those starters must be on the classpath
    # or the generated controllers/entities/repositories would not compile.
    assert "spring-boot-starter-web" in pom
    assert "spring-boot-starter-data-jpa" in pom
    assert "flyway-core" in pom
    # config + source roots from scaffold_module
    assert (root / "config/checkstyle.xml").exists()
    # at least one application class on disk
    apps = list(root.rglob("*Application.java"))
    assert apps
    controllers = list(root.rglob("*Controller.java"))
    assert len(controllers) == 3
    repos = list(root.rglob("*Repository.java"))
    assert len(repos) == 2
    migrations = list(root.rglob("V001__create_*.sql"))
    assert len(migrations) == 2


def test_scaffold_from_design_cleans_existing_module_before_writing(tmp_path):
    root = scaffold_from_design(tmp_path, _design())
    stale = root / "src/main/java/com/cobolmodernizer/carddemo/Stale.java"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("class Stale {}", encoding="utf-8")

    root2 = scaffold_from_design(tmp_path, _design())

    assert root2 == root
    assert not stale.exists()


def test_scaffold_from_design_is_deterministic_on_disk(tmp_path):
    r1 = scaffold_from_design(tmp_path / "a", _design())
    r2 = scaffold_from_design(tmp_path / "b", _design())

    def _rel(root: Path) -> dict[str, str]:
        return {str(p.relative_to(root)): p.read_text()
                for p in sorted(root.rglob("*")) if p.is_file()}

    assert _rel(r1) == _rel(r2)
