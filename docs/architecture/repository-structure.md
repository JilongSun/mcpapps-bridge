# Repository Structure

```text
mcpapps-bridge/
|
├── backend/                          # Python bridge host
│   ├── pyproject.toml
│   └── src/mcpapps_bridge/
│       ├── main.py                   # YAML-driven backend CLI entry point
│       ├── api/                      # FastAPI HTTP + WebSocket control plane
│       ├── host/                     # Process-level Uvicorn orchestration
│       ├── config/                   # Typed YAML config loading and runtime selection
│       ├── domain/                   # Managed topology and session domain contracts
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── manager.py            # BridgeManager and BridgeRoute lifecycle ownership
│       │   ├── upstream.py           # Upstream MCP clients: stdio, SSE, streamable HTTP
│       │   ├── runtime.py            # UpstreamRuntime: upstream lifecycle, cache, state sync
│       │   ├── downstream.py         # Downstream MCP Server + HTTP/SSE/stdio transports
│       │   ├── handlers.py           # ProxyHandlers for tools and resources methods
│       │   ├── mapper.py             # Internal models <-> MCP SDK type conversion
│       │   └── proxy.py              # Assembly helper that builds the current manager
│       ├── session/                  # Session store protocol and in-memory implementation
│       ├── events/                   # Typed event envelopes
│       ├── models/                   # Shared Pydantic protocol/session/resource models
│       └── agent_adapters/           # Agent-specific wiring (future)
│
├── frontend/                         # React debugging + session surface
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── types.ts
│       ├── hooks/
│       └── styles.css
│
├── scripts/                          # Development launchers and support scripts
├── docs/architecture/                # Architecture notes
│   └── decisions/                    # Accepted architecture decision records
├── .github/instructions/             # Committed project and agent instructions
├── mcpapps-bridge.yaml.example       # Example bridge runtime configuration
├── mcpapps-bridge.yaml               # Local bridge runtime configuration
├── justfile                          # Root task commands
├── README.md
└── LICENSE
```

## Backend Layer Responsibilities

| Layer | Module | Role |
| --- | --- | --- |
| Config | `config/` | Loads YAML, validates bridge/upstream config, resolves runtime selection |
| Domain | `domain/` | Defines persistence-independent upstream, endpoint, binding, policy, and session contracts |
| Host | `host/runtime.py` | Starts Uvicorn with one `BridgeManager`-backed FastAPI app |
| API | `api/app.py` | Mounts MCP routes and exposes session snapshot/event APIs |
| Manager | `mcp/manager.py` | Owns routes, lifecycle, and route-scoped session stores |
| Assembly | `mcp/proxy.py` | Builds the current single-route `BridgeManager` from config |
| Downstream | `mcp/downstream.py` | Hosts the downstream MCP SDK `Server` and transport sessions |
| Handlers | `mcp/handlers.py` | Implements MCP methods and records session events |
| Runtime | `mcp/runtime.py` | Owns one upstream MCP session, caches, resource preloading, and state sync |
| Upstream | `mcp/upstream.py` | Connects to real MCP servers via stdio, SSE, or streamable HTTP |
| Mapper | `mcp/mapper.py` | Pure conversion between bridge models and MCP SDK types |
| Session | `session/` | Defines `BridgeSessionStore` and the in-memory `BridgeSessionState` |
| Events | `events/` | Typed events emitted by session/runtime operations |
| Models | `models/` | Canonical Pydantic models shared across backend layers |

## Ownership Rules

- `BridgeManager` is the lifecycle owner for MCP endpoints and creates, resolves, and closes bridge sessions.
- The current `BridgeRoute` with one fixed session store is transitional; managed endpoints and per-client bridge sessions replace it.
- `BridgeDownstreamServer` owns downstream MCP transports only; it does not start or close the upstream runtime.
- An upstream runtime belongs to a bridge session by default; it owns upstream protocol state and caches but does not know about HTTP routing.
- `ProxyHandlers` own method behavior and session event recording, while `mapper.py` remains pure conversion logic.
- Future persistent session storage should satisfy `BridgeSessionStore` rather than forcing runtime or handler code to depend on a database directly.
