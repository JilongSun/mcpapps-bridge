"""Persist Agent Session bindings and unresolved native execution ownership."""

from alembic import op
import sqlalchemy as sa

revision = "0002_agent_sessions"
down_revision = "0001_mabrid_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("runtime_binding_id", sa.String(255), nullable=False),
        sa.Column("remote_session_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint(
            "runtime_binding_id", "remote_session_id", name="uq_agent_session_remote_binding"
        ),
    )
    op.create_index(
        "ix_agent_sessions_target_created", "agent_sessions", ["target_id", "created_at"]
    )
    op.create_table(
        "unsettled_agent_runs",
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("runtime_binding_id", sa.String(255), nullable=False),
        sa.Column("remote_run_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.session_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("target_id"),
        sa.UniqueConstraint("run_id"),
    )


def downgrade() -> None:
    op.drop_table("unsettled_agent_runs")
    op.drop_index("ix_agent_sessions_target_created", table_name="agent_sessions")
    op.drop_table("agent_sessions")
