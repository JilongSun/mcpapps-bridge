"""YAML configuration loading for the bridge runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from mcpapps_bridge.mcp import UpstreamServerConfig

from .models import BridgeRuntimeConfig, McpAppsBridgeConfig, UpstreamFileConfig

CONFIG_FILE_NAME = "mcpapps-bridge.yaml"


class ConfigError(RuntimeError):
    """Raised when the bridge configuration is missing or invalid."""


@dataclass(frozen=True)
class LoadedBridgeConfig:
    path: Path
    config: McpAppsBridgeConfig


@dataclass(frozen=True)
class RuntimeSelection:
    config_path: Path
    upstream_name: str
    bridge: BridgeRuntimeConfig
    upstream: UpstreamServerConfig


def load_bridge_config(path: str | None = None) -> LoadedBridgeConfig:
    config_path = _resolve_config_path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"Unable to read config file '{config_path}': {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in '{config_path}': {exc}") from exc

    try:
        config = McpAppsBridgeConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid bridge config in '{config_path}': {exc}") from exc

    return LoadedBridgeConfig(path=config_path, config=config)


def resolve_runtime_selection(
    config_path: str | None,
    *,
    upstream_name: str | None,
    api_host: str | None,
    api_port: int | None,
    proxy_name: str | None,
    httpx_timeout_seconds: float | None = None,
) -> RuntimeSelection:
    loaded = load_bridge_config(config_path)
    selected_upstream_name, upstream = _select_upstream(loaded.config, upstream_name)
    bridge = _apply_bridge_overrides(
        loaded.config.bridge,
        upstream_name=selected_upstream_name,
        api_host=api_host,
        api_port=api_port,
        proxy_name=proxy_name,
        httpx_timeout_seconds=httpx_timeout_seconds,
    )
    return RuntimeSelection(
        config_path=loaded.path,
        upstream_name=selected_upstream_name,
        bridge=bridge,
        upstream=_to_runtime_upstream_config(upstream, loaded.path.parent, bridge),
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
    return Path(__file__).resolve().parents[4]


def _select_upstream(
    config: McpAppsBridgeConfig,
    requested_name: str | None,
) -> tuple[str, UpstreamFileConfig]:
    if requested_name is not None:
        upstream = config.upstreams.get(requested_name)
        if upstream is None:
            raise ConfigError(f"Unknown upstream '{requested_name}'")
        return requested_name, upstream

    if config.default_upstream is not None:
        return config.default_upstream, config.upstreams[config.default_upstream]

    if len(config.upstreams) == 1:
        name, upstream = next(iter(config.upstreams.items()))
        return name, upstream

    available = ", ".join(sorted(config.upstreams))
    raise ConfigError(
        f"Multiple upstreams are configured ({available}). Choose one with --upstream or set defaultUpstream in YAML."
    )


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
) -> UpstreamServerConfig:
    cwd = upstream.cwd
    if cwd is not None and not cwd.is_absolute():
        cwd = (config_dir / cwd).resolve()

    return UpstreamServerConfig(
        transport=upstream.transport,
        command=upstream.command,
        args=upstream.args,
        cwd=cwd,
        env=upstream.env,
        url=upstream.url,
        headers=upstream.headers,
        httpx_timeout_seconds=bridge.httpx_timeout_seconds,
    )
