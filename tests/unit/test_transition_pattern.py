from cobol_modernizer.seam.transition import classify_seam_type, transition_for
from cobol_modernizer.seam.schema import SeamType


def test_cics_program_is_cics_api():
    profile = {"has_cics": True, "is_writer": False, "is_copybook": False,
               "is_batch_io": False, "reader_only": True}
    assert classify_seam_type(profile) is SeamType.cics_api
    assert transition_for(SeamType.cics_api).name == "facade_routed_by_txn_id"


def test_writer_is_db_writer_with_acl():
    profile = {"has_cics": False, "is_writer": True, "is_copybook": False,
               "is_batch_io": False, "reader_only": False}
    assert classify_seam_type(profile) is SeamType.db_writer
    assert "anti-corruption" in transition_for(SeamType.db_writer).summary.lower()


def test_reader_is_db_reader_cdc():
    profile = {"has_cics": False, "is_writer": False, "is_copybook": False,
               "is_batch_io": False, "reader_only": True}
    assert classify_seam_type(profile) is SeamType.db_reader
    assert transition_for(SeamType.db_reader).name == "cdc_or_read_replica"


def test_batch_io_is_spring_batch():
    profile = {"has_cics": False, "is_writer": False, "is_copybook": False,
               "is_batch_io": True, "reader_only": True}
    assert classify_seam_type(profile) is SeamType.batch_io
    assert transition_for(SeamType.batch_io).name == "spring_batch_adapter"


def test_copybook_is_canonical_dto():
    profile = {"has_cics": False, "is_writer": False, "is_copybook": True,
               "is_batch_io": False, "reader_only": False}
    assert classify_seam_type(profile) is SeamType.copybook
    assert transition_for(SeamType.copybook).name == "canonical_dto_acl"
