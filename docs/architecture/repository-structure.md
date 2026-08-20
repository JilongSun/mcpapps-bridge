# Repository Structure

## Backend Structure

```text
mcpapps-bridge/
|
├── backend/
│   ├── pyproject.toml                # Workspace and shared development tooling
│   ├── uv.lock
│   ├── packages/
│   │   ├── bridge-core/              # Reusable MCP protocol bridge
│   │   └── gateway-service/          # Application use cases, models, events, and ports
│   └── apps/server/
│       ├── pyproject.toml
│       ├── alembic.ini
│       ├── migrations/               # Versioned SQLite schema migrations
│       └── src/mcp_gateway_server/   # FastAPI, SQLite, config, CLI, composition
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

Allowed production dependencies:

```text
server ----------------> bridge-core
   `--> gateway-service ---> bridge-core
```

The migration in [ADR 0006](decisions/0006-core-service-and-server-packages.md) is complete. The
[bridge core contract](bridge-core-contract.md) is authoritative for cross-package types; new code
must not add dependencies that oppose this graph.

## Backend Layer Responsibilities

| Layer | Module | Role |
| --- | --- | --- |
| Config | `apps/server/.../config/` | Loads YAML and resolves bridge, storage, topology, and upstream configuration |
| Application models | `packages/gateway-service/.../management.py`, `revisions.py`, `sessions.py` | Defines topology heads, immutable revisions, policies, and session records |
| Application ports | `packages/gateway-service/.../ports.py` | Defines topology, session, and inspection persistence behavior |
| Coordinator | `packages/gateway-service/.../coordinator.py` | Publishes endpoints and coordinates persisted/core session lifecycles |
| Persistence | `apps/server/.../persistence/` | Implements SQLite lifecycle, SQLAlchemy adapters, topology reads, and session stores |
| Host | `apps/server/.../host/runtime.py` | Starts Uvicorn with the composed FastAPI app |
| API | `apps/server/.../api/app.py` | Dispatches stable `/mcp/{slug}` routes and exposes session snapshot/event APIs |
| Assembly | `apps/server/.../bootstrap.py`, `mcp/builder.py` | Opens SQLite, seeds topology, and injects adapters into the coordinator |
| Downstream | `packages/bridge-core/.../downstream.py` | Hosts the downstream MCP SDK `Server` and raw transport sessions |
| Engine | `packages/bridge-core/.../engine.py` | Owns worker task groups, router composition, core sessions, and upstream lifecycle |
| Handlers | `packages/bridge-core/.../handlers.py` | Implements MCP methods and emits correlated tool-call observations |
| Router | `packages/bridge-core/.../router.py` | Owns passthrough/aggregate routing, public names and URIs, discovery, and bridge observations |
| Runtime | `packages/bridge-core/.../runtime.py` | Proxies one upstream MCP session through a persistent owner task and maintains local caches |
| Upstream | `packages/bridge-core/.../upstream.py` | Connects to real MCP servers via stdio, SSE, or streamable HTTP |
| SDK adapter | `packages/bridge-core/.../_mcp_sdk.py` | Pure conversion between core models and MCP SDK v1 types |
| Inspection | `packages/gateway-service/.../inspection.py`, `events.py`, `session_store.py` | Defines durable snapshots/events and adapts core observations |

## Ownership Rules

- `GatewaySessionCoordinator` owns endpoint publication and application session lifecycle.
- `TopologyReader` returns complete immutable endpoint revisions; domain and MCP modules do not depend on SQLAlchemy joins or rows.
- `main.py` and FastAPI depend on coordinator operations and server-injected ports.
- `PublishedEndpoint` contains one resolved endpoint revision; it does not own live transport objects.
- Stable upstream and endpoint rows are management identities whose current pointers select immutable revisions. Binding revisions are routing edges from an endpoint revision to upstream revisions.
- Every bridge session captures `endpoint_revision_id`, keeping active-session routing stable when a current pointer changes.
- Each `BridgeSessionRuntime` owns one downstream MCP SDK server, one core `BridgeSession`, and one bridge session store correlated with one `mcp-session-id`.
- `BridgeDownstreamServer` owns downstream MCP transports only; it does not start or close the upstream runtime.
- Core `ProxyHandlers` depend on the narrow `McpMethodRouter`; routers and runtime consume only core
	plans and protocol models.
- `AggregateRouter` owns lazy bound runtimes, deterministic degraded discovery, namespaced tools, and exact public-to-upstream resource URI maps.
- An upstream runtime belongs to a bridge session by default; its engine-hosted worker enters, operates, and exits SDK transport contexts in one task. The runtime owns upstream protocol state and caches but does not know about HTTP routing.
- Core `ProxyHandlers` own method behavior and emit typed observations. `_mcp_sdk.py` owns SDK v1
	conversion; core upstream connectors map SDK responses directly to core models.
- `JournalBridgeObserver` converts core observations to application journal events;
	`BridgeSessionStoreJournal` adapts those events to the durable inspection store port.
- Persistent session storage satisfies `BridgeSessionStore`; runtime and handler code never depend on SQLAlchemy or database sessions directly.
- SQLite owns managed topology after the initial seed. YAML remains the source for host and storage settings and may seed topology only when the database is empty.
