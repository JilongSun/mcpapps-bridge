# Repository Structure

## Current Structure

```text
mcpapps-bridge/
|
├── backend/                          # Python MCP Apps Gateway backend
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/                   # Versioned database schema migrations
│   └── src/mcpapps_bridge/
│       ├── main.py                   # YAML-driven backend CLI entry point
│       ├── bootstrap.py              # SQLite application composition root
│       ├── api/                      # FastAPI HTTP + WebSocket control plane
│       ├── host/                     # Process-level Uvicorn orchestration
│       ├── config/                   # Typed YAML config and runtime configuration
│       ├── domain/                   # Managed topology and session domain contracts
│       ├── repositories/             # Async repository and topology reader ports
│       ├── persistence/              # SQLAlchemy models, repositories, stores, and database
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── manager.py            # Managed endpoints, sessions, and lifecycle ownership
│       │   ├── builder.py            # Repository-based manager assembly
│       │   ├── downstream.py         # Downstream MCP Server + HTTP/SSE/stdio transports
│       │   └── plan_adapter.py       # Temporary managed revision -> core plan adapter
│       ├── session/                  # Session store and factory ports
│       ├── events/                   # Typed event envelopes
│       ├── models/                   # Shared Pydantic protocol/session/resource models
│       └── agent_adapters/           # Agent-specific wiring (future)
│
├── frontend/                         # React management and Agent Host surface
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

## Target Backend Structure

[ADR 0006](decisions/0006-core-service-and-server-packages.md) replaces the single backend package
through a staged `uv` workspace migration. Directory and distribution names are internal working
names; the post-v0.1 product brand is a separate decision.

```text
backend/
|-- pyproject.toml                    # uv workspace and shared development tooling
|-- uv.lock
|-- packages/
|   |-- bridge-core/
|   |   |-- pyproject.toml
|   |   `-- src/                      # Plans, observations, handlers, routing, runtime, SDK adapters
|   `-- gateway-service/
|       |-- pyproject.toml
|       `-- src/                      # Topology, sessions, events, Agent Host, ports
`-- apps/
	`-- server/
		|-- pyproject.toml
		|-- migrations/               # Server-owned SQLite schema
		`-- src/                      # FastAPI, SQLite, adapters, CLI, composition
```

Allowed production dependencies:

```text
server ----------------> bridge-core
   `--> gateway-service ---> bridge-core
```

The workspace members and core contract models now exist. MCP SDK mapping, downstream method
handlers, routing, the upstream owner-task runtime, and upstream SDK connectors live in bridge
core. Raw downstream transport hosting remains in the current server module tree until its
extraction step lands. The
[bridge core contract](bridge-core-contract.md) is authoritative for new cross-package types; new
code must not add dependencies that oppose the target graph.

## Backend Layer Responsibilities

| Layer | Module | Role |
| --- | --- | --- |
| Config | `config/` | Loads YAML and resolves bridge, storage, topology, and upstream configuration |
| Domain | `domain/` | Defines persistence-independent topology heads, immutable revisions, bindings, policies, and sessions |
| Repositories | `repositories/` | Defines async management/session repositories and the resolved `TopologyReader` port |
| Persistence | `persistence/` | Implements SQLite lifecycle, SQLAlchemy heads and revisions, repository adapters, topology reads, and session stores |
| Host | `host/runtime.py` | Starts Uvicorn with one `BridgeManager`-backed FastAPI app |
| API | `api/app.py` | Dispatches stable `/mcp/{slug}` routes and exposes manager-backed session snapshot/event APIs |
| Manager | `mcp/manager.py` | Owns topology registration, session creation, endpoint runtime and observer assembly, and lifecycle |
| Assembly | `bootstrap.py`, `mcp/builder.py` | Opens configured SQLite storage, seeds initial topology, and injects repository/store ports into the manager |
| Downstream | `mcp/downstream.py` | Hosts the downstream MCP SDK `Server` and transport sessions |
| Handlers | `packages/bridge-core/.../handlers.py` | Implements MCP methods and emits correlated tool-call observations |
| Router | `packages/bridge-core/.../router.py` | Owns passthrough/aggregate routing, public names and URIs, discovery, and bridge observations |
| Runtime | `packages/bridge-core/.../runtime.py` | Proxies one upstream MCP session through a persistent owner task and maintains local caches |
| Upstream | `packages/bridge-core/.../upstream.py` | Connects to real MCP servers via stdio, SSE, or streamable HTTP |
| SDK adapter | `packages/bridge-core/.../_mcp_sdk.py` | Pure conversion between core models and MCP SDK v1 types |
| Transitional adapter | `mcp/plan_adapter.py` | Converts current managed revisions to core plans |
| Session | `session/` | Defines current store/factory ports and the transitional application journal adapter |
| Events | `events/` | Typed events emitted by session/runtime operations |
| Models | `models/` | Canonical Pydantic models shared across backend layers |

## Ownership Rules

- `BridgeManager` is the lifecycle owner for MCP endpoints and creates, resolves, and closes bridge sessions.
- `TopologyReader` returns complete immutable endpoint revisions; domain and MCP modules do not depend on SQLAlchemy joins or rows.
- `main.py`, FastAPI, and builders do not create session stores; they depend on manager operations and injected ports.
- `PublishedEndpoint` contains one resolved endpoint revision; it does not own live transport objects.
- Stable upstream and endpoint rows are management identities whose current pointers select immutable revisions. Binding revisions are routing edges from an endpoint revision to upstream revisions.
- Every bridge session captures `endpoint_revision_id`, keeping active-session routing stable when a current pointer changes.
- Each `BridgeSessionRuntime` owns one downstream MCP SDK server, one router, and one bridge session store correlated with one `mcp-session-id`.
- `BridgeDownstreamServer` owns downstream MCP transports only; it does not start or close the upstream runtime.
- Core `ProxyHandlers` depend on the narrow `McpMethodRouter`; routers and runtime consume only core
	plans and protocol models.
- `AggregateRouter` owns lazy bound runtimes, deterministic degraded discovery, namespaced tools, and exact public-to-upstream resource URI maps.
- An upstream runtime belongs to a bridge session by default; its manager-hosted worker enters, operates, and exits SDK transport contexts in one task. The runtime owns upstream protocol state and caches but does not know about HTTP routing.
- Core `ProxyHandlers` own method behavior and emit typed observations. `_mcp_sdk.py` owns SDK v1
	conversion; core upstream connectors map SDK responses directly to core models.
- `JournalBridgeObserver` converts core observations to application journal events;
	`BridgeSessionStoreJournal` adapts those events to the current durable store during migration.
- Persistent session storage satisfies `BridgeSessionStore`; runtime and handler code never depend on SQLAlchemy or database sessions directly.
- SQLite owns managed topology after the initial seed. YAML remains the source for host and storage settings and may seed topology only when the database is empty.
