---
description: "Use when: changing backend architecture, MCP layer boundaries, bridge manager, routing, session storage, upstream transports, or multi-upstream design."
applyTo:
  - "backend/src/mcpapps_bridge/**/*.py"
  - "docs/architecture/**/*.md"
---
# Bridge Architecture Guidance

## Product Boundary

This project is an MCP Apps Gateway. To the downstream agent runtime and model, the gateway should look like the intended MCP server and tools, not like a model-visible administration layer.

- Preserve MCP protocol semantics for `initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, and MCP Apps metadata.
- Keep bridge management, routing, storage, and frontend debugging concerns out of model-visible tool descriptions unless a task explicitly requires exposing them.
- Prefer streamable HTTP as the primary downstream transport. Keep SSE compatibility as fallback behavior, not the main design axis.
- Use explicit MCP-aware aggregate endpoints for configure-once clients. Do not use transparent TCP/HTTP interception as a substitute for MCP aggregation.
- Treat an adapter-driven Agent Host and its Run/Event API as an optional plane. Final assistant text is not observable from MCP server traffic alone.

## Ownership Decisions From The Manager Refactor

- `BridgeManager` owns managed endpoint lifecycle and all bridge session creation, lookup, activity tracking, and closure.
- A published endpoint owns stable routing and upstream binding definitions, not live MCP transport state.
- Each downstream MCP transport session is correlated with a bridge domain session. The transport session ID is not the domain session ID.
- Each passthrough bridge session owns one downstream MCP SDK `Server`, one transport session manager, one `UpstreamRuntime`, and one bridge session store.
- `UpstreamRuntime` belongs to one bridge session by default and owns one upstream MCP session, upstream identity, tool/resource caches, resource preloading, and state synchronization.
- `BridgeDownstreamServer` owns the downstream MCP SDK `Server` and transport sessions only.
- `ProxyHandlers` own MCP method behavior and session event recording.
- `mapper.py` must stay pure: no I/O, no session state, no transport logic.

Avoid designs where downstream transport code starts upstream runtimes, or where handler closures hide important dependencies. These make lifecycle and debugging unclear as routes, stores, and upstream transports grow.

## Future Extension Rules

- Use one ASGI listener with path-addressed endpoints such as `/mcp/github`, `/mcp/filesystem`, and `/mcp/all`; never allocate a port per managed server.
- Support both explicit endpoint modes: passthrough endpoints bind one upstream, while aggregate endpoints use unique binding namespaces for collision-safe routing.
- Isolate upstream MCP sessions per bridge session by default and open aggregate upstream connections lazily. Shared sessions require explicit configuration.
- Treat session storage as a manager-created, bridge-session-scoped dependency. Persistent stores must not leak database sessions into runtimes or handlers.
- Keep SQLAlchemy ORM models inside the persistence layer and translate them to persistence-independent domain models through async repositories.
- Keep agent adapters isolated from the generic bridge runtime. Adapter-specific behavior should not enter core MCP modules.
- Keep host/database settings in YAML or environment variables. Store managed servers, endpoints, bindings, and policies in the database; YAML topology import must be explicit.
- Prefer streamable HTTP. Keep stdio support on the same lifecycle contracts without adding special process pooling or process-count architecture.

## Documentation Expectations

When changing ownership boundaries, update `docs/architecture/mcp-layer.md` and `docs/architecture/repository-structure.md` in the same change. The docs should explain who owns lifecycle, session state, routes, transport hosting, and method behavior.