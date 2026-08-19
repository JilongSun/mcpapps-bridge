# ADR 0006: Core, Service, and Server Packages

- Status: Accepted
- Date: 2026-08-16
- Accepted: 2026-08-17

## Context

The current backend grew from one bridge process into an aggregate MCP gateway, persistent
management domain, session inspection service, planned Agent Host, and deployable web product.
`BridgeManager` now coordinates protocol runtime objects, repositories, session persistence,
endpoint publication, and downstream hosting. This is workable for one application, but it makes
the protocol bridge difficult to reuse and increases the blast radius of MCP SDK specification
changes.

The project needs a reusable bridge library, but the whole product should not become one SDK. The
database-backed management plane, Agent Host, FastAPI routes, frontend, and deployment assembly
have different consumers and stability requirements from protocol bridging.

The current environment uses MCP Python SDK 1.28 and already negotiates MCP specification
2025-11-25. The SDK has announced a breaking v2 API, while the project dependency currently has no
`<2` upper bound. Adopting that API at the same boundary that owns persistence and product
lifecycle would mix protocol compatibility work with application migration work.

## Decision

Organize the Python backend as a `uv` workspace containing three dependency-ordered packages.
Package names are internal working names and do not determine the product's future brand.

```text
backend/
|-- pyproject.toml                    # uv workspace and shared development tooling
|-- packages/
|   |-- bridge-core/                  # reusable protocol bridge library
|   `-- gateway-service/              # application use cases and ports
`-- apps/
   `-- server/                       # deployable FastAPI/SQLite product
```

The allowed production dependency graph is:

```text
server ----------------> bridge-core
   `--> gateway-service ---> bridge-core
```

Core must never import service or server code, and service must never import server code. The
server is the composition root and may depend directly on both lower packages.

The frontend consumes server HTTP/WebSocket contracts and does not import Python packages.

The cross-package types, lifecycle, observer events, and failure behavior are defined in the
[bridge core contract](../bridge-core-contract.md). That contract may gain capabilities during the
migration, but it cannot reverse this dependency graph or expose product persistence and framework
types through core.

### Package 1: Bridge core

The core is a reusable asynchronous Python library focused on MCP protocol bridging. It owns:

- Upstream connectors for stdio, SSE compatibility, and streamable HTTP.
- Downstream MCP server adaptation and a framework-neutral ASGI transport adapter.
- Persistent owner-task lifecycle, cancellation, concurrency, and bounded in-memory caches.
- Passthrough and aggregate routing.
- Tool naming, ordinary resource URI namespacing, opaque MCP Apps UI routes, and exact route maps.
- Preservation and mapping of bridge-relevant MCP metadata, including MCP Apps metadata.
- Capability negotiation and exact advertisement of the MCP methods the bridge implements.
- Immutable runtime input types such as `EndpointPlan` and `BindingPlan`.
- A small explicit facade such as `BridgeEngine`, `BridgeSession`, and `BridgeObserver`.

The core does not own:

- FastAPI, Uvicorn, YAML, SQLAlchemy, Alembic, or a database schema.
- Managed topology heads, administrative CRUD, historical session records, or product policies.
- Agent runtimes, OpenAI-compatible HTTP contracts, Hermes behavior, or frontend rendering.
- Product logging configuration. Library modules use normal Python loggers and leave handlers and
  formatting to the host.

MCP Apps metadata preservation and URI routing remain in core because they are protocol bridge
semantics. Rendering widgets, processing host actions, and persisting UI activity remain outside
core.

Core owns the collision-safe routing mechanisms and validates namespaces supplied in an
`EndpointPlan`. Service policy chooses the endpoint mode, bindings, namespace identities, enabled
capabilities, and publication lifecycle. Core does not derive managed namespaces from database
records or decide which upstreams a product should expose.

The core package API uses project-owned bridge types rather than exporting MCP Python SDK classes.
It does not reproduce the entire MCP schema. It normalizes only the state required for routing and
preserves unknown extension metadata so newer protocol fields are not discarded.

The bridge must not advertise transparency for protocol methods it does not implement. Each
supported capability has explicit forwarding, aggregation, notification, and version behavior;
unsupported capabilities remain unadvertised. Extension fields are preserved at supported
protocol locations rather than recursively rewriting arbitrary JSON.

