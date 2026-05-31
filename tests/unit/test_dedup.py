from cobol_modernizer.seam.dedup import capability_fingerprint, duplicate_capabilities


def test_fingerprint_is_name_independent():
    a = {"accesses": [("CSUTLDTC", "call")], "data": [("WS-DATE", "read")]}
    b = {"accesses": [("CSUTLDTC", "call")], "data": [("WS-DT", "read")]}  # diff data name
    # capability fingerprint keys on external calls + resource intents, not local vars
    fa = capability_fingerprint(a, key="accesses")
    fb = capability_fingerprint(b, key="accesses")
    assert fa == fb


def test_clusters_duplicate_validators():
    profiles = {
        "COACTUPC": {"accesses": [("CSUTLDTC", "call")]},
        "CORPT00C": {"accesses": [("CSUTLDTC", "call")]},
        "COTRN02C": {"accesses": [("CSUTLDTC", "call")]},
        "COSGN00C": {"accesses": [("COMEN01C", "call")]},  # different capability
    }
    clusters = duplicate_capabilities(profiles, key="accesses")
    assert sorted(clusters[0]) == ["COACTUPC", "CORPT00C", "COTRN02C"]
    assert len(clusters) == 1  # the singleton COSGN00C is not a duplicate cluster
