"""defect_ticket: equivalence-diff failures linked to source seam

Revision ID: 0002_defect_ticket
Revises: 0001_initial
Create Date: 2026-05-31 00:00:00.000000

Numbered 0002 by delivery order (Phase 3), per the binding migration-numbering
decision; the Phase 6 deploy table becomes 0003.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_defect_ticket"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "defect_ticket",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("stage_id", sa.String(), nullable=True),
        sa.Column("agent_run_id", sa.String(), nullable=True),
        sa.Column("artifact_id", sa.String(), nullable=True),
        sa.Column("source_seam", sa.String(), nullable=False),
        sa.Column("seam_edge_kind", sa.String(), nullable=True),
        sa.Column("source_file", sa.String(), nullable=True),
        sa.Column("source_line", sa.Integer(), nullable=True),
        sa.Column("field", sa.String(), nullable=False),
        sa.Column("record_key", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("dialect_note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_id"], ["journey_stage.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_run.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifact.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("defect_ticket")
