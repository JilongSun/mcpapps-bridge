from __future__ import annotations

from pathlib import Path

import pytest

from mabrid.server.config import (
    CONFIG_FILE_NAME,
    ConfigError,
    StorageConfig,
    build_advertised_mcp_url,
    resolve_runtime_configuration,
)


def test_mabrid_owns_default_deployment_identifiers() -> None:
    assert CONFIG_FILE_NAME == "mabrid.yaml"
    assert StorageConfig().sqlite_path == Path("backend/var/mabrid.db")


def _write_config(path: Path) -> None:
    path.write_text(
        """
bridge:
    advertisedBaseUrl: http://mabrid.test:8765
agentHost:
    enabled: true
    targetId: fixture-target
    endpointSlug: fixture
    runtime:
        integration: hermes
        interface: openai-chat-completions
        baseUrl: http://hermes.test:8642/v1
        apiKeyEnv: FIXTURE_HERMES_KEY
endpoints:
    fixture:
        bindings:
            - upstream: fixture
upstreams:
    fixture:
        transport: stdio
        command: fixture-server
""",
        encoding="utf-8",
    )


def test_enabled_agent_host_resolves_api_key_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    _write_config(config_path)
    monkeypatch.setenv("FIXTURE_HERMES_KEY", "fixture-secret")

    configuration = resolve_runtime_configuration(
        str(config_path),
        upstream_name=None,
        api_host=None,
        api_port=None,
        proxy_name=None,
    )

    assert configuration.agent_host.enabled is True
    assert configuration.agent_host.target_id == "fixture-target"
    assert configuration.agent_host.endpoint_slug == "fixture"
    assert configuration.agent_host.runtime.integration == "hermes"
    assert configuration.agent_host.runtime.interface == "openai-chat-completions"
    assert configuration.agent_host.runtime.base_url == "http://hermes.test:8642/v1"
    assert configuration.agent_host.runtime.api_key is not None
    assert configuration.agent_host.runtime.api_key.get_secret_value() == "fixture-secret"
    assert configuration.bridge.advertised_base_url == "http://mabrid.test:8765"


def test_enabled_agent_host_requires_configured_api_key_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    _write_config(config_path)
    monkeypatch.delenv("FIXTURE_HERMES_KEY", raising=False)

    with pytest.raises(ConfigError, match="FIXTURE_HERMES_KEY"):
        resolve_runtime_configuration(
            str(config_path),
            upstream_name=None,
            api_host=None,
            api_port=None,
            proxy_name=None,
        )