MCP Python SDK imports and version-specific conversions are isolated behind an internal protocol
adapter. Supported protocol versions are verified through compatibility tests. A specification
upgrade should replace or amend that adapter without changing application-service or persistence
contracts.

### Package 2: Gateway and Agent Host services

The service package owns application use cases and bounded contexts:

- Managed upstreams, endpoints, bindings, immutable revision publication, and policy validation.
- Bridge session coordination and translation from a stored revision into a core `EndpointPlan`.
- Session events, snapshots, inspection, and application-level audit behavior.
- MCP Apps host workflows such as UI actions and links between tool activity and rendered resources.
- Provider-neutral Agent Host run/event contracts and agent adapter ports.
- Management, gateway, and Agent Host authorization requirements as application policies.

Persistence abstractions belong here because persistence serves these use cases, not protocol
bridging. They should be narrow `Protocol` ports named for behavior, such as `TopologyStore`,
`RevisionPublisher`, `SessionJournal`, and `UnitOfWork`. The service package must not define a
generic `BaseRepository[T]` or expose ORM query concepts.

Developers may implement these ports for another database or embedding environment. The product
continues to ship one supported SQLite adapter. An in-memory implementation may exist as a test or
example adapter, but it is not a second production storage profile and does not weaken SQLite's
authority in the packaged server.

The service observes core events through `BridgeObserver` or an equivalent event sink. Core routers
and protocol handlers no longer write directly to `BridgeSessionStore`.

### Package 3: Deployable server

The server package is the product composition and infrastructure layer. It owns:

- FastAPI routes for management, session inspection, health/readiness, and OpenAI compatibility.
- Mounting the core MCP ASGI adapter under stable endpoint paths.
- Uvicorn startup, CLI commands, configuration loading, and product logging setup.
- SQLAlchemy SQLite adapters, Alembic migrations, seed/import commands, and credentials integration.
- Hermes HTTP/SSE and other concrete outbound agent adapters.
- Static frontend serving, OCI image assembly, and deployment defaults.

FastAPI lifespan belongs in this package. It creates a server container/composition root, opens
database and application services, starts core runtimes as required, mounts inbound adapters, and
closes resources in reverse order. Neither core nor service imports FastAPI or relies on FastAPI to
be usable.

The raw MCP ASGI transport may live in core because it is a protocol transport adapter, but route
selection, management endpoints, application lifespan, and process serving remain in server.

### SDK and release compatibility

Version 0.1 keeps core as an internal `uv` workspace package. It is not published to PyPI, emitted
as a separately supported release artifact, or presented as a stable embedded SDK. Its explicit
package facade exists to enforce ownership and enable later reuse, not to create a v0.1 external
compatibility promise. ADR 0004's SDK exclusion therefore remains unchanged.

Version 0.1 targets MCP specification 2025-11-25 for the capabilities in its release scope. It
does not implement cross-version protocol conversion or promise tested compatibility with older
profiles. The core dependency is constrained to MCP Python SDK v1 for this release. SDK v2,
post-2025 protocol profiles, and compatibility-conversion policy require a later decision after
the package boundary and v0.1 behavior are stable.

SQLite infrastructure remains directly inside the server package for v0.1. A separate first-party
storage adapter package is deferred until a second product composition demonstrates that it is
useful.

## Current-to-Target Mapping

| Current area | Target owner |
| --- | --- |
| Upstream owner-task runtime, moved from `mcp/runtime.py` to core | Bridge core |
| Upstream SDK connectors, moved from `mcp/upstream.py` to core | Bridge core |
| MCP SDK mapping, moved from `mcp/mapper.py` to core | Bridge core |
| MCP method handlers, moved from `mcp/handlers.py` to core | Bridge core |
| Protocol portions of `mcp/downstream.py` | Bridge core |
| Passthrough and aggregate routing, moved from `mcp/router.py` to core | Bridge core |
| Session-store writes currently inside handlers and routers | Service observer/application use cases |
| `domain/`, `repositories/`, `session/`, `events/` | Gateway service, simplified around use-case ports |
| `mcp/manager.py` | Split into core engine, service session coordinator, and server composition |
| `api/`, `host/`, `config/`, `bootstrap.py`, `main.py` | Deployable server |
| `persistence/` and migrations | Server-owned SQLite adapter |
| `agent_adapters/` | Service ports plus server-owned concrete adapters |

