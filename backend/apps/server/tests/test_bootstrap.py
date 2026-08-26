from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from mcp_gateway_service import AgentCapability, AgentRuntimeInterface

from mcp_gateway_server.bootstrap import bootstrap_gateway
from mcp_gateway_server.config import (
    BridgeRuntimeConfig,
    RuntimeAgentHostConfig,
    RuntimeConfiguration,
    RuntimeHermesAgentConfig,
    RuntimeUpstreamConfig,
    StorageConfig,
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
        endpoints={},
        default_upstream="fixture",
    )

    result = await bootstrap_gateway(configuration)
    try:
        assert [endpoint.revision.slug for endpoint in result.manager.published_endpoints] == [
            "fixture"
        ]
        assert configuration.storage.sqlite_path.is_file()
    finally:
        await result.storage.close()


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
        endpoints={},
        default_upstream="fixture",
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

    result = await bootstrap_gateway(configuration)
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
        await result.storage.close()


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
        endpoints={},
        default_upstream="fixture",
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
        await bootstrap_gateway(configuration)
    except ValueError as exc:
        assert "missing-endpoint" in str(exc)
        assert "not published and enabled" in str(exc)
    else:
        raise AssertionError("bootstrap accepted an unpublished Agent Target endpoint")
