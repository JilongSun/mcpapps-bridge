from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

from mabrid.application.agent_host import (
    AgentCapability,
    AgentRuntimeInterface,
    AgentSessionRecord,
    RuntimeSessionReference,
    RuntimeRunHandle,
    StartRunCommand,
    AgentMessage,
    AgentRunConflictError,
)
from mabrid.application.agent_host.integrations.hermes import (
    HermesChatCompletionsAdapter,
    HermesSessionAdapter,
)
from mabrid.server.config.runtime import RuntimeHermesSessionConfig
from mabrid.server.persistence.agent_host import SqliteAgentSessionRepository
from datetime import datetime, timezone
from uuid import uuid4
import pytest
import httpx
import uvicorn
from fastapi import FastAPI
import mabrid.server.main as server_main
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
import mabrid.application.host.composition as host_capabilities
import mabrid.server.composition.agent_host as agent_composition
from openai import AsyncOpenAI


def _endpoints() -> dict[str, EndpointFileConfig]:
    return {"fixture": EndpointFileConfig(bindings=[EndpointBindingFileConfig(upstream="fixture")])}


@pytest.mark.parametrize(
    "mode",
    [
        "native",
        "compatibility_only",
        "disabled",
        "widgets_disabled",
        "split_outage",
        "unsupported",
        "unknown",
    ],
)
async def test_production_capabilities_use_selected_interfaces_without_changing_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET" and request.url.path.endswith("/v1/capabilities")
        assert request.headers["authorization"] == "Bearer private-fixture-key"
        native = request.url.path.startswith("/native/")
        if mode == "split_outage" and native:
            return httpx.Response(503, text="private-upstream-diagnostic")
        if mode == "unknown":
            return httpx.Response(404, text="private-upstream-diagnostic")
        return httpx.Response(
            200,
            json={
                "object": "hermes.api_server.capabilities",
                "platform": "hermes-agent",
                "model": "private-remote-model",
                "auth": {"type": "bearer", "required": True},
                "runtime": {
                    "mode": "server_agent",
                    "tool_execution": "server",
                    "split_runtime": False,
                },
                "features": {
                    "session_resources": mode != "unsupported",
                    "session_chat_streaming": mode != "unsupported",
                    "run_status": True,
                    "run_stop": True,
                    "chat_completions_streaming": True,
                },
                "endpoints": {
                    name: {"method": method, "path": path}
                    for name, method, path in (
                        ("session_create", "POST", "/api/sessions"),
                        ("session", "GET", "/api/sessions/{session_id}"),
                        ("session_messages", "GET", "/api/sessions/{session_id}/messages"),
                        ("session_chat_stream", "POST", "/api/sessions/{session_id}/chat/stream"),
                        ("run_status", "GET", "/v1/runs/{run_id}"),
                        ("run_stop", "POST", "/v1/runs/{run_id}/stop"),
                        ("chat_completions", "POST", "/v1/chat/completions"),
                    )
                },
            },
        )

    transport = httpx.MockTransport(handle)

    def build_runtime(config: RuntimeHermesAgentConfig) -> HermesChatCompletionsAdapter:
        return HermesChatCompletionsAdapter(
            base_url=config.base_url,
            api_key="private-fixture-key",
            client=AsyncOpenAI(
                base_url=config.base_url,
                api_key="private-fixture-key",
                http_client=httpx.AsyncClient(transport=transport),
                max_retries=0,
            ),
        )

    def build_native(**kwargs: object) -> HermesSessionAdapter:
        return HermesSessionAdapter(
            api_root="http://runtime.test/native",
            api_key="private-fixture-key",
            runtime_binding_id="private-binding",
            client=httpx.AsyncClient(transport=transport),
        )

    monkeypatch.setattr(agent_composition, "_build_agent_runtime", build_runtime)
    monkeypatch.setattr(agent_composition, "HermesSessionAdapter", build_native)
    enabled = mode != "disabled"
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(advertised_base_url="http://mabrid.test"),
        storage=StorageConfig(sqlite_path=tmp_path / "capabilities.db"),
        upstreams={"fixture": RuntimeUpstreamConfig(command="fixture-server")},
        endpoints=_endpoints(),
        diagnostic_upstream=None,
        agent_host=RuntimeAgentHostConfig(
            enabled=enabled,
            mcp_apps_enabled=mode != "widgets_disabled",
            target_id="fixture-target" if enabled else None,
            endpoint_slug="fixture" if enabled else None,
            runtime=RuntimeHermesAgentConfig(
                base_url="http://runtime.test/compatibility/v1",
                api_key=SecretStr("private-fixture-key"),
                sessions=RuntimeHermesSessionConfig(
                    api_root="http://runtime.test/native", binding_id="private-binding"
                )
                if enabled and mode != "compatibility_only"
                else None,
            ),
        ),
    )

    async def serve(server: uvicorn.Server) -> None:
        assert isinstance(server.config.app, FastAPI)
        assert requests == []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.config.app), base_url="http://mabrid.test"
        ) as client:
            assert (await client.get("/ready")).status_code == 200
            response = await client.get("/api/v1/capabilities")
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            document = response.json()
            assert document["gateway"] == {
                "enabled": True,
                "topology_read": True,
                "session_inspection": True,
                "topology_mutation": False,
                "mcp_apps_protocol_passthrough": True,
            }
            host = document["agent_host"]
            assert host["enabled"] == enabled
            expected = {
                "native": "available",
                "compatibility_only": "disabled",
                "disabled": "disabled",
                "widgets_disabled": "available",
                "split_outage": "unavailable",
                "unsupported": "unsupported",
                "unknown": "unknown",
            }[mode]
            assert host["features"]["session_streaming"]["availability"] == expected
            assert host["features"]["session_history"]["availability"] == expected
            assert host["features"]["widgets"]["availability"] == (
                "disabled" if mode == "widgets_disabled" else expected
            )
            assert host["features"]["compatibility_streaming"]["availability"] == (
                "disabled" if not enabled else "unknown" if mode == "unknown" else "available"
            )
            for deferred in ("host_actions", "event_replay", "remote_session_import"):
                assert host["features"][deferred]["implemented"] is False
            assert host["max_concurrent_runs"] == 1
            assert len(requests) == (0 if not enabled else 1 if mode == "compatibility_only" else 2)
            assert (
                (await client.get("/ready")).status_code
                == (await client.get("/health")).status_code
                == 200
            )
            assert len(requests) == (0 if not enabled else 1 if mode == "compatibility_only" else 2)
            for private in (
                "private-fixture-key",
                "private-binding",
                "private-upstream-diagnostic",
                "private-remote-model",
                "runtime.test",
                "runtime_binding_id",
                "session_key",
                "operation_key",
            ):
                assert private not in response.text

    monkeypatch.setattr(
        server_main, "resolve_runtime_configuration", lambda *_args, **_kwargs: configuration
    )
    monkeypatch.setattr(uvicorn.Server, "serve", serve)
    await server_main.serve_runtime(
        server_main.parse_args(["--config", str(configuration.config_path)])
    )


