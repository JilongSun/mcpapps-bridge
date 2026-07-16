# ADR 0001: Managed Endpoints and Session Ownership

- Status: Accepted; endpoint priority amended by ADR 0003
- Date: 2026-07-13

## Context

The bridge started as a single MCP Apps proxy with one configured upstream server, one downstream MCP endpoint, and one in-memory session state. The project is expanding into a managed MCP host that can register servers, publish MCP endpoints, add bridge capabilities, and expose an administrative control plane.

The original runtime model conflates four lifecycles:

- An upstream MCP server registered with the host.
- A downstream MCP endpoint published by the host.
- A downstream client session established through an endpoint.
- An upstream MCP session opened on behalf of that client session.

Keeping these lifecycles coupled would make multi-server routing unsafe. In particular, multiple downstream clients could share a stateful upstream MCP session unintentionally, and configuration objects could become mixed with live transport objects.

## Decision

### Managed topology

The management domain uses four distinct concepts:

| Concept | Purpose |
| --- | --- |
| `UpstreamServerDefinition` | Persistent configuration for one real MCP server |
| `EndpointDefinition` | Persistent configuration for one downstream MCP endpoint |
| `BridgeSessionRecord` | One downstream client session using an endpoint |
| `UpstreamSessionRecord` | One upstream MCP connection associated with a bridge session |

`EndpointBinding` connects an endpoint to an upstream server. Definitions and records are serializable domain objects; live MCP clients, SDK servers, task groups, and database sessions are runtime infrastructure and must not be stored in them.

### One listener, multiple endpoints

All downstream MCP endpoints share one ASGI listener and one configured host/port. Endpoint identity is expressed through the URL path:

```text
/mcp/github       -> passthrough endpoint
/mcp/filesystem   -> passthrough endpoint
/mcp/all          -> aggregate endpoint
```

The host uses a stable dispatcher at `/mcp/{endpoint_slug}`. Adding or removing a managed endpoint does not require another TCP port or a dynamic FastAPI route declaration.

### Hybrid endpoint modes

ADR 0003 later made aggregate the primary publication strategy and retained passthrough as a lower-priority compatibility and diagnostic strategy. The ownership and protocol behavior below remain valid.

The two endpoint modes have distinct protocol behavior:

- `passthrough` binds exactly one enabled upstream server. It preserves upstream tool names, resource URIs, initialization metadata, and MCP Apps metadata wherever protocol compatibility permits.
- `aggregate` binds one or more enabled upstream servers. Every binding has a unique namespace used for collision-safe tool and resource routing.

Aggregate tools will use a stable public name derived from the binding namespace and upstream tool name, for example `github__search_issues`. Aggregate resource mapping must be reversible and collision-safe. The exact exposed URI encoding will be decided with the aggregate mapper implementation; passthrough endpoints do not rewrite resource URIs.

### Session ownership and cardinality

`BridgeManager` owns bridge session creation, lookup, activity tracking, and closure. Neither `main.py` nor the FastAPI application creates session state directly.

The default upstream session policy is `isolated`:

```text
BridgeSession A -> UpstreamSession A1, A2, ...
BridgeSession B -> UpstreamSession B1, B2, ...
```

An isolated upstream MCP connection belongs to one bridge session. Aggregate endpoints open only the upstream connections needed by that bridge session. Connections are lazy by default.

The `shared` policy is an explicit opt-in for upstream deployments known to be safe for shared use. It must never be inferred from transport type.

The MCP SDK transport session ID (`mcp-session-id`) is correlated with a `BridgeSessionRecord`, but it is not the bridge's domain session ID. Transport session state remains owned by the MCP SDK.

### Transport strategy

Streamable HTTP is the primary upstream and downstream transport. SSE remains a compatibility fallback. Stdio remains supported but does not receive special pooling, process-count, or routing architecture: each configured stdio server follows the same endpoint and session policy contracts as other transports.

### Configuration authority

Configuration is layered by responsibility rather than by field-level overriding:

- YAML and environment variables configure the host process, database connection, logging, and bootstrap behavior.
- The database is authoritative for managed upstream servers, endpoints, bindings, and session policies.
- A YAML topology manifest may seed an empty database or be applied through an explicit import operation. Startup must not silently overwrite administrative changes stored in the database.

### Persistence boundary

Domain models are independent from SQLAlchemy ORM models. Async repositories and a unit of work will translate between ORM rows and domain objects. Runtime code must not expose `AsyncSession` outside the persistence layer.

SQLite with `aiosqlite` is the first supported database. The persistence API remains compatible with later PostgreSQL support through SQLAlchemy's async API.

## Consequences

- Multi-server support does not multiply listening ports.
- Each active passthrough bridge session owns an independent MCP SDK `Server`, transport session manager, upstream runtime, and session store.
- Process-level session construction, the fixed `BridgeSessionState`, and endpoint bootstrap sessions have been removed.
- Aggregate endpoint support requires explicit tool-name and resource-URI routing tables.
- Isolated sessions may open multiple upstream connections, but correctness takes priority over implicit connection sharing.
- Administrative CRUD can change managed topology without making YAML the runtime source of truth.

## Implementation Sequence

1. Introduce topology and session domain contracts without changing runtime behavior. Complete.
2. Add in-memory repositories and refactor `BridgeManager` around endpoint and session ownership. Complete.
3. Replace static route mounts with a stable endpoint dispatcher and isolated passthrough runtimes. Complete.
4. Add async SQLAlchemy persistence, repositories, a unit of work, and a session store factory.
5. Implement multiple passthrough endpoints.
6. Implement aggregate tool/resource routing and lazy per-session upstream connections.
7. Expose administrative CRUD through the control-plane API.
