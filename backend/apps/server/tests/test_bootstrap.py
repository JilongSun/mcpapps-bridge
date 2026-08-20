from __future__ import annotations

from pathlib import Path

from mcp_gateway_server.bootstrap import bootstrap_gateway
from mcp_gateway_server.config import (
    BridgeRuntimeConfig,
    RuntimeConfiguration,
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
