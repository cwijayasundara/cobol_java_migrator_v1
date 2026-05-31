"""Emit the ArchUnit JUnit5 test that pins the bounded-context layering. The
architecture rule becomes a compiled, runnable assertion in `mvn verify`."""
from __future__ import annotations

from cobol_modernizer.design.schema import ServiceDesign

_TEMPLATE = '''package {pkg};

import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;
import static com.tngtech.archunit.library.Architectures.layeredArchitecture;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

@AnalyzeClasses(packages = "{pkg}")
class ArchitectureTest {{

    @ArchTest
    static final ArchRule layering = layeredArchitecture().consideringAllDependencies()
        .layer("Controller").definedBy("{pkg}.api..")
        .layer("Service").definedBy("{pkg}.service..")
        .layer("Repository").definedBy("{pkg}.repository..")
        .whereLayer("Controller").mayNotBeAccessedByAnyLayer()
        .whereLayer("Service").mayOnlyBeAccessedByLayers("Controller")
        .whereLayer("Repository").mayOnlyBeAccessedByLayers("Service");

    @ArchTest
    static final ArchRule repository_only_from_service =
        noClasses().that().resideInAPackage("{pkg}.api..")
            .should().dependOnClassesThat().resideInAPackage("{pkg}.repository..");
}}
'''


def render_archunit_test(design: ServiceDesign, *, base_package: str) -> str:
    return _TEMPLATE.format(pkg=base_package)
