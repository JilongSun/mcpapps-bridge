"""YAML configuration loading for the bridge runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import SecretStr, ValidationError

from .file import (
    AgentHostFileConfig,
    BridgeRuntimeConfig,
    MabridConfig,
    UpstreamFileConfig,
)
from .runtime import (
    RuntimeAgentHostConfig,
    RuntimeConfiguration,
    RuntimeHermesAgentConfig,
    RuntimeUpstreamConfig,
)

CONFIG_FILE_NAME = "mabrid.yaml"


class ConfigError(RuntimeError):
    """Raised when the bridge configuration is missing or invalid."""


@dataclass(frozen=True)
class LoadedBridgeConfig:
    path: Path
    config: MabridConfig


def load_bridge_config(path: str | None = None) -> LoadedBridgeConfig:
    config_path = _resolve_config_path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"Unable to read config file '{config_path}': {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in '{config_path}': {exc}") from exc

    try:
        config = MabridConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid bridge config in '{config_path}': {exc}") from exc

    return LoadedBridgeConfig(path=config_path, config=config)


def resolve_runtime_configuration(
    config_path: str | None,
    *,
    upstream_name: str | None,
    api_host: str | None,
    api_port: int | None,
    proxy_name: str | None,
    httpx_timeout_seconds: float | None = None,
) -> RuntimeConfiguration:
    loaded = load_bridge_config(config_path)
    load_dotenv(loaded.path.with_name(".env"), override=False)
    if upstream_name is not None and upstream_name not in loaded.config.upstreams:
        raise ConfigError(f"Unknown upstream '{upstream_name}'")
    bridge = _apply_bridge_overrides(
        loaded.config.bridge,
        upstream_name=upstream_name or "mabrid-gateway",
        api_host=api_host,
        api_port=api_port,
        proxy_name=proxy_name,
        httpx_timeout_seconds=httpx_timeout_seconds,
    )
    resolved_upstreams = {
        name: _to_runtime_upstream_config(upstream, loaded.path.parent, bridge)
        for name, upstream in loaded.config.upstreams.items()
    }
    sqlite_path = loaded.config.storage.sqlite_path
    if not sqlite_path.is_absolute():
        sqlite_path = (loaded.path.parent / sqlite_path).resolve()
    return RuntimeConfiguration(
        config_path=loaded.path,
        bridge=bridge,
        storage=loaded.config.storage.model_copy(update={"sqlite_path": sqlite_path}),
        upstreams=resolved_upstreams,
        endpoints=loaded.config.endpoints,
        diagnostic_upstream=upstream_name,
        agent_host=_resolve_agent_host_config(loaded.config.agent_host),
    )


def _resolve_agent_host_config(config: AgentHostFileConfig) -> RuntimeAgentHostConfig:
    runtime = config.runtime
    api_key = os.environ.get(runtime.api_key_env)
    if config.enabled and not api_key:
        raise ConfigError(
            f"Agent Host is enabled but environment variable '{runtime.api_key_env}' is not set"
        )
    return RuntimeAgentHostConfig(
        enabled=config.enabled,
        target_id=config.target_id,
        endpoint_slug=config.endpoint_slug,
        runtime=RuntimeHermesAgentConfig(
            integration=runtime.integration,
            interface=runtime.interface,
            base_url=str(runtime.base_url),
            api_key=SecretStr(api_key) if api_key is not None else None,
            timeout_seconds=runtime.timeout_seconds,
        ),
    )


def _resolve_config_path(path: str | None) -> Path:
    if path is not None:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise ConfigError(f"Config file not found: {resolved}")
        return resolved

    candidates = [Path.cwd() / CONFIG_FILE_NAME, _project_root() / CONFIG_FILE_NAME]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    expected = candidates[-1]
    raise ConfigError(
        f"No bridge config file found. Create '{CONFIG_FILE_NAME}' in the repo root or pass --config. Expected default path: {expected}"
    )


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / CONFIG_FILE_NAME).is_file():
            return parent
    return Path.cwd()


def _apply_bridge_overrides(
    bridge: BridgeRuntimeConfig,
    *,
    upstream_name: str,
    api_host: str | None,
    api_port: int | None,
    proxy_name: str | None,
    httpx_timeout_seconds: float | None = None,
) -> BridgeRuntimeConfig:
    updates: dict[str, object] = {}
    if api_host is not None:
        updates["api_host"] = api_host
    if api_port is not None:
        updates["api_port"] = api_port
    if proxy_name is not None:
        updates["proxy_name"] = proxy_name
    else:
        updates["proxy_name"] = bridge.proxy_name or upstream_name
    if httpx_timeout_seconds is not None:
        updates["httpx_timeout_seconds"] = httpx_timeout_seconds
    return bridge.model_copy(update=updates)


def _to_runtime_upstream_config(
    upstream: UpstreamFileConfig,
    config_dir: Path,
    bridge: BridgeRuntimeConfig,
) -> RuntimeUpstreamConfig:
    cwd = upstream.cwd
    if cwd is not None and not cwd.is_absolute():
        cwd = (config_dir / cwd).resolve()

    return RuntimeUpstreamConfig(
        transport=upstream.transport,
        command=upstream.command,
        args=upstream.args,
        cwd=cwd,
        env=upstream.env,
        url=upstream.url,
        headers=upstream.headers,
        httpx_timeout_seconds=bridge.httpx_timeout_seconds,
    )
