import json
from pathlib import Path

from cobol_modernizer.benchmark.work_unit_pipeline import (
    run_carddemo_mini_benchmark,
    write_report,
)
from cobol_modernizer.cli import main
from cobol_modernizer.contract.cobol_contract import load_contract


FIX = Path(__file__).parents[1] / "fixtures" / "extract_v2.json"


def test_work_unit_benchmark_report_has_operational_fields(cobol_sample_root, tmp_path):
    payload = json.loads(FIX.read_text())
    report = run_carddemo_mini_benchmark(
        cobol_sample_root, parse_fn=lambda root: load_contract(payload))

    assert report.repo_slug == "carddemo-mini"
    assert report.files_discovered > 0
    assert report.agent_calls == 0
    assert report.cost_usd == 0.0
    assert set(report.token_usage) == {
        "input", "output", "cache_read", "cache_creation"}
    assert report.gate_state["backlog"] == "skipped_no_llm"
    assert report.skipped_repos[0]["repo_slug"] == "aws-mf-mod-carddemo"

    out = tmp_path / "nested" / "bench.json"
    write_report(report, out)
    data = json.loads(out.read_text())
    assert data["repo_slug"] == "carddemo-mini"
    assert data["stages"][0]["stage"] == "parse"


def test_work_unit_benchmark_cli_blocks_large_repo(tmp_path):
    large = tmp_path / "aws-mf-mod-carddemo"
    large.mkdir()
    rc = main([
        "work-unit-benchmark",
        "--repo", str(large),
        "--repo-slug", "aws-mf-mod-carddemo",
        "--out", str(tmp_path / "out.json"),
    ])
    assert rc == 2
