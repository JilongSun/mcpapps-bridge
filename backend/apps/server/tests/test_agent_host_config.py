from __future__ import annotations

from pathlib import Path

import pytest

from mcp_gateway_server.config import ConfigError, resolve_runtime_configuration


def _write_config(path: Path) -> None:
    path.write_text(
        """
agentHost:
  enabled: true
  baseUrl: http://hermes.test:8642/v1
  apiKeyEnv: FIXTURE_HERMES_KEY
defaultUpstream: fixture
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
    assert configuration.agent_host.base_url == "http://hermes.test:8642/v1"
    assert configuration.agent_host.api_key is not None
    assert configuration.agent_host.api_key.get_secret_value() == "fixture-secret"


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
agentHost:
  enabled: true
defaultUpstream: fixture
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

    assert configuration.agent_host.api_key is not None
    assert configuration.agent_host.api_key.get_secret_value() == "fixture-secret"


def test_agent_host_loads_api_key_from_dotenv_next_to_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
agentHost:
  enabled: true
defaultUpstream: fixture
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

    assert configuration.agent_host.api_key is not None
    assert configuration.agent_host.api_key.get_secret_value() == "dotenv-secret"


def test_process_environment_takes_precedence_over_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text(
        """
agentHost:
  enabled: true
defaultUpstream: fixture
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

    assert configuration.agent_host.api_key is not None
    assert configuration.agent_host.api_key.get_secret_value() == "process-secret"
