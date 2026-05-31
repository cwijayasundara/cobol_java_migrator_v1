"""Deterministic Spring Boot 3.3 / Java 25 Maven module scaffold with all four
quality gates wired (ArchUnit, SpotBugs+FindSecBugs, Error Prone, Checkstyle).
No LLM here — the agent only fills in src code/tests."""
from __future__ import annotations

from pathlib import Path

_POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.4</version>
  </parent>
  <groupId>com.cobolmodernizer</groupId>
  <artifactId>{module}</artifactId>
  <version>0.1.0</version>
  <properties>
    <java.version>25</java.version>
    <maven.compiler.release>25</maven.compiler.release>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-test</artifactId>
      <scope>test</scope>
    </dependency>
    <dependency>
      <groupId>com.tngtech.archunit</groupId>
      <artifactId>archunit-junit5</artifactId>
      <version>1.3.0</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <configuration>
          <compilerArgs>
            <arg>-XDcompilePolicy=simple</arg>
            <arg>-Xplugin:ErrorProne</arg>
          </compilerArgs>
          <annotationProcessorPaths>
            <path>
              <groupId>com.google.errorprone</groupId>
              <artifactId>error_prone_core</artifactId>
              <version>2.28.0</version>
            </path>
          </annotationProcessorPaths>
        </configuration>
      </plugin>
      <plugin>
        <groupId>com.github.spotbugs</groupId>
        <artifactId>spotbugs-maven-plugin</artifactId>
        <version>4.8.6.2</version>
        <configuration>
          <effort>Max</effort>
          <threshold>Low</threshold>
          <plugins>
            <plugin>
              <groupId>com.h3xstream.findsecbugs</groupId>
              <artifactId>findsecbugs-plugin</artifactId>
              <version>1.13.0</version>
            </plugin>
          </plugins>
        </configuration>
        <executions>
          <execution>
            <phase>verify</phase>
            <goals><goal>check</goal></goals>
          </execution>
        </executions>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-checkstyle-plugin</artifactId>
        <version>3.5.0</version>
        <configuration>
          <configLocation>config/checkstyle.xml</configLocation>
          <failOnViolation>true</failOnViolation>
        </configuration>
        <executions>
          <execution>
            <phase>verify</phase>
            <goals><goal>check</goal></goals>
          </execution>
        </executions>
      </plugin>
    </plugins>
  </build>
</project>
"""

_CHECKSTYLE = """<?xml version="1.0"?>
<!DOCTYPE module PUBLIC "-//Checkstyle//DTD Checkstyle Configuration 1.3//EN"
 "https://checkstyle.org/dtds/configuration_1_3.dtd">
<module name="Checker">
  <module name="TreeWalker">
    <module name="UnusedImports"/>
    <module name="MissingOverride"/>
    <module name="EmptyBlock"/>
  </module>
</module>
"""


def scaffold_module(parent: Path, *, module: str, base_package: str) -> Path:
    root = Path(parent) / module
    pkg = base_package.replace(".", "/")
    (root / f"src/main/java/{pkg}").mkdir(parents=True, exist_ok=True)
    (root / f"src/test/java/{pkg}").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "pom.xml").write_text(_POM.format(module=module), encoding="utf-8")
    (root / "config/checkstyle.xml").write_text(_CHECKSTYLE, encoding="utf-8")
    return root