@pytest.mark.parametrize("native_enabled", [False, True])
async def test_main_runtime_wires_first_party_host_without_changing_gateway_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_enabled: bool
) -> None:
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(advertised_base_url="http://mabrid.test"),
        storage=StorageConfig(sqlite_path=tmp_path / "runtime.db"),
        upstreams={"fixture": RuntimeUpstreamConfig(command="fixture-server")},
        endpoints=_endpoints(),
        diagnostic_upstream=None,
        agent_host=RuntimeAgentHostConfig(
            enabled=native_enabled,
            target_id="fixture-target" if native_enabled else None,
            endpoint_slug="fixture" if native_enabled else None,
            runtime=RuntimeHermesAgentConfig(
                api_key=SecretStr("fixture"),
                sessions=RuntimeHermesSessionConfig(
                    api_root="http://hermes.test", binding_id="fixture"
                )
                if native_enabled
                else None,
            ),
        ),
    )

    async def serve(server: uvicorn.Server) -> None:
        app = server.config.app
        assert isinstance(app, FastAPI)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://mabrid.test"
        ) as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/ready")).status_code == 200
            response = await client.get("/api/v1/host/sessions")
            assert response.status_code == (200 if native_enabled else 503)
            if native_enabled:
                assert response.json()["sessions"] == []
            else:
                assert response.json()["code"] == "unsupported_operation"

    monkeypatch.setattr(
        server_main, "resolve_runtime_configuration", lambda *_args, **_kwargs: configuration
    )
    monkeypatch.setattr(uvicorn.Server, "serve", serve)
    await server_main.serve_runtime(
        server_main.parse_args(["--config", str(configuration.config_path)])
    )


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


