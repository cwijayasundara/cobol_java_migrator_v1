from cobol_modernizer.seam.deadcode import dead_paragraphs


class FakeClient:
    def __init__(self, rows): self.rows = rows
    def run(self, query, **params): return self.rows


def test_unreachable_paragraph_flagged():
    # 1000-MAIN reaches 2000-READ; 9999-ORPHAN is never performed/gone-to.
    client = FakeClient([{"paragraph": "CBACT01C.9999-ORPHAN"}])
    assert dead_paragraphs(client, repo="cardemo", program="CBACT01C") == \
        ["CBACT01C.9999-ORPHAN"]


def test_no_dead_paragraphs():
    client = FakeClient([])
    assert dead_paragraphs(client, repo="cardemo", program="CBACT01C") == []
