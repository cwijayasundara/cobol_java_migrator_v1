import os
from fastapi.testclient import TestClient

from cobol_modernizer.api import app
from cobol_modernizer.controlplane.repos import scan_repos


def _make_repo(root, name, programs=0, copybooks=0):
    d = root / name
    (d / "cbl").mkdir(parents=True)
    for i in range(programs):
        (d / "cbl" / f"P{i}.cbl").write_text("       IDENTIFICATION DIVISION.\n")
    for i in range(copybooks):
        (d / "cbl" / f"C{i}.cpy").write_text("       01 X PIC X.\n")
    return d


def test_scan_repos_counts_cobol_and_skips_empty_and_hidden(tmp_path):
    _make_repo(tmp_path, "carddemo-mini", programs=3, copybooks=1)
    _make_repo(tmp_path, "sample_cobol", programs=2, copybooks=0)
    (tmp_path / "not-a-repo").mkdir()                 # no COBOL -> excluded
    (tmp_path / ".git").mkdir()                       # hidden -> excluded
    (tmp_path / ".git" / "x.cbl").write_text("x")
    repos = scan_repos(tmp_path)
    by_slug = {r["slug"]: r for r in repos}
    assert set(by_slug) == {"carddemo-mini", "sample_cobol"}
    assert by_slug["carddemo-mini"]["programs"] == 3
    assert by_slug["carddemo-mini"]["copybooks"] == 1
    assert by_slug["sample_cobol"]["programs"] == 2


def test_repos_endpoint_lists_discovered_repos(tmp_path, monkeypatch):
    _make_repo(tmp_path, "carddemo-mini", programs=3, copybooks=1)
    monkeypatch.setenv("COBOL_SOURCE_ROOT", str(tmp_path))
    resp = TestClient(app).get("/api/repos")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["slug"] for r in body] == ["carddemo-mini"]
    assert body[0]["programs"] == 3


def test_repos_endpoint_empty_when_root_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("COBOL_SOURCE_ROOT", str(tmp_path / "nope"))
    assert TestClient(app).get("/api/repos").json() == []
