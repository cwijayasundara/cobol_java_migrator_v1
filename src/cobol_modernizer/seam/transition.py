from __future__ import annotations

from cobol_modernizer.seam.schema import SeamType, TransitionPattern

_PATTERNS: dict[SeamType, TransitionPattern] = {
    SeamType.batch_io: TransitionPattern(
        name="spring_batch_adapter",
        summary="Wrap the sequential file-IO batch step in a Spring Batch adapter "
                "(reader/processor/writer); keep the COBOL file format via an ItemReader."),
    SeamType.cics_api: TransitionPattern(
        name="facade_routed_by_txn_id",
        summary="Front the CICS transaction with a facade routed by transaction id; "
                "dark-launch the Spring service behind the same txn id."),
    SeamType.db_reader: TransitionPattern(
        name="cdc_or_read_replica",
        summary="Read-only access: feed the new service via Change Data Capture or a "
                "read replica; no write-back, lowest blast radius."),
    SeamType.db_writer: TransitionPattern(
        name="extract_product_lines_acl",
        summary="Writer: apply Extract Product Lines and front the legacy store with an "
                "anti-corruption layer; keep writes single-system until fully extracted."),
    SeamType.copybook: TransitionPattern(
        name="canonical_dto_acl",
        summary="Shared copybook: promote to a canonical DTO with an anti-corruption "
                "layer translating to/from the legacy record layout."),
}


def classify_seam_type(profile: dict) -> SeamType:
    # Precedence: copybook node > CICS surface > writer > batch IO > db reader.
    if profile.get("is_copybook"):
        return SeamType.copybook
    if profile.get("has_cics"):
        return SeamType.cics_api
    if profile.get("is_writer"):
        return SeamType.db_writer
    if profile.get("is_batch_io"):
        return SeamType.batch_io
    return SeamType.db_reader


def transition_for(seam_type: SeamType) -> TransitionPattern:
    return _PATTERNS[seam_type]