## Migration Strategy

1. Constrain MCP Python SDK to `>=1.28,<2` and freeze current transparent gateway behavior with
   2025-11-25 protocol-level integration tests before moving modules.
2. Define the core public facade and immutable endpoint plan without changing runtime behavior.
3. Replace direct session-store dependencies in routers and handlers with observer events.
4. Move protocol runtime and routing into the core package and enforce import boundaries.
5. Move management and session orchestration into application services with narrow persistence
   ports.
6. Rebuild the server composition root, FastAPI adapters, and SQLite adapter around those ports.
7. Run the 2025-11-25 protocol contract suite across the extracted core and composed server.
8. Implement the remaining v0.1 management and Agent Host APIs against the new service contracts.

MCP Python SDK v2 and later protocol profiles are not part of this migration. Deferring them keeps
protocol compatibility work distinguishable from ownership and import errors.

## Consequences

- The bridge can be embedded without FastAPI, SQLite, or the product management plane.
- The deployable product keeps one supported and coherent SQLite configuration while custom hosts
  can implement service ports.
- MCP SDK breaking changes are contained within the bridge core compatibility boundary.
- FastAPI becomes an inbound adapter and composition host rather than the owner of domain behavior.
- Three packages add workspace and build-management overhead and require explicit package-facade
  and dependency-boundary tests.
- Existing database schema, migrations, module paths, and provisional tests may be replaced during
  the pre-release migration, but protocol compatibility tests remain mandatory.

## Deferred Decisions

- Whether and when to publish bridge core as an independently supported package.
- MCP Python SDK v2 migration and the compatibility policy for protocol profiles after
  2025-11-25.
- Extraction of SQLite infrastructure into a reusable first-party adapter package.
- A post-v0.1 project name and external interface refactor. The new product name does not need to
  describe its feature set, and branding must not become a dependency between internal packages.

## Implementation Status

As of 2026-08-18, implementation is partial.

### Implemented

- MCP Python SDK is constrained to `>=1.28,<2` for the v0.1 migration.
- The backend is a `uv` workspace with internal bridge-core, gateway-service, and server members;
  their declared dependencies follow the accepted direction.
- Bridge core owns frozen runtime plan and protocol models, typed observations, the observer port,
  and a no-op observer without importing the monolith, FastAPI, or persistence.
- Gateway service owns resolved topology DTOs, conversion to core `EndpointPlan`, application
  journal events, and the core-observation-to-journal adapter.
- Published endpoints now carry both the existing managed revision and its core plan. Immutable
  endpoint, binding, and upstream revision keys survive the conversion.
- Routers and protocol handlers emit typed observations instead of importing or writing directly
  to `BridgeSessionStore`; manager composition adapts those observations to the current durable
  store during migration.
- Bridge core owns the MCP SDK v1 conversion adapter, its compatibility tests, the downstream MCP
  method handlers, and the narrow core-typed `McpMethodRouter` contract.
- Bridge core owns the persistent upstream owner-task runtime and passthrough/aggregate routers.
  Routers consume immutable `EndpointPlan` and `BindingPlan` values without importing managed
  topology, application availability snapshots, or server models.
- Bridge core owns stdio, SSE compatibility, and streamable HTTP upstream connectors. They map MCP
  SDK responses directly to core protocol models and are selected through a core-owned factory.
- Aggregate characterization coverage freezes namespaced tools, ordinary and opaque UI resource
  routes, MCP Apps metadata rewriting, protocol-defined tool result rewriting, and rejection of
  unregistered resource URIs.
- The existing owner-task regression freezes upstream transport context ownership.
- Cross-package plans, facade responsibilities, observer events, and lifecycle invariants are
  specified in the bridge core contract.

### Pending

- Move raw downstream transport adapters into bridge core.
- Split `BridgeManager` into core engine, application session service, and server composition.
- Recompose SQLite, FastAPI, configuration, and process lifecycle in the server package.
- Add real MCP 2025-11-25 transport contract tests across the extracted core and composed server.
