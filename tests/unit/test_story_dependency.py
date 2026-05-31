from cobol_modernizer.planner.dependency import stories_from_seam_set, derive_dependencies
from cobol_modernizer.planner.dag import is_acyclic


def test_writer_story_depends_on_reader_of_shared_resource():
    # COACTVWC reads ACCTFILE; CBTRN02C writes ACCTFILE -> writer depends on reader.
    seam_candidates = [
        {"program": "COACTVWC", "reads": ["ACCTFILE"], "writes": [],
         "score": {"weighted": 0.8}},
        {"program": "CBTRN02C", "reads": [], "writes": ["ACCTFILE"],
         "score": {"weighted": 0.2}},
    ]
    stories = stories_from_seam_set(seam_candidates, repo_id="cardemo")
    dag = derive_dependencies(stories, seam_candidates)
    writer = next(s for s in dag.stories if s.seam == "CBTRN02C")
    reader = next(s for s in dag.stories if s.seam == "COACTVWC")
    assert reader.id in writer.depends_on
    assert is_acyclic(dag) is True
