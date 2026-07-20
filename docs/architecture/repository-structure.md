# Repository Structure

```text
mcpapps-bridge/
|
├── backend/                          # Python MCP Apps Gateway backend
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/                   # Versioned database schema migrations
│   └── src/mcpapps_bridge/
│       ├── main.py                   # YAML-driven backend CLI entry point
│       ├── bootstrap.py              # Memory/SQLite application composition root
│       ├── api/                      # FastAPI HTTP + WebSocket control plane
│       ├── host/                     # Process-level Uvicorn orchestration
│       ├── config/                   # Typed YAML config and runtime configuration
│       ├── domain/                   # Managed topology and session domain contracts
│       ├── repositories/             # Async repository ports and in-memory adapters
│       ├── persistence/              # SQLAlchemy models, repositories, stores, and database
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── manager.py            # Managed endpoints, sessions, and lifecycle ownership
│       │   ├── builder.py            # Compatibility and repository-based manager assembly
│       │   ├── upstream.py           # Upstream MCP clients: stdio, SSE, streamable HTTP
│       │   ├── runtime.py            # UpstreamRuntime: upstream lifecycle, cache, state sync
│       │   ├── router.py             # Session MCP router port and passthrough adapter
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
| Config | `config/` | Loads YAML and resolves bridge, storage, topology, and upstream configuration |
| Domain | `domain/` | Defines persistence-independent topology heads, immutable revisions, bindings, policies, and sessions |
| Repositories | `repositories/` | Defines async management/session repositories, the resolved `TopologyReader` port, and memory adapters |
| Persistence | `persistence/` | Implements SQLite lifecycle, SQLAlchemy heads and revisions, repository adapters, topology reads, and session stores |
| Host | `host/runtime.py` | Starts Uvicorn with one `BridgeManager`-backed FastAPI app |
| API | `api/app.py` | Dispatches stable `/mcp/{slug}` routes and exposes manager-backed session snapshot/event APIs |
| Manager | `mcp/manager.py` | Owns topology registration, session creation, endpoint runtime assembly, and lifecycle |
| Assembly | `bootstrap.py`, `mcp/builder.py` | Selects storage adapters, seeds initial topology, and injects repository/store ports into the manager |
| Downstream | `mcp/downstream.py` | Hosts the downstream MCP SDK `Server` and transport sessions |
| Handlers | `mcp/handlers.py` | Implements MCP methods and records session events |
| Router | `mcp/router.py` | Defines handler-facing session routing and adapts passthrough behavior |
| Runtime | `mcp/runtime.py` | Owns one upstream MCP session, caches, resource preloading, and state sync |
| Upstream | `mcp/upstream.py` | Connects to real MCP servers via stdio, SSE, or streamable HTTP |
| Mapper | `mcp/mapper.py` | Pure conversion between bridge models and MCP SDK types |
| Session | `session/` | Defines `BridgeSessionStore`, `BridgeSessionStoreFactory`, and in-memory implementations |
| Events | `events/` | Typed events emitted by session/runtime operations |
| Models | `models/` | Canonical Pydantic models shared across backend layers |

## Ownership Rules

- `BridgeManager` is the lifecycle owner for MCP endpoints and creates, resolves, and closes bridge sessions.
- `TopologyReader` returns complete immutable endpoint revisions; domain and MCP modules do not depend on SQLAlchemy joins or rows.
- `main.py`, FastAPI, and builders do not create session stores; they depend on manager operations and injected ports.
- `PublishedEndpoint` contains one resolved endpoint revision and its routed upstream revision; it does not own live transport objects.
- Stable upstream and endpoint rows are management identities whose current pointers select immutable revisions. Binding revisions are routing edges from an endpoint revision to upstream revisions.
- Every bridge session captures `endpoint_revision_id`, keeping active-session routing stable when a current pointer changes.
- Each `PassthroughSessionRuntime` owns one downstream MCP SDK server, one upstream runtime, and one bridge session store correlated with one `mcp-session-id`.
- `BridgeDownstreamServer` owns downstream MCP transports only; it does not start or close the upstream runtime.
- `ProxyHandlers` depend on `McpSessionRouter`, not directly on single-upstream runtime details.
- An upstream runtime belongs to a bridge session by default; it owns upstream protocol state and caches but does not know about HTTP routing.
- `ProxyHandlers` own method behavior and session event recording, while `mapper.py` remains pure conversion logic.
- Persistent session storage satisfies `BridgeSessionStore`; runtime and handler code never depend on SQLAlchemy or database sessions directly.
- SQLite owns managed topology after the initial seed. YAML remains the source for host and storage settings and may seed topology only when the database is empty.
