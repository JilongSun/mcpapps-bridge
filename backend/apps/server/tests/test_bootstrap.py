from __future__ import annotations

from pathlib import Path

from mabrid.application.agent_host import AgentCapability, AgentRuntimeInterface
from pydantic import SecretStr
from sqlalchemy import inspect

from mabrid.server.composition import bootstrap_server
from mabrid.server.config import (
    BridgeRuntimeConfig,
    EndpointBindingFileConfig,
    EndpointFileConfig,
    RuntimeAgentHostConfig,
    RuntimeConfiguration,
    RuntimeHermesAgentConfig,
    RuntimeUpstreamConfig,
    StorageConfig,
)
from mabrid.server.persistence import Base, SqliteDatabase


def _endpoints() -> dict[str, EndpointFileConfig]:
    return {"fixture": EndpointFileConfig(bindings=[EndpointBindingFileConfig(upstream="fixture")])}


async def test_clean_sqlite_database_migrates_seeds_and_composes_gateway(tmp_path: Path) -> None:
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(),
        storage=StorageConfig(sqlite_path=tmp_path / "gateway.db", auto_migrate=True),
        upstreams={
            "fixture": RuntimeUpstreamConfig(
                transport="stdio",
                command="fixture-server",
            )
        },
        endpoints=_endpoints(),
        diagnostic_upstream=None,
    )

    result = await bootstrap_server(configuration)
    try:
        assert [endpoint.revision.slug for endpoint in result.gateway.published_endpoints] == [
            "fixture"
        ]
        assert configuration.storage.sqlite_path.is_file()
    finally:
        await result.database.close()


async def test_initial_migration_matches_the_current_sqlite_schema(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "schema.db")
    try:
        await database.migrate()
        async with database.engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            endpoint_columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"] for column in inspect(sync_connection).get_columns("endpoints")
                }
            )
            session_columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"]
                    for column in inspect(sync_connection).get_columns("bridge_sessions")
                }
            )
    finally:
        await database.close()

    assert tables == {*Base.metadata.tables, "alembic_version"}
    assert "upstream_sessions" not in tables
    assert "upstream_session_mode" not in endpoint_columns
    assert "lazy_upstream_connections" not in endpoint_columns
    assert "idle_timeout_seconds" not in endpoint_columns
    assert "downstream_transport_session_id" not in session_columns


async def test_enabled_agent_host_composes_hermes_http_adapter(tmp_path: Path) -> None:
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(),
        storage=StorageConfig(sqlite_path=tmp_path / "gateway.db", auto_migrate=True),
        upstreams={
            "fixture": RuntimeUpstreamConfig(
                transport="stdio",
                command="fixture-server",
            )
        },
        endpoints=_endpoints(),
        diagnostic_upstream=None,
        agent_host=RuntimeAgentHostConfig(
            enabled=True,
            target_id="fixture-target",
            endpoint_slug="fixture",
            runtime=RuntimeHermesAgentConfig(
                base_url="http://hermes.test:8642/v1",
                api_key=SecretStr("fixture-secret"),
            ),
        ),
    )

    result = await bootstrap_server(configuration)
    try:
        assert result.agent_host is not None
        assert result.agent_host.service.target.target_id == "fixture-target"
        assert result.agent_host.service.runtime_profile.interface is (
            AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS
        )
        assert result.agent_host.service.runtime_profile.capabilities == frozenset(
            {
                AgentCapability.TEXT_GENERATION,
                AgentCapability.TOKEN_USAGE,
            }
        )
        assert result.agent_host.service.target.endpoint_assignment.endpoint_slug == "fixture"
    finally:
        if result.agent_host is not None:
            await result.agent_host.runtime.close()
        await result.database.close()


async def test_agent_target_requires_a_published_enabled_endpoint(tmp_path: Path) -> None:
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(),
        storage=StorageConfig(sqlite_path=tmp_path / "gateway.db", auto_migrate=True),
        upstreams={
            "fixture": RuntimeUpstreamConfig(
                transport="stdio",
                command="fixture-server",
            )
        },
        endpoints=_endpoints(),
        diagnostic_upstream=None,
        agent_host=RuntimeAgentHostConfig(
            enabled=True,
            target_id="fixture-target",
            endpoint_slug="missing-endpoint",
            runtime=RuntimeHermesAgentConfig(
                base_url="http://hermes.test:8642/v1",
                api_key=SecretStr("fixture-secret"),
            ),
        ),
    )

    try:
        await bootstrap_server(configuration)
    except ValueError as exc:
        assert "missing-endpoint" in str(exc)
        assert "not published and enabled" in str(exc)
    else:
        raise AssertionError("bootstrap accepted an unpublished Agent Target endpoint")


async def test_diagnostic_upstream_explicitly_overrides_configured_endpoints(
    tmp_path: Path,
) -> None:
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(proxy_name="Diagnostic Fixture"),
        storage=StorageConfig(sqlite_path=tmp_path / "gateway.db", auto_migrate=True),
        upstreams={
            "fixture": RuntimeUpstreamConfig(
                transport="stdio",
                command="fixture-server",
            )
        },
        endpoints={
            "configured-endpoint": EndpointFileConfig(
                bindings=[EndpointBindingFileConfig(upstream="fixture")]
            )
        },
        diagnostic_upstream="fixture",
    )

    result = await bootstrap_server(configuration)
    try:
        [published] = result.gateway.published_endpoints
        assert published.revision.slug == "fixture"
        assert published.revision.display_name == "Diagnostic Fixture"
    finally:
        await result.database.close()
