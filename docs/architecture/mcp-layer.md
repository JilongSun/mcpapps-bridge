# MCP Layer Architecture

The `mcp/` package is the protocol-aware bridge boundary between downstream MCP clients and real upstream MCP servers. Downstream clients should experience the selected upstream as a normal MCP server: tools, resources, initialization metadata, and MCP Apps annotations are proxied without exposing bridge management concepts to the model.

`BridgeManager` creates all bridge session records and stores through async repository and factory ports. The stable `/mcp/{endpoint_slug}` dispatcher correlates each downstream `mcp-session-id` with one isolated passthrough session runtime, as defined by [ADR 0001](decisions/0001-managed-endpoints-and-session-ownership.md).

## Responsibility Model

```mermaid
flowchart TD
    Client["Agent Runtime / Inspector"] --> |"streamable HTTP / SSE fallback"| API["Stable MCP dispatcher"]
    API --> Manager["BridgeManager"]
    Manager --> Endpoint["PublishedEndpoint"]
    Manager --> Repositories["Async repositories"]
    Manager --> Factory["BridgeSessionStoreFactory"]
    Manager --> SessionRuntime["PassthroughSessionRuntime"]
    Endpoint --> SessionRuntime
    SessionRuntime --> Downstream["BridgeDownstreamServer"]
    Downstream --> Handlers["ProxyHandlers"]
    SessionRuntime --> Runtime["UpstreamRuntime"]
    Handlers --> Runtime
    Runtime --> Upstream["UpstreamMcpClient"]
    Upstream --> Real["Real MCP Server"]

    Factory --> Store["BridgeSessionStore"]
    Runtime --> Store
    Handlers --> Store
    Runtime --> Cache[("Tool/resource cache")]
    Handlers --> Mapper["mapper.py"]

    subgraph "mcp/ package"
        Manager
        Endpoint
        SessionRuntime
        Downstream
        Handlers
        Runtime
        Upstream
        Mapper
    end
```

The important ownership rule is that lifecycle flows from the host into `BridgeManager`, then into isolated passthrough session runtimes. The CLI and FastAPI application never construct session stores or upstream clients. The dispatcher identifies endpoints and transports requests, while the manager creates and closes the downstream server, upstream runtime, and store as one bridge-session-scoped unit.

## Modules

### `manager.py` - Endpoint, Session, and Lifecycle Ownership

`BridgeManager` is the system-level MCP owner for the backend process. It registers upstream definitions, publishes endpoints, creates session records and stores, tracks transport-session bindings, and provides the lifecycle context used by FastAPI.

`PublishedEndpoint` binds stable topology only:

- `definition`: the persistent endpoint domain definition.
- `path`: the derived downstream path `/mcp/{slug}`.
- `upstream_server`: the enabled upstream definition selected by the passthrough binding.

`PassthroughSessionRuntime` owns the live objects for one bridge session:

- The bridge domain session ID and endpoint ID.
- One `UpstreamRuntime` and upstream MCP client.
- One `BridgeDownstreamServer` and streamable HTTP session manager.
- Structured stop and closed events managed by the manager task group.

Session creation is repository-backed and atomic with session-store creation. A new streamable HTTP initialization request starts a session runtime before dispatch. The dispatcher captures the SDK-generated `mcp-session-id` response header and persists the binding before sending that header to the client. Later requests resolve the same runtime through the repository binding. `DELETE` is handled by the MCP SDK first and then closes only the correlated bridge session runtime. For SSE fallback, the dispatcher captures the SDK session ID from the initial `endpoint` event, routes `/mcp/{slug}/messages` by that query ID, and closes the isolated runtime when the SSE connection ends.

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

`UpstreamRuntime` owns one upstream MCP session. It connects to the upstream server, tracks upstream identity, refreshes tool/resource metadata, caches loaded resources, synthesizes UI resources when needed, and records state changes through `BridgeSessionStore`.

Key methods:

| Method | Role |
| --- | --- |
| `start()` / `close()` | Connect and disconnect the upstream MCP client |
| `refresh_tools()` | Pull tools from upstream, update cache, register tools in the session store |
| `refresh_resources()` | Pull resources, or synthesize UI resources from tool metadata when upstream listing is unavailable |
| `call_tool()` | Forward `tools/call` to the upstream client |
| `preload_tool_resource()` | Load a tool's MCP App UI resource after a tool call when metadata provides one |
| `read_and_cache_resource()` | Read and cache upstream resources, then record loaded resources in the session store |
| `identity` | Exposes upstream `serverInfo` for downstream initialization responses |

