# MCP Layer Architecture

The `mcp/` package is the protocol-aware bridge boundary between downstream MCP clients and real upstream MCP servers. Downstream clients should experience the selected upstream as a normal MCP server: tools, resources, initialization metadata, and MCP Apps annotations are proxied without exposing bridge management concepts to the model.

`BridgeManager` creates all bridge session records and stores through async repository and factory ports. It publishes fully resolved immutable endpoint revisions from `TopologyReader`, so runtime code does not join persistence records or depend on SQLAlchemy. The stable `/mcp/{endpoint_slug}` dispatcher correlates each downstream `mcp-session-id` with one isolated bridge session runtime, as defined by [ADR 0001](decisions/0001-managed-endpoints-and-session-ownership.md).

## Refactor Status

This document describes the staged implementation of [ADR 0006](decisions/0006-core-service-and-server-packages.md). MCP SDK mapping and downstream method behavior now live in bridge core; routing, runtime, and raw downstream transport hosting remain in the monolith during the next extraction steps. The target cross-package API is defined by the [bridge core contract](bridge-core-contract.md).

The target ownership is:

```mermaid
flowchart LR
        Server["Deployable server"] --> Service["Gateway and Agent Host services"]
        Server --> Core["Bridge core"]
        Service --> Core
        Core --> SDK["MCP Python SDK adapter"]
        Service --> Ports["Persistence ports"]
        Server --> SQLite["SQLite adapters"]
        SQLite --> Ports
```

- Bridge core currently owns protocol models, MCP SDK mapping, and downstream method handlers. It
    will also own routing, upstream owner tasks, caches, and raw downstream MCP transports.
- Gateway service owns managed topology, immutable revision publication, session coordination,
    durable event semantics, Agent Host contracts, and persistence ports.
- Deployable server owns FastAPI/Uvicorn lifecycle, transport route selection, SQLite/Alembic,
    concrete agent adapters, static frontend serving, and deployment assembly.
- Core reports typed observations to service. Routers and handlers no longer write directly to
    `BridgeSessionStore`; manager composition connects `JournalBridgeObserver` to the transitional
    store journal adapter.

Runtime, routing, and raw downstream transport files have not moved to their target package yet.
The ownership below reflects the current package boundary while physical extraction continues.

## Responsibility Model

```mermaid
flowchart TD
    Client["Agent Runtime / Inspector"] --> |"streamable HTTP / SSE fallback"| API["Stable MCP dispatcher"]
    API --> Manager["BridgeManager"]
    Manager --> Topology["TopologyReader"]
    Manager --> Endpoint["PublishedEndpoint"]
    Manager --> Repositories["Async repositories"]
    Manager --> Factory["BridgeSessionStoreFactory"]
    Manager --> SessionRuntime["BridgeSessionRuntime"]
    Endpoint --> SessionRuntime
    SessionRuntime --> Downstream["BridgeDownstreamServer"]
    Downstream --> Handlers["ProxyHandlers (bridge-core)"]
    SessionRuntime --> Router["McpSessionRouter"]
    Handlers --> Adapter["CoreRouterAdapter"]
    Adapter --> Router
    Router --> Runtime["UpstreamRuntime"]
    Runtime --> Upstream["UpstreamMcpClient"]
    Upstream --> Real["Real MCP Server"]

    Factory --> Store["BridgeSessionStore"]
    Manager --> Observer["JournalBridgeObserver"]
    Router --> Observer
    Handlers --> Observer
    Observer --> Journal["BridgeSessionStoreJournal"]
    Journal --> Store
    Runtime --> Cache[("Tool/resource cache")]
    Handlers --> Mapper["_mcp_sdk.py (bridge-core)"]

    subgraph "mcp/ package"
        Manager
        Endpoint
        SessionRuntime
        Downstream
        Adapter
        Router
        Runtime
        Upstream
    end

    subgraph "bridge-core package"
        Handlers
        Mapper
    end
```