@pytest.mark.parametrize("fail_session_close", [False, True])
async def test_bootstrap_failure_closes_agent_runtime_before_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_session_close: bool,
) -> None:
    closed: list[str] = []
    original_database_close = SqliteDatabase.close

    async def close_agent_runtime(_runtime: HermesChatCompletionsAdapter) -> None:
        closed.append("agent-runtime")

    async def close_session_runtime(runtime: HermesSessionAdapter) -> None:
        closed.append("session-runtime")
        await original_session_close(runtime)
        if fail_session_close:
            raise RuntimeError("fixture native close failure")

    async def close_database(database: SqliteDatabase) -> None:
        closed.append("database")
        await original_database_close(database)

    def fail_agent_host_service(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fixture composition failure")

    monkeypatch.setattr(HermesChatCompletionsAdapter, "close", close_agent_runtime)
    original_session_close = HermesSessionAdapter.close
    monkeypatch.setattr(HermesSessionAdapter, "close", close_session_runtime)
    monkeypatch.setattr(host_capabilities, "AgentHostService", fail_agent_host_service)
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

    configuration.agent_host.runtime.sessions = RuntimeHermesSessionConfig(
        api_root="http://hermes.test:8642/prefix", binding_id="fixture-deployment"
    )
    with pytest.raises(
        RuntimeError,
        match="fixture native close failure"
        if fail_session_close
        else "fixture composition failure",
    ):
        await bootstrap_server(configuration)

    assert closed == ["session-runtime", "agent-runtime", "database"]


@pytest.mark.parametrize("native_binding", [None, "original", "changed"])
async def test_bootstrap_restores_unsettled_native_ownership_before_all_ingress(
    tmp_path: Path, native_binding: str | None
) -> None:
    database_path = tmp_path / "restart.db"
    database = SqliteDatabase(database_path)
    await database.migrate()
    repository = SqliteAgentSessionRepository(database.session_factory)
    session = AgentSessionRecord(
        target_id="fixture-target",
        runtime_session=RuntimeSessionReference(
            runtime_binding_id="original", remote_session_id="remote-session"
        ),
        created_at=datetime.now(timezone.utc),
    )
    run_id = uuid4()
    try:
        await repository.add(session)
        assert await repository.claim_run(session, run_id)
        await repository.record_runtime_run(
            session.target_id,
            run_id,
            RuntimeRunHandle(runtime_binding_id="original", remote_run_id="remote-run"),
        )
    finally:
        await database.close()
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(advertised_base_url="http://mabrid.test"),
        storage=StorageConfig(sqlite_path=database_path),
        upstreams={"fixture": RuntimeUpstreamConfig(command="fixture-server")},
        endpoints=_endpoints(),
        diagnostic_upstream=None,
        agent_host=RuntimeAgentHostConfig(
            enabled=True,
            target_id="fixture-target",
            endpoint_slug="fixture",
            runtime=RuntimeHermesAgentConfig(
                base_url="http://hermes.test:8642/v1",
                api_key=SecretStr("fixture"),
                sessions=RuntimeHermesSessionConfig(
                    api_root="http://hermes.test:8642/native-prefix", binding_id=native_binding
                )
                if native_binding is not None
                else None,
            ),
        ),
    )
    result = await bootstrap_server(configuration)
    try:
        assert result.agent_host is not None
        assert (
            await result.agent_host.service.coordinator.active_run_id(session.target_id) == run_id
        )
        with pytest.raises(AgentRunConflictError):
            await anext(
                result.agent_host.service.run_events(
                    StartRunCommand(
                        model=session.target_id,
                        messages=(AgentMessage(role="user", content="Must not execute"),),
                    )
                )
            )
        if native_binding is None:
            assert result.agent_host.sessions is None
        else:
            assert result.agent_host.sessions is not None
            assert result.agent_host.sessions.coordinator is result.agent_host.service.coordinator
            assert result.agent_host.session_runtime is not None
    finally:
        if result.agent_host is not None:
            await result.agent_host.close()
        await result.database.close()


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
