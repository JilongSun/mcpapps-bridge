from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

from mabrid.application.agent_host import AgentCapability, AgentRuntimeInterface
from mabrid.application.agent_host.integrations.hermes import HermesChatCompletionsAdapter
import pytest
from pydantic import SecretStr
from sqlalchemy import inspect

from mabrid.server.api import create_app
from mabrid.server.composition import GatewayManagementComposition, bootstrap_server
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
from mabrid.server.persistence import Base, SqliteDatabase, SqliteReadinessProbe
import mabrid.server.composition.agent_host as agent_host_composition


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
        assert isinstance(result.gateway_management, GatewayManagementComposition)
        assert result.gateway_management.published_endpoint_slugs == ("fixture",)
        assert await result.gateway_management.is_ready() is True
        with pytest.raises(FrozenInstanceError):
            setattr(result.gateway_management, "advertised_base_url", "http://changed.test")
        assert configuration.storage.sqlite_path.is_file()
    finally:
        await result.database.close()


async def test_gateway_management_is_not_ready_without_a_published_endpoint(
    tmp_path: Path,
) -> None:
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
        endpoints={},
        diagnostic_upstream=None,
    )

    result = await bootstrap_server(configuration)
    try:
        assert result.gateway_management.published_endpoint_slugs == ()
        assert await result.gateway_management.is_ready() is False
    finally:
        await result.database.close()


async def test_sqlite_readiness_probe_distinguishes_available_database(
    tmp_path: Path,
) -> None:
    available = SqliteDatabase(tmp_path / "available.db")
    unavailable = SqliteDatabase(tmp_path / "missing" / "unavailable.db")
    try:
        await available.migrate()

        assert await SqliteReadinessProbe(available.session_factory).is_ready() is True
        assert await SqliteReadinessProbe(unavailable.session_factory).is_ready() is False
    finally:
        await available.close()
        await unavailable.close()


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
        bridge=BridgeRuntimeConfig(advertised_base_url="http://mabrid.test:8765"),
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
            mcp_apps_enabled=True,
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
        assert result.agent_host.management.target is result.agent_host.service.target
        assert result.agent_host.management.endpoint_slug == "fixture"
        assert result.agent_host.management.endpoint_path == "/mcp/fixture"
        assert result.agent_host.management.transport == "streamable-http"
        assert result.agent_host.management.advertised_url == (
            "http://mabrid.test:8765/mcp/fixture"
        )
        published = result.gateway.resolve_published_endpoint("fixture")
        assert published is not None
        assert result.agent_host.management.endpoint_id == published.revision.endpoint_id
        assert result.agent_host.management.target.endpoint_assignment.model_dump() == {
            "endpoint_slug": "fixture"
        }
        observer = result.agent_host.bridge_observer_factory.create(
            "session-1",
            "fixture",
        )
        assert observer is not None
        assert result.agent_host.operation_attributions is not None
        assert result.mcp_apps is not None
        assert result.host_events is not None
        app = create_app(
            result.gateway,
            agent_host=result.agent_host.service,
            gateway_management=result.gateway_management,
            agent_host_management=result.agent_host.management,
        )
        assert app.state.gateway_management is result.gateway_management
        assert app.state.agent_host_management is result.agent_host.management
    finally:
        if result.agent_host is not None:
            await result.agent_host.runtime.close()
        await result.database.close()


async def test_enabled_agent_host_can_omit_mcp_apps_workflow(tmp_path: Path) -> None:
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(advertised_base_url="http://mabrid.test:8765"),
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
            mcp_apps_enabled=False,
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
        assert result.mcp_apps is None
        assert result.host_events is not None
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


async def test_bootstrap_failure_closes_agent_runtime_before_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []
    original_database_close = SqliteDatabase.close

    async def close_agent_runtime(_runtime: HermesChatCompletionsAdapter) -> None:
        closed.append("agent-runtime")

    async def close_database(database: SqliteDatabase) -> None:
        closed.append("database")
        await original_database_close(database)

    def fail_agent_host_service(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fixture composition failure")

    monkeypatch.setattr(HermesChatCompletionsAdapter, "close", close_agent_runtime)
    monkeypatch.setattr(agent_host_composition, "AgentHostService", fail_agent_host_service)
    monkeypatch.setattr(SqliteDatabase, "close", close_database)
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(advertised_base_url="http://mabrid.test:8765"),
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

    with pytest.raises(RuntimeError, match="fixture composition failure"):
        await bootstrap_server(configuration)

    assert closed == ["agent-runtime", "database"]


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