The important ownership rule is that lifecycle flows from the host into `BridgeManager`, then into isolated bridge session runtimes. The CLI and FastAPI application never construct session stores or upstream clients. The dispatcher identifies endpoints and transports requests, while the manager creates and closes the downstream server, router, bound upstream runtimes, observer, journal adapter, and store as one bridge-session-scoped unit. The manager task group also hosts one persistent upstream worker per binding, as defined by [ADR 0005](decisions/0005-upstream-transport-task-ownership.md).

## Modules

### `manager.py` - Endpoint, Session, and Lifecycle Ownership

`BridgeManager` is the system-level MCP owner for the backend process. It publishes endpoint revisions and their core `EndpointPlan` values, creates session records and stores, composes the journal observer boundary, tracks transport-session bindings, and provides the lifecycle context used by FastAPI. Management repositories remain available for topology mutations, while publication and session routing consume the behavior-oriented `TopologyReader` port.

`PublishedEndpoint` binds stable topology only:

- `revision`: the complete immutable endpoint topology revision selected at publication time.
- `path`: the derived downstream path `/mcp/{slug}`.

`BridgeSessionRuntime` owns the live objects for one bridge session:

- The bridge domain session ID and endpoint ID.
- One `McpSessionRouter`: either a transparent `PassthroughRouter` or an `AggregateRouter` over multiple bound upstream runtimes.
- One `BridgeDownstreamServer` and streamable HTTP session manager.
- Structured stop and closed events managed by the manager task group.

Session creation is repository-backed and atomic with session-store creation. Each session stores the exact `endpoint_revision_id` from its published endpoint; changing the current topology head cannot change an active session's routing plan. A new streamable HTTP initialization request starts a session runtime before dispatch. The dispatcher captures the SDK-generated `mcp-session-id` response header and persists the binding before sending that header to the client. Later requests resolve the same runtime through the repository binding. `DELETE` is handled by the MCP SDK first and then closes only the correlated bridge session runtime. For SSE fallback, the dispatcher captures the SDK session ID from the initial `endpoint` event, routes `/mcp/{slug}/messages` by that query ID, and closes the isolated runtime when the SSE connection ends.

### `upstream.py` - Upstream MCP Clients

`upstream.py` connects to real MCP servers and normalizes SDK responses into bridge models.

Key types:

| Type | Role |
| --- | --- |
| `UpstreamServerConfig` | Transport-agnostic upstream config for `stdio`, `sse`, or `streamable-http` |
| `UpstreamMcpClient` | Protocol implemented by all upstream clients |
| `UpstreamMcpClientFactory` | Creates a fresh upstream client for each isolated bridge session |
| `StdioUpstreamMcpClient` | stdio upstream transport |
| `SseUpstreamMcpClient` | legacy SSE upstream transport |
| `StreamableHttpUpstreamMcpClient` | streamable HTTP upstream transport |
| `build_upstream_client()` | Factory for selecting the transport client |

Boundary rules:

- Does not know about FastAPI, downstream routes, or session event storage.
- Returns internal models such as `ToolDescriptor`, `ToolCallResult`, `AppResource`, and `UpstreamInitialization`.

### `runtime.py` - Single-Upstream Runtime

`UpstreamRuntime` owns one upstream MCP session. A persistent worker task executes its client operations through an internal command channel. The worker enters, uses, reconnects, and exits MCP SDK transport contexts in the same task because their AnyIO cancel scopes cannot move between request or discovery tasks. The runtime tracks upstream identity, refreshes tool/resource metadata, caches loaded resources, and synthesizes UI resources when needed. It does not publish session-global state.

Key methods:

| Method | Role |
| --- | --- |
| `start_worker()` / `shutdown_worker()` | Start and stop the manager-hosted transport owner task |
| `start()` / `close()` | Connect and disconnect the upstream MCP client |
| `refresh_tools()` | Pull tools from upstream and update the local cache |
| `refresh_resources()` | Pull resources, or synthesize UI resources from tool metadata when upstream listing is unavailable |
| `call_tool()` | Forward `tools/call` to the upstream client |
| `preload_tool_resource()` | Load a tool's MCP App UI resource after a tool call when metadata provides one |
| `read_and_cache_resource()` | Read and cache upstream resources |
| `identity` | Exposes upstream `serverInfo` for downstream initialization responses |

