"""Thin CLI entry-point for the cobol-modernizer toolchain.

Usage
-----
    uv run python -m cobol_modernizer.cli baseline \\
        --repo <path-to-repo> \\
        --out  <path-to-output.json>

    # with the real COBOL extractor JAR
    COBOL_EXTRACTOR_JAR=tools/cobol-extractor/target/cobol-extractor.jar \\
    JAVA_HOME=/opt/homebrew/opt/openjdk@25/... \\
    COBOL_MOD_COPYBOOK_DIRS=app/cpy,app/cpy-bms \\
    uv run python -m cobol_modernizer.cli baseline \\
        --repo /path/to/aws-mf-mod-carddemo \\
        --out  ./benchmark_out/carddemo_baseline.json

On a missing JAR or JVM the command still emits a report (zero entities,
graceful degradation) and exits 0.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _cmd_baseline(args: argparse.Namespace) -> int:
    """Run the CardDemo Phase-0 baseline benchmark and write the JSON report."""
    from cobol_modernizer.benchmark.carddemo_baseline import run_baseline, write_report
    from cobol_modernizer.cobol.parser import CobolParser

    repo_root = Path(args.repo).resolve()
    out_path = Path(args.out).resolve()

    if not repo_root.exists():
        logger.error("repo path does not exist: %s", repo_root)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a CobolParser from env-vars (JAR path, copybook dirs, JAVA_HOME).
    # CobolParser.from_env already handles graceful degradation: if the JAR or
    # JVM is absent, parse_repo() returns [] and logs a WARNING.
    parser = CobolParser.from_env(repo_root)
    parse_fn = lambda root: parser.parse_repo()  # noqa: E731

    logger.info("Running Phase-0 baseline benchmark on %s …", repo_root)
    report = run_baseline(repo_root, parse_fn=parse_fn)
    write_report(report, out_path)

    logger.info("Report written to %s", out_path)
    logger.info(
        "files_discovered=%d  programs=%d  copybooks=%d  "
        "parse_errors=%d  parse_seconds=%.3f  "
        "peak_memory_mb=%.2f  max_copybook_depth=%d",
        report.files_discovered,
        report.programs,
        report.copybooks,
        report.parse_errors,
        report.parse_seconds,
        report.peak_memory_mb,
        report.max_copybook_depth,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="cobol_modernizer",
        description="COBOL modernizer toolchain CLI",
    )
    sub = root.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ── baseline ──────────────────────────────────────────────────────────────
    p_base = sub.add_parser(
        "baseline",
        help="Run the Phase-0 CardDemo baseline benchmark and write a JSON report",
    )
    p_base.add_argument(
        "--repo",
        required=True,
        metavar="PATH",
        help="Root directory of the COBOL repository to analyse",
    )
    p_base.add_argument(
        "--out",
        required=True,
        metavar="FILE",
        help="Output path for the JSON benchmark report",
    )
    p_base.set_defaults(func=_cmd_baseline)

    return root


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
