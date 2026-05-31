"""deployment/canary_route/fitness_check: Phase 6 deployment automation + canary

Revision ID: 0003_deploy
Revises: 0002_defect_ticket
Create Date: 2026-05-31 00:00:00.000000

Numbered 0003 by delivery order (Phase 6), per the binding migration-numbering
decision. All deploy/routing/fitness state is Postgres run/audit state; Neo4j
carries none of it. canary_route defaults to canary_pct=0/legacy_pct=100 so the
migration leaves every slice stoppable-safe (full legacy) on creation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_deploy"
down_revision: Union[str, None] = "0002_defect_ticket"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deployment",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=True),
        sa.Column("slice_name", sa.String(), nullable=False),
        sa.Column("image_ref", sa.String(), nullable=False),
        sa.Column("image_digest", sa.String(), nullable=False),
        sa.Column("smoke_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("perf_baseline", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="built"),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifact.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "canary_route",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("slice_name", sa.String(), nullable=False),
        sa.Column("deployment_id", sa.String(), nullable=True),
        sa.Column("canary_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("legacy_pct", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rollback_reason", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployment.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slice_name", "active",
                            name="uq_canary_route_active"),
    )
    op.create_table(
        "fitness_check",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "commit_sha", name="uq_fitness_commit"),
    )


def downgrade() -> None:
    op.drop_table("fitness_check")
    op.drop_table("canary_route")
    op.drop_table("deployment")
