"""Create managed topology and session persistence tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_persistence"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upstream_servers",
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("args_json", sa.JSON(), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("env_json", sa.JSON(), nullable=False),
        sa.Column("headers_json", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("server_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "endpoints",
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("upstream_session_mode", sa.String(length=32), nullable=False),
        sa.Column("lazy_upstream_connections", sa.Boolean(), nullable=False),
        sa.Column("idle_timeout_seconds", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("endpoint_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "endpoint_bindings",
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("upstream_server_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.endpoint_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["upstream_server_id"],
            ["upstream_servers.server_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("binding_id"),
    )
    op.create_index(
        "ix_endpoint_bindings_endpoint_enabled_priority",
        "endpoint_bindings",
        ["endpoint_id", "enabled", "priority"],
    )
    op.create_table(
        "bridge_sessions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("downstream_transport_session_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.endpoint_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("downstream_transport_session_id"),
    )
    op.create_index(
        "ix_bridge_sessions_endpoint_status_created",
        "bridge_sessions",
        ["endpoint_id", "status", "created_at"],
    )
    op.create_table(
        "upstream_sessions",
        sa.Column("upstream_session_id", sa.Uuid(), nullable=False),
        sa.Column("bridge_session_id", sa.Uuid(), nullable=False),
        sa.Column("upstream_server_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["bridge_session_id"],
            ["bridge_sessions.session_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upstream_server_id"],
            ["upstream_servers.server_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("upstream_session_id"),
        sa.UniqueConstraint(
            "bridge_session_id",
            "upstream_server_id",
            name="uq_upstream_sessions_bridge_server",
        ),
    )
    op.create_table(
        "session_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["bridge_sessions.session_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_session_events_session_sequence"),
    )
    op.create_index(
        "ix_session_events_session_sequence",
        "session_events",
        ["session_id", "sequence"],
    )
    op.create_table(
        "session_snapshots",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["bridge_sessions.session_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("session_snapshots")
    op.drop_index("ix_session_events_session_sequence", table_name="session_events")
    op.drop_table("session_events")
    op.drop_table("upstream_sessions")
    op.drop_index("ix_bridge_sessions_endpoint_status_created", table_name="bridge_sessions")
    op.drop_table("bridge_sessions")
    op.drop_index(
        "ix_endpoint_bindings_endpoint_enabled_priority",
        table_name="endpoint_bindings",
    )
    op.drop_table("endpoint_bindings")
    op.drop_table("endpoints")
    op.drop_table("upstream_servers")
