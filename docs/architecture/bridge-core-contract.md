# Bridge Core Contract

This document defines the cross-package contract accepted by
[ADR 0006](decisions/0006-core-service-and-server-packages.md). It is the implementation boundary
for the pre-v0.1 refactor. Names are working names until types exist in code, but ownership and
dependency direction are normative.

## Contract Scope

Bridge core is an asynchronous MCP protocol bridge. It accepts a complete immutable runtime plan,
opens one bridge session, forwards supported MCP operations, and emits typed observations. It does
not discover product topology, query repositories, persist history, expose management APIs, or run
agents.

The v0.1 contract targets MCP specification 2025-11-25 for:

- `initialize`
- `tools/list`
- `tools/call`
- `resources/list`
- `resources/read`
- MCP Apps metadata and resource references at supported protocol locations

Unsupported methods and notifications are not advertised. Prompt aggregation, list-changed
notifications, protocol conversion, and MCP Python SDK v2 are later contract additions.

## Runtime Plans

Gateway service resolves database-backed topology into core-owned frozen Pydantic models before a
session opens.

### `EndpointPlan`

| Field | Meaning |
| --- | --- |
| `endpoint_key: str` | Opaque application identity used only for correlation |
| `display_name: str` | Downstream MCP server presentation |
| `mode: EndpointMode` | `passthrough` or `aggregate` |
| `bindings: tuple[BindingPlan, ...]` | Complete immutable bindings for this session |
| `capabilities: BridgeCapabilities` | Explicit methods and notifications enabled for the session |

### `BindingPlan`

| Field | Meaning |
| --- | --- |
| `binding_key: str` | Opaque application identity used in observations |
| `namespace: str | None` | Required for aggregate and forbidden for passthrough |
| `priority: int` | Stable discovery ordering |
| `upstream: UpstreamConfig` | Core-owned stdio, SSE, or streamable HTTP connection model |

Core validates plan shape but does not choose namespaces, bindings, endpoint publication, or
credentials. Service owns those policies and passes already resolved values. Database revision
IDs may be encoded as opaque keys, but core never interprets their format.

Plans cannot mutate after `open_session`. A topology mutation creates a new stored revision and a
new plan for later sessions.

## Facade And Lifecycle

### `BridgeEngine`

`BridgeEngine` owns the AnyIO task group that hosts upstream owner tasks. Its package facade
provides an async context manager and one operation:

```python
async with BridgeEngine(client_factory=client_factory) as engine:
    session = await engine.open_session(
        session_key=session_key,
        plan=endpoint_plan,
        observer=observer,
    )
```

Rules:

- The engine must be entered before sessions open.
- `session_key` is supplied by service and treated as opaque by core.
- Closing the engine closes all remaining sessions in reverse ownership order.
- Core does not create database records or application session identifiers.

### `BridgeSession`

One `BridgeSession` owns one immutable plan, one router, and one `UpstreamRuntime` per enabled
binding. It exposes project-owned models through these operations:

- `identity`
- `list_tools()`
- `call_tool(name, arguments)`
- `list_resources()`
- `read_resource(uri)`
- `aclose()`

`aclose()` is idempotent. A binding's upstream SDK session is entered, used, reconnected, and
closed by one persistent owner task. Different aggregate bindings may execute concurrently; one
binding serializes its stateful upstream operations.

The package facade does not export MCP Python SDK classes. A version-specific adapter maps between
SDK classes and core models.

### Downstream adapters

A core-owned MCP server adapter maps MCP 2025-11-25 requests to `BridgeSession` operations. A raw
ASGI transport adapter may host streamable HTTP and SSE compatibility without importing FastAPI.
The server package selects routes, correlates transport session IDs, and controls process lifespan.

## Observer Boundary

Core emits immutable Pydantic events through one asynchronous contract:

```python
class BridgeObserver(Protocol):
    async def observe(self, event: BridgeObservation) -> None: ...
```

`BridgeObservation` is a discriminated union with these v0.1 events:

| Event | Required correlation |
| --- | --- |
| `BridgeSessionStarted` | session key and downstream identity |
| `BindingAvailabilityChanged` | session key, binding key, `unknown`/`available`/`failed` status, identity or failure |
| `ToolsPublished` | session key and complete public tool descriptors |
| `ToolCallStarted` | session key, operation key, public tool name, and arguments |
| `ToolCallCompleted` | session key, operation key, public result or typed failure |
| `ResourceLoaded` | session key, optional binding key, and public resource |
| `BridgeErrorRaised` | session key, operation context, and typed failure |

Core generates an opaque operation key for tool-call correlation. Service wraps observations in
its durable event envelope, assigns persistence ordering, and updates snapshots. Core does not
import application event envelopes or `BridgeSessionStore`.

Observation delivery is awaited in operation order for one bridge session. Core does not retry,
buffer durably, or silently swallow observer failures. Server composition injects either a strict
observer or a policy wrapper that records and suppresses failures. This makes failure policy
explicit without putting persistence behavior in core.

A no-op observer is part of core so embedding does not require the gateway service.

## Routing Invariants

- Passthrough preserves upstream tool names and resource URIs.
- Aggregate tool names always use `{namespace}__{upstream_name}`.
- Aggregate ordinary resources use `{namespace}+{original_uri}` without hiding the original URI.
- Aggregate MCP Apps resources retain `ui://` and use an opaque route token.
- Public resource URIs are routing authority only after exact registration in the session route
  table. Decodable or well-formed forged URIs are rejected.
- MCP Apps metadata is rewritten only at supported protocol-defined locations.
- `ResourceLink.uri` and `EmbeddedResource.resource.uri` in tool results are rewritten; arbitrary
  text, structured content, and extension metadata are not recursively scanned.
- Unknown extension metadata at supported objects is preserved unless a documented adapter rule
  rewrites it.
- Degraded aggregate discovery returns deterministic healthy results and reports binding-scoped
  failures. A targeted operation depends only on its routed binding.

## Failure Contract

Core exposes typed failures rather than requiring service or server code to parse exception text.
The initial hierarchy distinguishes:

- invalid plans;
- unknown public tools and resources;
- unavailable bindings and upstream transport failures;
- upstream protocol failures;
- unsupported capabilities;
- protocol adapter failures.

The downstream MCP adapter converts these failures to protocol responses. The service observer
converts them to application events. FastAPI and OpenAI adapters map only application failures and
do not import MCP SDK exception classes.

## Migration Gates

Each extraction step must preserve these checks:

1. Aggregate router characterization tests pass without FastAPI or SQLite.
2. Upstream connect, operation, reconnect, and close remain in one owner task.
3. Core imports no service, FastAPI, SQLAlchemy, Alembic, YAML, Uvicorn, or agent adapter modules.
4. Service imports core but no server or ORM modules.
5. The server can compose core, service, SQLite, and FastAPI without reverse imports.
6. A real MCP 2025-11-25 streamable HTTP test passes initialize, tool/resource discovery, calls,
   reads, and clean shutdown.

The workspace package skeleton, core-owned plan/event models, managed-revision adapter, durable
journal adapter, MCP SDK v1 adapter, downstream method handlers, owner-task runtime, and
passthrough/aggregate routers now exist. Core also owns stdio, SSE compatibility, and streamable
HTTP upstream connectors that map SDK responses directly to core models. Aggregate protocol
characterization, SDK mapping, and owner-task tests run inside the core package without server or
persistence imports. The next implementation slice can move the raw downstream transport adapter
into bridge core.
