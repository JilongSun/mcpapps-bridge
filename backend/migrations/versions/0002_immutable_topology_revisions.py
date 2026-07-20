"""Add immutable topology revisions and bind sessions to endpoint revisions."""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0002_immutable_topology_revisions"
down_revision: str | Sequence[str] | None = "0001_initial_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upstream_revisions",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["upstream_servers.server_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint("server_id", "revision_number", name="uq_upstream_revision_number"),
    )
    op.create_table(
        "endpoint_revisions",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("upstream_session_mode", sa.String(length=32), nullable=False),
        sa.Column("lazy_upstream_connections", sa.Boolean(), nullable=False),
        sa.Column("idle_timeout_seconds", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.endpoint_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint("endpoint_id", "revision_number", name="uq_endpoint_revision_number"),
    )
    op.create_table(
        "endpoint_binding_revisions",
        sa.Column("binding_revision_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_revision_id", sa.Uuid(), nullable=False),
        sa.Column("upstream_revision_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["endpoint_revision_id"], ["endpoint_revisions.revision_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["upstream_revision_id"], ["upstream_revisions.revision_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("binding_revision_id"),
    )
    op.create_index(
        "ix_endpoint_binding_revisions_endpoint_priority",
        "endpoint_binding_revisions",
        ["endpoint_revision_id", "enabled", "priority"],
    )
    with op.batch_alter_table("upstream_servers") as batch_op:
        batch_op.add_column(sa.Column("current_revision_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_upstream_servers_current_revision",
            "upstream_revisions",
            ["current_revision_id"],
            ["revision_id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("endpoints") as batch_op:
        batch_op.add_column(sa.Column("current_revision_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_endpoints_current_revision",
            "endpoint_revisions",
            ["current_revision_id"],
            ["revision_id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("bridge_sessions") as batch_op:
        batch_op.add_column(sa.Column("endpoint_revision_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_bridge_sessions_endpoint_revision",
            "endpoint_revisions",
            ["endpoint_revision_id"],
            ["revision_id"],
            ondelete="RESTRICT",
        )

    _backfill_initial_revisions()

    with op.batch_alter_table("bridge_sessions") as batch_op:
        batch_op.alter_column(
            "endpoint_revision_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )


def _backfill_initial_revisions() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    upstream_servers = sa.Table("upstream_servers", metadata, autoload_with=connection)
    upstream_revisions = sa.Table("upstream_revisions", metadata, autoload_with=connection)
    endpoints = sa.Table("endpoints", metadata, autoload_with=connection)
    endpoint_revisions = sa.Table("endpoint_revisions", metadata, autoload_with=connection)
    endpoint_bindings = sa.Table("endpoint_bindings", metadata, autoload_with=connection)
    binding_revisions = sa.Table("endpoint_binding_revisions", metadata, autoload_with=connection)
    bridge_sessions = sa.Table("bridge_sessions", metadata, autoload_with=connection)
    now = datetime.now(timezone.utc)

    upstream_revision_ids: dict[str, str] = {}
    for row in connection.execute(sa.select(upstream_servers)).mappings():
        revision_id = uuid4().hex
        upstream_revision_ids[row["server_id"]] = revision_id
        connection.execute(
            upstream_revisions.insert().values(
                revision_id=revision_id,
                server_id=row["server_id"],
                revision_number=1,
                slug=row["slug"],
                display_name=row["display_name"],
                transport=row["transport"],
                url=row["url"],
                command=row["command"],
                args_json=row["args_json"],
                cwd=row["cwd"],
                env_json=row["env_json"],
                headers_json=row["headers_json"],
                timeout_seconds=row["timeout_seconds"],
                enabled=row["enabled"],
                metadata_json=row["metadata_json"],
                created_at=now,
            )
        )
        connection.execute(
            upstream_servers.update()
            .where(upstream_servers.c.server_id == row["server_id"])
            .values(current_revision_id=revision_id)
        )

    endpoint_revision_ids: dict[str, str] = {}
    for row in connection.execute(sa.select(endpoints)).mappings():
        revision_id = uuid4().hex
        endpoint_revision_ids[row["endpoint_id"]] = revision_id
        connection.execute(
            endpoint_revisions.insert().values(
                revision_id=revision_id,
                endpoint_id=row["endpoint_id"],
                revision_number=1,
                slug=row["slug"],
                display_name=row["display_name"],
                mode=row["mode"],
                upstream_session_mode=row["upstream_session_mode"],
                lazy_upstream_connections=row["lazy_upstream_connections"],
                idle_timeout_seconds=row["idle_timeout_seconds"],
                enabled=row["enabled"],
                metadata_json=row["metadata_json"],
                created_at=now,
            )
        )
        connection.execute(
            endpoints.update()
            .where(endpoints.c.endpoint_id == row["endpoint_id"])
            .values(current_revision_id=revision_id)
        )

    for row in connection.execute(sa.select(endpoint_bindings)).mappings():
        connection.execute(
            binding_revisions.insert().values(
                binding_revision_id=uuid4().hex,
                binding_id=row["binding_id"],
                endpoint_revision_id=endpoint_revision_ids[row["endpoint_id"]],
                upstream_revision_id=upstream_revision_ids[row["upstream_server_id"]],
                namespace=row["namespace"],
                priority=row["priority"],
                enabled=row["enabled"],
            )
        )

    for endpoint_id, revision_id in endpoint_revision_ids.items():
        connection.execute(
            bridge_sessions.update()
            .where(bridge_sessions.c.endpoint_id == endpoint_id)
            .values(endpoint_revision_id=revision_id)
        )


def downgrade() -> None:
    with op.batch_alter_table("bridge_sessions") as batch_op:
        batch_op.drop_constraint("fk_bridge_sessions_endpoint_revision", type_="foreignkey")
        batch_op.drop_column("endpoint_revision_id")
    with op.batch_alter_table("endpoints") as batch_op:
        batch_op.drop_constraint("fk_endpoints_current_revision", type_="foreignkey")
        batch_op.drop_column("current_revision_id")
    with op.batch_alter_table("upstream_servers") as batch_op:
        batch_op.drop_constraint("fk_upstream_servers_current_revision", type_="foreignkey")
        batch_op.drop_column("current_revision_id")
    op.drop_index(
        "ix_endpoint_binding_revisions_endpoint_priority",
        table_name="endpoint_binding_revisions",
    )
    op.drop_table("endpoint_binding_revisions")
    op.drop_table("endpoint_revisions")
    op.drop_table("upstream_revisions")
