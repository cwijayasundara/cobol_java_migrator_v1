from cobol_modernizer.technical_design.render import render_html
from cobol_modernizer.technical_design.schema import (
    ApiContract, PersistenceDesign, TechnicalDesign, TechnicalService,
)
from cobol_modernizer.technical_design.storage import TechnicalDesignStorage


class FakeNeo4j:
    def __init__(self):
        self.saved = None
        self.version = 0

    def run(self, query, **params):
        if "CREATE (t:TechnicalDesign" in query:
            self.version += 1
            self.saved = dict(params, version=self.version)
            return [{"version": self.version}]
        if "RETURN t ORDER BY t.version DESC" in query:
            return [{"t": self.saved}] if self.saved else []
        return []


def _design():
    return TechnicalDesign(repo_slug="carddemo-mini", services=[
        TechnicalService(name="posting-service", bounded_context="Posting", deployment="module",
                         story_ids=["US-1"],
                         api_contracts=[ApiContract(name="post", method="POST", path="/p")],
                         persistence=[PersistenceDesign(resource="ACCTFILE", access_pattern="legacy-mimic")],
                         evidence_refs=["CBPOST1M"])])


def test_save_and_get_latest_roundtrip():
    neo = FakeNeo4j()
    out = TechnicalDesignStorage(neo).save(_design(), html="<h1>td</h1>", model="m")
    assert out.version == 1
    assert "posting-service" in neo.saved["services_json"]
    assert TechnicalDesignStorage(neo).get_latest("carddemo-mini")["version"] == 1


def test_save_twice_increments_version_on_get_latest():
    neo = FakeNeo4j()
    TechnicalDesignStorage(neo).save(_design(), html="<h1>td</h1>", model="m")
    TechnicalDesignStorage(neo).save(_design(), html="<h1>td</h1>", model="m")
    assert TechnicalDesignStorage(neo).get_latest("carddemo-mini")["version"] == 2


def test_render_html_lists_services_and_contracts():
    html = render_html(_design())
    assert "posting-service" in html
    assert "Posting" in html
    assert "/p" in html
    assert "ACCTFILE" in html


def test_render_html_escapes_special_characters():
    design = TechnicalDesign(repo_slug="repo<>&", services=[
        TechnicalService(name="svc<x>", bounded_context="Posting", deployment="module",
                         api_contracts=[ApiContract(name="post", method="POST", path="/p<script>")])])
    html = render_html(design)
    assert "repo<>" not in html
    assert "svc<x>" not in html
    assert "<script>" not in html
    assert "&lt;" in html