Boundary rules:

- Knows about upstream clients and bridge-side caches.
- Serializes one stateful upstream session while allowing different aggregate bindings to run concurrently.
- Does not know about the MCP SDK `Server`, Starlette scopes, FastAPI, or HTTP routing.

### `router.py` - Session MCP Routing

`McpSessionRouter` is the current application contract for lifecycle, identity, tools, and resources. `CoreRouterAdapter` converts its transitional models to the core-owned `McpMethodRouter` contract used by handlers. `PassthroughRouter` adapts one `UpstreamRuntime` without changing public protocol behavior. `AggregateRouter` composes immutable binding revisions and lazy bound runtimes, performs concurrent deterministic discovery, publishes healthy results during partial failures, routes namespaced tool calls, and owns public resource URI maps.

Boundary rules:

- Owns public-to-upstream method routing for one bridge session.
- Emits typed session-global tool/resource publication and binding availability observations.
- Does not own downstream MCP transport objects or persistence implementation details.
- The temporary adapter keeps core `ProxyHandlers` independent of monolith models and topology.

### `downstream.py` - Downstream MCP Transport Host

`BridgeDownstreamServer` owns the MCP SDK `Server` and downstream transports: streamable HTTP, SSE fallback, and stdio serving when needed.

Key methods:

| Method | Role |
| --- | --- |
| `handle_streamable_http(scope, receive, send)` | Streamable HTTP request dispatch |
| `handle_sse(scope, receive, send)` | Legacy SSE connection flow |
| `handle_sse_post(scope, receive, send)` | Legacy SSE message posting |
| `run_http_transports()` | Async context for the streamable HTTP session manager |
| `serve_stdio()` | stdio transport loop |

Identity presentation uses a runtime-provided identity callback, so downstream initialization can reflect the real upstream server rather than a bridge-internal name.

Boundary rules:

- Knows about MCP SDK transport primitives and core-owned `ProxyHandlers`.
- Does not start, close, or otherwise own the upstream runtime.
- Does not access caches or session state directly.

### `bridge-core/handlers.py` - MCP Method Handlers

`ProxyHandlers` registers and implements the MCP methods exposed by one downstream server:

- `tools/list`
- `tools/call`
- `resources/list`
- `resources/read`

It emits correlated tool call observations, delegates protocol work to the core-typed
`McpMethodRouter`, and uses the internal MCP SDK adapter for conversion.

Boundary rules:

- Owns MCP method behavior, not transport setup.
- May call `McpMethodRouter` and `BridgeObserver`; it does not import application or session
    storage packages.
- Should remain a class so debugging and future handler-level dependencies stay explicit.

### Core MCP SDK and Transitional Model Adapters

`bridge-core/_mcp_sdk.py` is stateless conversion code between core models and MCP SDK v1 types.
The monolith `core_mapper.py` and `core_router_adapter.py` temporarily convert existing application
models and router results to core contracts; they disappear as routing moves into core.

Key functions:

| Function | Converts |
| --- | --- |
| `to_mcp_tool(tool)` | `ToolDescriptor` to `mcp.types.Tool` |
| `to_mcp_call_tool_result(result)` | `ToolCallResult` to `mcp.types.CallToolResult` |
| `to_mcp_resource(resource)` | `ResourceDescriptor` to `mcp.types.Resource` |
| `to_read_resource_contents(resource)` | `AppResource` to `ReadResourceContents` |
| `_to_content_block(item)` | bridge content dictionaries to MCP content blocks |

Boundary rules:

- Pure functions only.
- No async, no I/O, no session state, no transport objects.

### `bootstrap.py` and `builder.py` - Application Assembly