def test_agent_host_uses_hermes_api_server_key_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
bridge: {advertisedBaseUrl: http://mabrid.test:8765}
agentHost: {enabled: true, targetId: fixture-target, endpointSlug: fixture}
endpoints:
    fixture:
        bindings: [{upstream: fixture}]
upstreams:
  fixture:
    transport: stdio
    command: fixture-server
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("API_SERVER_KEY", "fixture-secret")

    configuration = resolve_runtime_configuration(
        str(config_path),
        upstream_name=None,
        api_host=None,
        api_port=None,
        proxy_name=None,
    )

    assert configuration.agent_host.runtime.api_key is not None
    assert configuration.agent_host.runtime.api_key.get_secret_value() == "fixture-secret"


def test_agent_host_loads_api_key_from_dotenv_next_to_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
bridge: {advertisedBaseUrl: http://mabrid.test:8765}
agentHost: {enabled: true, targetId: fixture-target, endpointSlug: fixture}
endpoints:
    fixture:
        bindings: [{upstream: fixture}]
upstreams:
  fixture:
    transport: stdio
    command: fixture-server
""",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("API_SERVER_KEY=dotenv-secret\n", encoding="utf-8")
    monkeypatch.delenv("API_SERVER_KEY", raising=False)

    configuration = resolve_runtime_configuration(
        str(config_path),
        upstream_name=None,
        api_host=None,
        api_port=None,
        proxy_name=None,
    )

    assert configuration.agent_host.runtime.api_key is not None
    assert configuration.agent_host.runtime.api_key.get_secret_value() == "dotenv-secret"


def test_process_environment_takes_precedence_over_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
bridge: {advertisedBaseUrl: http://mabrid.test:8765}
agentHost: {enabled: true, targetId: fixture-target, endpointSlug: fixture}
endpoints:
    fixture:
        bindings: [{upstream: fixture}]
upstreams:
  fixture:
    transport: stdio
    command: fixture-server
""",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("API_SERVER_KEY=dotenv-secret\n", encoding="utf-8")
    monkeypatch.setenv("API_SERVER_KEY", "process-secret")

    configuration = resolve_runtime_configuration(
        str(config_path),
        upstream_name=None,
        api_host=None,
        api_port=None,
        proxy_name=None,
    )

    assert configuration.agent_host.runtime.api_key is not None
    assert configuration.agent_host.runtime.api_key.get_secret_value() == "process-secret"


def test_agent_host_rejects_an_unknown_runtime_integration(tmp_path: Path) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
bridge: {advertisedBaseUrl: http://mabrid.test:8765}
agentHost:
  enabled: true
  targetId: fixture-target
  endpointSlug: fixture
  runtime:
        integration: unknown
endpoints:
    fixture:
        bindings: [{upstream: fixture}]
upstreams:
  fixture:
    transport: stdio
    command: fixture-server
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="integration"):
        resolve_runtime_configuration(
            str(config_path),
            upstream_name=None,
            api_host=None,
            api_port=None,
            proxy_name=None,
        )


def test_configuration_requires_explicit_endpoints(tmp_path: Path) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
upstreams:
  fixture:
    transport: stdio
    command: fixture-server
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="endpoints"):
        resolve_runtime_configuration(
            str(config_path),
            upstream_name=None,
            api_host=None,
            api_port=None,
            proxy_name=None,
        )


def test_enabled_agent_host_requires_advertised_base_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
agentHost: {enabled: true, targetId: fixture-target, endpointSlug: fixture}
endpoints:
    fixture:
        bindings: [{upstream: fixture}]
upstreams:
    fixture:
        transport: stdio
        command: fixture-server
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("API_SERVER_KEY", "fixture-secret")

    with pytest.raises(ConfigError, match="advertisedBaseUrl"):
        resolve_runtime_configuration(
            str(config_path),
            upstream_name=None,
            api_host=None,
            api_port=None,
            proxy_name=None,
        )


def test_disabled_agent_host_allows_missing_advertised_base_url(tmp_path: Path) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
agentHost: {enabled: false}
endpoints:
    fixture:
        bindings: [{upstream: fixture}]
upstreams:
    fixture:
        transport: stdio
        command: fixture-server
""",
        encoding="utf-8",
    )

    configuration = resolve_runtime_configuration(
        str(config_path),
        upstream_name=None,
        api_host=None,
        api_port=None,
        proxy_name=None,
    )

    assert configuration.bridge.advertised_base_url is None


@pytest.mark.parametrize(
    "advertised_base_url",
    [
        "ftp://mabrid.test",
        "http://mabrid.test/prefix",
        "http://mabrid.test?tenant=one",
        "http://mabrid.test#internal",
        "http://user:password@mabrid.test",
        "http:///missing-host",
    ],
)
def test_configuration_rejects_invalid_advertised_base_url(
    tmp_path: Path,
    advertised_base_url: str,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        f"""
bridge:
    advertisedBaseUrl: {advertised_base_url}
endpoints:
    fixture:
        bindings: [{{upstream: fixture}}]
upstreams:
    fixture:
        transport: stdio
        command: fixture-server
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="advertisedBaseUrl"):
        resolve_runtime_configuration(
            str(config_path),
            upstream_name=None,
            api_host=None,
            api_port=None,
            proxy_name=None,
        )


def test_advertised_base_url_is_normalized_and_independent_of_listener_overrides(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
bridge:
    advertisedBaseUrl: https://mabrid.example.test/
endpoints:
    fixture:
        bindings: [{upstream: fixture}]
upstreams:
    fixture:
        transport: stdio
        command: fixture-server
""",
        encoding="utf-8",
    )

    configuration = resolve_runtime_configuration(
        str(config_path),
        upstream_name=None,
        api_host="0.0.0.0",
        api_port=9000,
        proxy_name=None,
    )

    assert configuration.bridge.api_host == "0.0.0.0"
    assert configuration.bridge.api_port == 9000
    assert configuration.bridge.advertised_base_url == "https://mabrid.example.test"


def test_build_advertised_mcp_url_uses_the_validated_origin() -> None:
    assert (
        build_advertised_mcp_url("https://mabrid.example.test", "test-endpoint")
        == "https://mabrid.example.test/mcp/test-endpoint"
    )