Boundary rules:

- Knows about upstream clients, bridge session storage, and bridge-side caches.
- Does not know about the MCP SDK `Server`, Starlette scopes, FastAPI, or HTTP routing.

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

- Knows about MCP SDK transport primitives and `ProxyHandlers`.
- Does not start, close, or otherwise own the upstream runtime.
- Does not access caches or session state directly.

### `handlers.py` - MCP Method Handlers

`ProxyHandlers` registers and implements the MCP methods exposed by one downstream server:

- `tools/list`
- `tools/call`
- `resources/list`
- `resources/read`

It records tool call events in the bridge session store, delegates protocol work to `UpstreamRuntime`, and uses `mapper.py` for SDK type conversion.

Boundary rules:

- Owns MCP method behavior, not transport setup.
- May call `UpstreamRuntime` and `BridgeSessionStore`.
- Should remain a class so debugging and future handler-level dependencies stay explicit.

### `mapper.py` - Pure Protocol Mapping

`mapper.py` is stateless conversion code between internal bridge models and MCP SDK types.

Key functions:

| Function | Converts |
| --- | --- |
| `to_mcp_tool(tool)` | `ToolDescriptor` to `mcp.types.Tool` |
| `to_mcp_call_tool_result(result)` | `ToolCallResult` to `mcp.types.CallToolResult` |
| `to_mcp_resource(resource)` | `ResourceDescriptor` to `mcp.types.Resource` |
| `to_read_resource_contents(resource)` | `AppResource` to `ReadResourceContents` |
| `to_content_block(item)` | bridge content dictionaries to MCP content blocks |

Boundary rules:

- Pure functions only.
- No async, no I/O, no session state, no transport objects.

### `builder.py` - Application Assembly

`builder.py` converts the selected YAML upstream into seed domain definitions and wires in-memory repository, session-store, and upstream-client factory adapters. It then asks `BridgeManager` to register the upstream and publish the passthrough endpoint. It never constructs live session state directly.

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
    participant RT as UpstreamRuntime
    participant UP as Upstream Client
    participant Real as Real MCP Server
    participant Store as BridgeSessionStore

    Client->>API: tools/call
    API->>Manager: resolve mcp-session-id
    Manager-->>API: PassthroughSessionRuntime
    API->>DS: handle_streamable_http(...)
    DS->>H: call_tool(name, arguments)
    H->>Store: start_tool_call(...)
    H->>RT: call_tool(name, arguments)
    RT->>UP: call_tool(name, arguments)
    UP->>Real: MCP tools/call
    Real-->>UP: tool result
    UP-->>RT: ToolCallResult
    RT-->>H: ToolCallResult
    H->>Store: complete_tool_call(...)
    H->>RT: preload_tool_resource(name)
    RT->>RT: read_and_cache_resource(ui_resource_uri)
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

Endpoints do not require separate TCP ports or static FastAPI route declarations. The stable `/mcp/{endpoint_slug}` dispatcher resolves endpoint definitions at request time. Each active passthrough bridge session owns an independent MCP SDK `Server` and downstream transport session manager so its handlers cannot accidentally share an upstream runtime with another client.

Passthrough endpoints remain transparent and bind one upstream. Aggregate endpoints are the next core gateway capability after persistence and management foundations; they use stable binding namespaces to route tool names and resource URIs without collisions.

`BridgeManager` owns the domain side of the following session relationship:

```mermaid
flowchart LR
    Transport["MCP transport session ID"] --> Bridge["BridgeSession"]
    Bridge --> One["UpstreamSession: github"]
    Bridge --> Two["UpstreamSession: filesystem"]
```

Upstream sessions are isolated per bridge session and opened lazily by default. Shared upstream sessions are an explicit policy, never a transport-derived assumption. Streamable HTTP remains the strategic transport; stdio follows the same lifecycle contracts and does not introduce a separate process-pooling architecture.

The dispatcher and manager now implement transport-session binding, reverse lookup, isolated upstream lifecycle, and per-session deletion. SQLAlchemy-backed repositories can replace the in-memory adapters without changing the MCP runtime or ASGI dispatch contracts.
