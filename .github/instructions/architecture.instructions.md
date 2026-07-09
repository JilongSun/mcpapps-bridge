---
description: "Use when: changing backend architecture, MCP layer boundaries, bridge manager, routing, session storage, upstream transports, or multi-upstream design."
applyTo:
  - "backend/src/mcpapps_bridge/**/*.py"
  - "docs/architecture/**/*.md"
---
# Bridge Architecture Guidance

## Product Boundary

This project is a transparent MCP Apps bridge host. To the downstream agent runtime and model, the bridge should look like the intended MCP server and tools, not like a model-visible bridge administration layer.

- Preserve MCP protocol semantics for `initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, and MCP Apps metadata.
- Keep bridge management, routing, storage, and frontend debugging concerns out of model-visible tool descriptions unless a task explicitly requires exposing them.
- Prefer streamable HTTP as the primary downstream transport. Keep SSE compatibility as fallback behavior, not the main design axis.

## Ownership Decisions From The Manager Refactor

- `BridgeManager` owns MCP route lifecycle at the backend-process level.
- `BridgeRoute` owns the binding between one downstream endpoint, one upstream runtime, and one route-scoped session store.
- `UpstreamRuntime` owns one upstream MCP session, upstream identity, tool/resource caches, resource preloading, and state synchronization.
- `BridgeDownstreamServer` owns the downstream MCP SDK `Server` and transport sessions only.
- `ProxyHandlers` own MCP method behavior and session event recording.
- `mapper.py` must stay pure: no I/O, no session state, no transport logic.

Avoid designs where downstream transport code starts upstream runtimes, or where handler closures hide important dependencies. These make lifecycle and debugging unclear as routes, stores, and upstream transports grow.

## Future Extension Rules

- Default multi-upstream design is one upstream per downstream route, for example `/mcp/github` and `/mcp/filesystem`.
- Add aggregation only as an explicit layer above route ownership, after a concrete use case proves it is needed.
- Treat session storage as a route-owned dependency. New persistent stores should implement `BridgeSessionStore` rather than leaking database APIs into runtimes or handlers.
- Keep agent adapters isolated from the generic bridge runtime. Adapter-specific behavior should not enter core MCP modules.
- Prefer config-level choices over low-level CLI flags. Runtime startup should remain YAML-driven and friendly to local debugging.

## Documentation Expectations

When changing ownership boundaries, update `docs/architecture/mcp-layer.md` and `docs/architecture/repository-structure.md` in the same change. The docs should explain who owns lifecycle, session state, routes, transport hosting, and method behavior.