`bootstrap.py` is the application composition root. It converts resolved YAML topology into seed domain definitions, opens configured SQLite storage, applies migrations when configured, seeds an empty database with revision 1, marks interrupted sessions as failed, and assembles `BridgeManager`. Normal and debug entry points use this same path. After the first seed, managed topology in SQLite is authoritative.

`builder.py` provides repository-based manager assembly and transport configuration conversion. Neither module constructs live session state directly.

Boundary rules:

- Assembly is allowed to import multiple MCP submodules because it wires ownership boundaries together.
- Runtime behavior should live in the owning modules, not in the factory.

## Request Lifecycle: `tools/call`

```mermaid
sequenceDiagram
    participant Client as Agent / Inspector
    participant API as Stable Dispatcher
    participant Manager as BridgeManager
    participant DS as Downstream Server
    participant H as ProxyHandlers
    participant Adapter as CoreRouterAdapter
    participant Router as McpSessionRouter
    participant RT as UpstreamRuntime
    participant UP as Upstream Client
    participant Real as Real MCP Server
    participant Observer as BridgeObserver
    participant Journal as SessionJournal
    participant Store as BridgeSessionStore

    Client->>API: tools/call
    API->>Manager: resolve mcp-session-id
    Manager-->>API: BridgeSessionRuntime
    API->>DS: handle_streamable_http(...)
    DS->>H: call_tool(name, arguments)
    H->>Observer: ToolCallStarted(operation_key, ...)
    Observer->>Journal: append application event
    Journal->>Store: start_tool_call(operation_key, ...)
    H->>Adapter: call_tool(public_name, arguments)
    Adapter->>Router: call_tool(public_name, arguments)
    Router->>RT: call_tool(upstream_name, arguments)
    RT->>UP: call_tool(name, arguments)
    UP->>Real: MCP tools/call
    Real-->>UP: tool result
    UP-->>RT: ToolCallResult
    RT-->>Router: ToolCallResult
    Router-->>Adapter: Public ToolCallResult
    Adapter-->>H: Core ToolCallResult
    H->>Observer: ToolCallCompleted(operation_key, ...)
    Observer->>Journal: append application event
    Journal->>Store: complete_tool_call(operation_key, ...)
    H->>Adapter: preload_tool_resource(public_name)
    Adapter->>Router: preload_tool_resource(public_name)
    Router->>RT: read_and_cache_resource(upstream_ui_uri)
    H-->>DS: mapped CallToolResult
    DS-->>Client: MCP response
```

## Accepted Managed-Host Topology

Multiple MCP endpoints share one listener and are distinguished by path:

```text
/mcp/github       -> passthrough endpoint -> GitHub upstream
/mcp/filesystem   -> passthrough endpoint -> Filesystem upstream
/mcp/all          -> aggregate endpoint   -> GitHub + Filesystem
```

Endpoints do not require separate TCP ports or static FastAPI route declarations. The stable `/mcp/{endpoint_slug}` dispatcher resolves endpoint definitions at request time. Each active bridge session owns an independent MCP SDK `Server`, downstream transport session manager, router, and set of bound upstream runtimes.

Passthrough endpoints remain transparent and bind one upstream. Aggregate endpoints use stable binding namespaces to route tool names and ordinary resource URIs, preserve `ui://` for MCP Apps, and continue serving healthy bindings when another binding fails.

`BridgeManager` owns the domain side of the following session relationship:

```mermaid
flowchart LR
    Transport["MCP transport session ID"] --> Bridge["BridgeSession"]
    Bridge --> One["UpstreamSession: github"]
    Bridge --> Two["UpstreamSession: filesystem"]
```

Upstream sessions are isolated per bridge session and opened lazily by default. Shared upstream sessions are an explicit policy, never a transport-derived assumption. Streamable HTTP remains the strategic transport; stdio follows the same lifecycle contracts and does not introduce a separate process-pooling architecture.

The dispatcher and manager implement transport-session binding, reverse lookup, isolated upstream lifecycle, and per-session deletion. SQLAlchemy-backed repositories and session stores persist topology, session records, events, and snapshots without exposing database sessions to the MCP runtime or ASGI dispatch contracts.
