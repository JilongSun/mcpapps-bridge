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
│       ├── repositories/             # Async repository ports and in-memory adapters
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── manager.py            # Managed endpoints, sessions, and lifecycle ownership
│       │   ├── builder.py            # Current in-memory application assembly
│       │   ├── upstream.py           # Upstream MCP clients: stdio, SSE, streamable HTTP
│       │   ├── runtime.py            # UpstreamRuntime: upstream lifecycle, cache, state sync
│       │   ├── downstream.py         # Downstream MCP Server + HTTP/SSE/stdio transports
│       │   ├── handlers.py           # ProxyHandlers for tools and resources methods
│       │   └── mapper.py             # Internal models <-> MCP SDK type conversion
│       ├── session/                  # Store port, factory port, and in-memory adapter
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
| Repositories | `repositories/` | Defines async topology/session repository ports and concurrency-safe in-memory adapters |
| Host | `host/runtime.py` | Starts Uvicorn with one `BridgeManager`-backed FastAPI app |
| API | `api/app.py` | Mounts published endpoints and exposes manager-backed session snapshot/event APIs |
| Manager | `mcp/manager.py` | Owns topology registration, session creation, endpoint runtime assembly, and lifecycle |
| Assembly | `mcp/builder.py` | Converts the selected YAML upstream to seed definitions and injects in-memory adapters |
| Downstream | `mcp/downstream.py` | Hosts the downstream MCP SDK `Server` and transport sessions |
| Handlers | `mcp/handlers.py` | Implements MCP methods and records session events |
| Runtime | `mcp/runtime.py` | Owns one upstream MCP session, caches, resource preloading, and state sync |
| Upstream | `mcp/upstream.py` | Connects to real MCP servers via stdio, SSE, or streamable HTTP |
| Mapper | `mcp/mapper.py` | Pure conversion between bridge models and MCP SDK types |
| Session | `session/` | Defines `BridgeSessionStore`, `BridgeSessionStoreFactory`, and in-memory implementations |
| Events | `events/` | Typed events emitted by session/runtime operations |
| Models | `models/` | Canonical Pydantic models shared across backend layers |

## Ownership Rules

- `BridgeManager` is the lifecycle owner for MCP endpoints and creates, resolves, and closes bridge sessions.
- `main.py`, FastAPI, and builders do not create session stores; they depend on manager operations and injected ports.
- The current `PublishedEndpoint` bootstrap session is transitional until the downstream transport dispatcher activates one manager-owned session per `mcp-session-id`.
- `BridgeDownstreamServer` owns downstream MCP transports only; it does not start or close the upstream runtime.
- An upstream runtime belongs to a bridge session by default; it owns upstream protocol state and caches but does not know about HTTP routing.
- `ProxyHandlers` own method behavior and session event recording, while `mapper.py` remains pure conversion logic.
- Future persistent session storage should satisfy `BridgeSessionStore` rather than forcing runtime or handler code to depend on a database directly.
